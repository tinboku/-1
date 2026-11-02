// Zero-dependency HTTP client. All progress comes from the engine.
async function req(method, path, body) {
  const res = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* HTTP fallback */ }
    throw new Error(`${res.status}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`);
  }
  return res.status === 204 ? null : res.json();
}
export const api = {
  health: () => req('GET', '/api/health'),
  plan: (question, answers) => req('POST', '/api/plan', { question, answers }),
  listSearches: () => req('GET', '/api/searches'),
  getSearch: id => req('GET', `/api/searches/${id}`),
  launchSearch: payload => req('POST', '/api/searches', payload),
  launchTrace: payload => req('POST', '/api/trace', payload),
  launchReport: (id, focus) => req('POST', `/api/searches/${id}/report`, { focus: focus || null }),
  launchExtract: (id, columns, top) => req('POST', `/api/searches/${id}/extract`, { columns, top: top || 10 }),
  launchUpdates: id => req('POST', `/api/searches/${id}/updates`, {}),
  ask: (id, question) => req('POST', `/api/searches/${id}/ask`, { question }),
  exportUrl: (id, format) => `/api/searches/${id}/export?format=${format}`,
  listFiles: () => req('GET', '/api/files'),
  getFile: id => req('GET', `/api/files/${id}`),
  listPapers: (starred, folder) => req('GET', `/api/papers?${new URLSearchParams({ starred: String(!!starred), ...(folder ? { folder } : {}) })}`),
  lookupPaper: identifier => req('GET', `/api/papers/lookup?${new URLSearchParams({ identifier })}`),
  setStar: (id, starred) => req('POST', `/api/papers/${id}/star`, { starred }),
  setFolder: (id, folder) => req('POST', `/api/papers/${id}/folder`, { folder }),
  importDoi: doi => req('POST', '/api/import/doi', { doi }),
  importBibtex: content => req('POST', '/api/import/bibtex', { content }),
  listJobs: () => req('GET', '/api/jobs'),
  getJob: id => req('GET', `/api/jobs/${id}`),
};

// Replay-safe SSE with repeated snapshot polling when the stream disconnects.
// Network outages retain the monitor; 404 means the server lost its in-memory job.
export function watchJob(jobId, onProgress, onConnection = () => {}) {
  return new Promise((resolve, reject) => {
    let seen = 0, stream, settled = false, polling = false;
    const finish = ev => { settled = true; stream?.close(); resolve(ev); };
    const poll = async () => {
      try {
        const snap = await api.getJob(jobId);
        for (const ev of snap.events.slice(seen)) onProgress({ type: 'progress', ...ev });
        seen = Math.max(seen, snap.events.length);
        if (['done', 'error'].includes(snap.status)) { finish({ type: snap.status, result: snap.result, error: snap.error }); return; }
        onConnection('实时连接中断，正在通过快照持续同步');
      } catch (err) {
        if (err.message.startsWith('404:')) { settled = true; reject(new Error('任务不存在，服务可能已重启；请检查检索历史。')); return; }
        onConnection('网络不可用，正在重试连接');
      }
      setTimeout(poll, 2500);
    };
    try { stream = new EventSource(`/api/jobs/${jobId}/events`); }
    catch { polling = true; poll(); return; }
    stream.onopen = () => onConnection('SSE 已连接 · 接收引擎真实事件');
    stream.onmessage = msg => {
      if (settled || polling) return;
      let ev;
      try { ev = JSON.parse(msg.data); } catch { return; }
      if (ev.type === 'progress') { seen++; onProgress(ev); }
      else if (['done', 'error'].includes(ev.type)) finish(ev);
    };
    stream.onerror = () => {
      if (settled || polling) return;
      polling = true; stream.close(); poll();
    };
  });
}
