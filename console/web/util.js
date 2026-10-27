"use strict";
/* Agents Behind the Wall - Demo Console: shared helpers, job store and poller. No dependencies, no CDN. */
window.ABW = window.ABW || {};
(function (A) {
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  // Hyperscript-style builder. Text is always added as text nodes, so server data can never inject markup.
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === "class") e.className = v;
        else if (k === "text") e.textContent = v;
        else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
        else if (k === "dataset") Object.assign(e.dataset, v);
        else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? "" : v);
      }
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return e;
  }

  async function api(path, opts) {
    opts = opts || {};
    const init = { method: opts.method || "GET", cache: "no-store" };
    if (opts.body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(opts.body);
    }
    const r = await fetch(path, init);
    let data = null;
    try { data = await r.json(); } catch (e) { /* not json */ }
    if (!r.ok) {
      const err = new Error((data && data.error) || r.statusText || "Request failed");
      err.status = r.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  let toastTimer = null;
  function toast(msg, bad) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "show" + (bad ? " bad" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.className = ""; }, 2600);
  }

  function copy(text, label) {
    const done = () => toast(label || "Copied");
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, () => toast("Copy failed", true));
    } else {
      const ta = h("textarea", { style: { position: "fixed", opacity: 0 } });
      ta.value = text;
      document.body.append(ta);
      ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { toast("Copy failed", true); }
      ta.remove();
    }
  }

  // ---- tiny markdown -> DOM (paragraphs, "- " bullets, **bold**, `code`)
  function inline(text) {
    return String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/).filter(Boolean).map((p) => {
      if (p.startsWith("**") && p.endsWith("**") && p.length > 4) return h("strong", null, p.slice(2, -2));
      if (p.startsWith("`") && p.endsWith("`") && p.length > 2) return h("code", null, p.slice(1, -1));
      return p;
    });
  }
  function md(text) {
    const frag = document.createDocumentFragment();
    let list = null;
    for (const raw of String(text == null ? "" : text).split(/\r?\n/)) {
      const line = raw.trimEnd();
      const m = line.match(/^\s*(?:[-*\u2022]|\d+[.)])\s+(.*)$/);
      if (m) {
        if (!list) { list = h("ul"); frag.append(list); }
        list.append(h("li", null, inline(m[1])));
      } else {
        list = null;
        if (line.trim()) frag.append(h("p", null, inline(line.replace(/^#+\s*/, ""))));
      }
    }
    return frag;
  }

  function secs(n) {
    n = Number(n) || 0;
    if (n < 60) return n.toFixed(n < 10 ? 1 : 0) + " s";
    return Math.floor(n / 60) + "m " + String(Math.floor(n % 60)).padStart(2, "0") + "s";
  }
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
  const trunc = (s, n) => { s = String(s == null ? "" : s); return s.length > n ? s.slice(0, n - 1) + "\u2026" : s; };
  function asText(v) {
    if (v == null) return "";
    if (typeof v === "string") return v;
    try { return JSON.stringify(v); } catch (e) { return String(v); }
  }

  // ---------------------------------------------------------------- job store: one poller for every tracked job
  const store = { jobs: new Map(), subs: new Map(), byBeat: {} };
  let pollTimer = null;

  function track(id, meta) {
    let j = store.jobs.get(id);
    if (!j) {
      j = Object.assign({ id, kind: "", title: "", beat: "", status: "running", elapsed: 0, events: [], next: 0, result: {}, pending: [], fetchedAt: Date.now(), loaded: false }, meta || {});
      store.jobs.set(id, j);
    }
    kick();
    return j;
  }
  function subscribe(id, fn) {
    if (!store.subs.has(id)) store.subs.set(id, new Set());
    store.subs.get(id).add(fn);
    return () => store.subs.get(id) && store.subs.get(id).delete(fn);
  }
  function notify(j, fresh) {
    for (const fn of Array.from(store.subs.get(j.id) || [])) { try { fn(j, fresh); } catch (e) { console.error(e); } }
    if (A.onJobUpdate) { try { A.onJobUpdate(j, fresh); } catch (e) { console.error(e); } }
  }
  const isLive = (j) => !j.loaded || j.status === "running" || j.status === "waiting";

  async function pollOnce() {
    const live = Array.from(store.jobs.values()).filter(isLive);
    await Promise.all(live.map(async (j) => {
      try {
        const v = await api("/api/jobs/" + j.id + "?since=" + j.next);
        const fresh = v.events || [];
        j.events.push(...fresh);
        Object.assign(j, { kind: v.kind, title: v.title || j.title, beat: v.beat, status: v.status, elapsed: v.elapsed, next: v.next, result: v.result || {}, pending: v.pending || [], fetchedAt: Date.now(), loaded: true });
        notify(j, fresh);
      } catch (e) {
        if (e.status === 404) {
          j.loaded = true; j.status = "failed"; j.missing = true;
          j.result = { summary: "This run is no longer known to the console (it was restarted). Run the step again." };
          notify(j, []);
        }
      }
    }));
  }
  function kick() {
    if (pollTimer) return;
    const loop = async () => {
      try { await pollOnce(); } catch (e) { /* keep polling */ }
      pollTimer = Array.from(store.jobs.values()).some(isLive) ? setTimeout(loop, 600) : null;
    };
    pollTimer = setTimeout(loop, 0);
  }

  async function startJob(run, title, beat) {
    run = A.withPersona ? A.withPersona(run) : run;
    const r = await api("/api/jobs", { method: "POST", body: { kind: run.kind, params: run, title: title || run.kind, beat: beat || "" } });
    const j = track(r.id, { kind: run.kind, title, beat: beat || "", startedHere: true });
    if (beat) store.byBeat[beat] = r.id;
    return j;
  }
  async function loadHistory() {
    try {
      const rows = await api("/api/jobs");
      for (const r of rows) {
        if (r.beat && !store.byBeat[r.beat]) {
          store.byBeat[r.beat] = r.id;
          track(r.id, { kind: r.kind, title: r.title, beat: r.beat });
        }
      }
    } catch (e) { /* first run: nothing to restore */ }
  }

  Object.assign(A, { $, $$, h, api, toast, copy, md, inline, secs, cap, trunc, asText, store, track, subscribe, startJob, loadHistory, isLive });
})(window.ABW);
