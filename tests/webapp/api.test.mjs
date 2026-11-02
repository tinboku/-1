import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
const source = await readFile(new URL('../../webapp/js/api.js', import.meta.url), 'utf8');
function client(fetcher) {
  const streams = [], timers = [];
  class EventSource {
    constructor(url) { this.url = url; streams.push(this); }
    close() { this.closed = true; }
  }
  const context = vm.createContext({ fetch: fetcher, URLSearchParams, EventSource, setTimeout: fn => timers.push(fn) });
  vm.runInContext(source.replaceAll('export ', '') + '\nglobalThis.client = {api, watchJob};', context);
  return { ...context.client, streams, timers };
}
const response = body => ({ ok: true, status: 200, json: async () => body });
const flush = () => new Promise(resolve => setImmediate(resolve));

test('plan sends the real clarification answers', async () => {
  let payload;
  const { api } = client(async (url, init) => { payload = JSON.parse(init.body); return response({}); });
  await api.plan('question', { Scope: 'tables only' });
  assert.deepEqual(payload.answers, { Scope: 'tables only' });
});
test('folder and lookup query strings preserve special characters', async () => {
  const urls = [];
  const { api } = client(async url => { urls.push(url); return response([]); });
  await api.listPapers(true, 'A&B'); await api.lookupPaper('10.test/a?b');
  assert.equal(new URLSearchParams(urls[0].split('?')[1]).get('folder'), 'A&B');
  assert.equal(new URLSearchParams(urls[1].split('?')[1]).get('identifier'), '10.test/a?b');
});
test('SSE displays actual engine stages and resolves only on terminal event', async () => {
  const c = client(); const events = [];
  const done = c.watchJob('job', ev => events.push(ev));
  c.streams[0].onmessage({ data: JSON.stringify({ type: 'progress', stage: 'actual stage', detail: 'actual detail' }) });
  assert.equal(events[0].stage, 'actual stage');
  c.streams[0].onmessage({ data: JSON.stringify({ type: 'done', result: { search_id: 4 } }) });
  assert.equal((await done).result.search_id, 4);
  assert.equal(c.streams[0].closed, true);
});
test('disconnect keeps polling, avoids replay duplicates and survives another network failure', async () => {
  let count = 0;
  const c = client(async () => {
    count++;
    if (count === 2) throw new Error('offline');
    return response({ status: count < 3 ? 'running' : 'done', events: [{ stage: 'first' }, { stage: 'second' }], result: { search_id: 8 } });
  });
  const events = []; const done = c.watchJob('job', ev => events.push(ev.stage));
  c.streams[0].onmessage({ data: JSON.stringify({ type: 'progress', stage: 'first' }) });
  c.streams[0].onerror(); await flush();
  assert.deepEqual(events, ['first', 'second']);
  assert.equal(c.timers.length, 1);
  await c.timers.shift()();
  assert.equal(c.timers.length, 1);
  await c.timers.shift()();
  assert.equal((await done).result.search_id, 8);
  assert.deepEqual(events, ['first', 'second']);
});
test('server restart gives an actionable missing-job error', async () => {
  const c = client(async () => ({ ok: false, status: 404, json: async () => ({ detail: 'job not found' }) }));
  const done = c.watchJob('lost', () => {});
  c.streams[0].onerror();
  await assert.rejects(done, /任务不存在/);
});
test('job failure and SSE constructor failure are both handled', async () => {
  const c = client(); const done = c.watchJob('failed', () => {});
  c.streams[0].onmessage({ data: JSON.stringify({ type: 'error', error: 'real engine error' }) });
  assert.equal((await done).error, 'real engine error');
  const context = vm.createContext({ fetch: async () => response({ status: 'done', events: [], result: {} }), URLSearchParams, setTimeout });
  vm.runInContext(source.replaceAll('export ', '') + '\nglobalThis.watch = watchJob;', context);
  assert.equal((await context.watch('job', () => {})).type, 'done');
});
