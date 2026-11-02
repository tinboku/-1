// Thin client for the dls HTTP API (see dls/api.py).

async function req(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* keep status text */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  health: () => req("GET", "/api/health"),
  plan: (question, answers) => req("POST", "/api/plan", { question, answers }),
  listSearches: () => req("GET", "/api/searches"),
  getSearch: (id) => req("GET", `/api/searches/${id}`),
  launchSearch: (payload) => req("POST", "/api/searches", payload),
  launchTrace: (payload) => req("POST", "/api/trace", payload),
  launchReport: (id, focus) => req("POST", `/api/searches/${id}/report`, { focus: focus || null }),
  launchExtract: (id, columns, top) => req("POST", `/api/searches/${id}/extract`, { columns, top: top || 10 }),
  launchUpdates: (id) => req("POST", `/api/searches/${id}/updates`, {}),
  ask: (id, question) => req("POST", `/api/searches/${id}/ask`, { question }),
  exportUrl: (id, format) => `/api/searches/${id}/export?format=${format}`,
  listFiles: () => req("GET", "/api/files"),
  getFile: (id) => req("GET", `/api/files/${id}`),
  listPapers: (starred) => req("GET", `/api/papers${starred ? "?starred=true" : ""}`),
  setStar: (dbId, starred) => req("POST", `/api/papers/${dbId}/star`, { starred }),
  importDoi: (doi) => req("POST", "/api/import/doi", { doi }),
  getJob: (id) => req("GET", `/api/jobs/${id}`),
};

// Stream a job's progress events; resolves with the final event
// ({type: "done"|"error", result, error}).
export function watchJob(jobId, onProgress) {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/jobs/${jobId}/events`);
    es.onmessage = (msg) => {
      let ev;
      try { ev = JSON.parse(msg.data); } catch { return; }
      if (ev.type === "progress") {
        onProgress(ev);
      } else {
        es.close();
        resolve(ev);
      }
    };
    es.onerror = () => {
      // EventSource fires error on close too; fall back to one snapshot poll.
      es.close();
      api.getJob(jobId).then((snap) => {
        if (snap.status === "done") resolve({ type: "done", result: snap.result });
        else if (snap.status === "error") resolve({ type: "error", error: snap.error });
        else reject(new Error("progress stream disconnected"));
      }).catch(reject);
    };
  });
}
