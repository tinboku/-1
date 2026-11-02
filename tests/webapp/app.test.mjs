// Small DOM adapter exercises event lifetimes and view transitions without dependencies.
// This supplements API integration tests; it does not replace a real browser layout check.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const html = await readFile(new URL('../../webapp/index.html', import.meta.url), 'utf8');
const app = await readFile(new URL('../../webapp/js/app.js', import.meta.url), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
class Element {
  constructor() {
    this.value = ''; this.dataset = {}; this.children = []; this.listeners = {}; this.attrs = {};
    this.disabled = false; this.checked = false; this.classes = new Set();
    this.classList = { add: c => this.classes.add(c), remove: c => this.classes.delete(c), contains: c => this.classes.has(c), toggle: (c, on) => on ? this.classes.add(c) : this.classes.delete(c) };
  }
  set innerHTML(value) {
    this.html = value; this.children = [];
    this.inputs = [...value.matchAll(/data-q="([^"]*)" value="([^"]*)"/g)].map(m => Object.assign(new Element(), { dataset: { q: m[1] }, value: m[2] }));
  }
  get innerHTML() { return this.html || ''; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  fire(type, event = {}) { return Promise.all((this.listeners[type] || []).map(fn => fn({ currentTarget: this, ...event }))); }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child); return child; }
  setAttribute(key, value) { this.attrs[key] = value; }
  querySelector(selector) {
    if (selector === '.star-btn') return this.star ||= new Element();
    return this.children.find(child => child.className === selector.slice(1)) || null;
  }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
function workspace(overrides = {}, watchJob = async () => ({ type: 'done', result: {} })) {
  const ids = [...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]);
  assert.equal(ids.length, new Set(ids).size, 'HTML IDs must be unique');
  const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
  const tabs = ['progress', 'paper', 'report', 'table', 'ask'].map(tab => Object.assign(new Element(), { dataset: { tab } }));
  const api = { health: async () => ({}), listJobs: async () => [], listFiles: async () => [], listSearches: async () => [],
    getSearch: async id => ({ id, question: `Q${id}`, criteria: [], papers: [] }), ...overrides };
  const context = vm.createContext({ api, watchJob, document: { getElementById: id => { assert.ok(nodes[id], id); return nodes[id]; },
    createElement: () => new Element(), querySelectorAll: selector => selector === '.tab' ? tabs : selector === '#ns-questions input' ? nodes['ns-questions'].inputs || [] : [] },
    window: { addEventListener() {} }, localStorage: { getItem: () => null, setItem() {} }, URL, console, alert() {} });
  vm.runInContext(app.replace(/import \{ api, watchJob \} from "\.\/api.js";/, '').replace('export function', 'function') + '\nglobalThis.workspace = { openSearch, paperRow, showArtifact, state };', context);
  return { nodes, ...context.workspace };
}
test('clarification answers survive regeneration and reach the launched search with edited criteria', async () => {
  const plans = []; let launched;
  const w = workspace({ plan: async (question, answers) => { plans.push(JSON.parse(JSON.stringify(answers))); return { questions: ['Scope?'], criteria: [answers['Scope?'] || 'draft'] }; },
    launchSearch: async payload => { launched = payload; return { job_id: 'new' }; } });
  await flush();
  w.nodes['ns-question'].value = 'Research question';
  await w.nodes['ns-plan'].fire('click');
  w.nodes['ns-questions'].inputs[0].value = 'tables';
  await w.nodes['ns-questions'].fire('input');
  await w.nodes['ns-plan'].fire('click');
  assert.deepEqual(plans, [{}, { 'Scope?': 'tables' }]);
  assert.equal(w.nodes['ns-questions'].inputs[0].value, 'tables');
  w.nodes['ns-criteria'].value = 'edited criterion';
  await w.nodes['ns-criteria'].fire('input');
  w.nodes['ns-confirm'].checked = true; await w.nodes['ns-confirm'].fire('change');
  await w.nodes['ns-launch'].fire('click');
  assert.equal(launched.answers['Scope?'], 'tables');
  assert.equal(launched.criteria[0], 'edited criterion');
});
test('failed criteria regeneration prevents launching stale criteria', async () => {
  let fail = false, launched = false;
  const w = workspace({ plan: async () => { if (fail) throw new Error('planning unavailable'); return { questions: [], criteria: ['draft'] }; }, launchSearch: () => { launched = true; } });
  await flush(); w.nodes['ns-question'].value = 'Question'; await w.nodes['ns-plan'].fire('click');
  fail = true; await assert.rejects(w.nodes['ns-plan'].fire('click'), /planning unavailable/);
  w.nodes['ns-confirm'].checked = true; await w.nodes['ns-launch'].fire('click');
  assert.equal(launched, false);
});
test('star callback works after currentTarget is invalidated by dispatch', async () => {
  let finish;
  const w = workspace({ setStar: () => new Promise(resolve => { finish = resolve; }) });
  await flush();
  const paper = { db_id: 3, title: 'Paper', starred: false };
  const button = w.paperRow(paper, 'search').querySelector('.star-btn');
  const event = { currentTarget: button, stopPropagation() {} };
  const pending = button.listeners.click[0](event);
  event.currentTarget = null; finish(); await pending;
  assert.equal(paper.starred, true); assert.equal(button.classList.contains('on'), true);
  assert.equal(button.disabled, false);
});
test('switching searches clears artifacts and late results cannot overwrite the new view', async () => {
  const w = workspace({ getFile: async () => ({ content: 'old artifact' }) }); await flush();
  await w.openSearch(1); const oldView = w.state.view;
  w.nodes['report-view'].innerHTML = 'old report'; w.nodes['table-view'].innerHTML = 'old table';
  await w.openSearch(2);
  assert.doesNotMatch(w.nodes['report-view'].innerHTML, /old report/);
  assert.doesNotMatch(w.nodes['table-view'].innerHTML, /old table/);
  await w.showArtifact(7, 'report', oldView);
  assert.doesNotMatch(w.nodes['report-view'].innerHTML, /old artifact/);
});
test('page boot attaches to running jobs before store-backed history can block', async () => {
  const attached = [];
  workspace({ listJobs: async () => [{ id: 'running', kind: 'search', status: 'running' }], listSearches: () => new Promise(() => {}) },
    id => { attached.push(id); return new Promise(() => {}); });
  await flush(); assert.deepEqual(attached, ['running']);
});
