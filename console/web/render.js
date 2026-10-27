"use strict";
/* Renders one job's event stream as plain-English cards: verdicts, approvals, answers, tables, the request-id chain, the end-to-end trace board. */
(function (A) {
  const { h, md, secs, trunc, asText, copy, toast, api } = A;

  const WALL_LABEL = ["Foundry guardrail", "AI gateway", "MCP server", "Data plane"];
  const SERVER_LABEL = { legacy: "legacy PoC", research: "research", wall: "wall", actions: "actions", private: "private", vendor: "vendor", agents: "AI gateway" };

  const wallChip = (w) => (w == null ? null : h("span", { class: "chip", style: { borderColor: "var(--w" + w + ")" } }, "Wall " + w + " \u00b7 " + (WALL_LABEL[w] || "")));
  const pre = (text) => h("pre", null, text);
  const details = (label, body, open) => h("details", open ? { open: true } : null, h("summary", null, label), body);

  function ridRow(rid) {
    if (!rid) return null;
    return h("div", { class: "rid" }, "Request id ", h("code", null, rid), h("button", { class: "btn tiny", onclick: () => copy(rid, "Request id copied") }, "Copy"));
  }

  // ---------------------------------------------------------------- verdict card (agent tool call or raw gateway call)
  function verdictCard(ev) {
    const v = ev.verdict || "failed";
    const badge = { allowed: "ALLOWED", denied: "DENIED", leak: "LEAKED", unchecked: "NO CHECK", failed: "FAILED" }[v] || String(v).toUpperCase();
    const raw = ev.status != null;
    const server = SERVER_LABEL[ev.server] || ev.server;
    const args = trunc(asText(ev.args), 170);
    return h("div", { class: "verdict " + v },
      h("div", { class: "v-head" },
        h("span", { class: "v-badge" }, badge),
        h("span", { class: "v-tool mono" }, server + " \u00b7 " + ev.tool),
        raw ? h("span", { class: "v-http" }, "HTTP " + ev.status) : null,
        raw && ev.seconds != null ? h("span", { class: "v-time" }, ev.seconds + " s") : null,
        wallChip(ev.wall)),
      ev.as_user ? h("div", { class: "v-as" }, "Signed in as ", h("b", null, ev.as_user), Array.isArray(ev.roles) ? " \u00b7 roles in this token: " + (ev.roles.length ? ev.roles.join(", ") : "none") : "") : null,
      ev.title ? h("div", { class: "v-title" }, ev.title) : null,
      ev.plain ? h("div", { class: "v-plain" }, ev.plain) : null,
      ev.leak && ev.leak.length ? h("div", { class: "v-leak" }, "Confidential content that came back: ", ev.leak.map((t) => h("mark", null, t))) : null,
      ev.attack ? h("div", { class: "v-attack" }, "\u26a0 The tool result carries an injected instruction: \u201c" + ev.attack + "\u201d") : null,
      args && args !== "{}" ? h("div", { class: "v-args mono" }, "arguments " + args) : null,
      ev.excerpt ? details("What came back", pre(ev.excerpt), ev.open) : null,
      ridRow(ev.request_id));
  }

  function approvalCard(ev, state, job, onChange) {
    const wrap = h("div", { class: "approval" });
    const body = state.answered != null
      ? h("div", { class: "notice info" }, h("h4", null, state.answered ? "You approved this call" : "You rejected this call"), h("p", null, state.answered ? "The agent was allowed to continue." : "The agent was told no and must stop here."))
      : null;
    if (body) return body;
    const decidable = job.status === "waiting" && String(job.pending[0]) === String(ev.id);
    wrap.append(h("h4", null, "The agent is asking permission: " + ev.tool),
      h("p", null, "Nothing happens until a person decides. It will act under your identity."),
      h("pre", { class: "args" }, trunc(asText(ev.args), 400)));
    if (!decidable) {
      wrap.className = "notice info";
      wrap.append(h("p", { class: "eta" }, "Waiting\u2026"));
      return wrap;
    }
    const send = async (ok) => {
      wrap.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      try {
        await api("/api/jobs/" + job.id + "/approve", { method: "POST", body: { id: ev.id, approve: ok } });
      } catch (e) {
        toast(e.message, true);
        wrap.querySelectorAll("button").forEach((b) => { b.disabled = false; });
      }
      onChange();
    };
    wrap.append(h("div", { class: "btns" },
      h("button", { class: "btn good", onclick: () => send(true) }, "Approve"),
      h("button", { class: "btn danger", onclick: () => send(false) }, "Reject")));
    return wrap;
  }

  // ---------------------------------------------------------------- probe fact card (also used by the drawer and the control room)
  function probeCard(p, title) {
    const pill = { ok: "ok", warn: "warn", fail: "fail", na: "na" }[p.status] || "na";
    const label = { ok: "Live", warn: "Check", fail: "Problem", na: "Portal step" }[p.status] || p.status;
    return h("div", { class: "probe" },
      h("div", { class: "p-head" }, h("span", { class: "pill " + pill }, label), h("b", null, title || p.id), h("span", { class: "eta" }, p.asOf ? "read at " + p.asOf + (p.ms ? " \u00b7 " + p.ms + " ms" : "") : "")),
      h("div", { class: "v-plain", style: { marginTop: "6px" } }, p.headline || ""),
      p.facts && p.facts.length ? h("table", { class: "facts" }, p.facts.map((f) => h("tr", null, h("td", null, f.k), h("td", null, f.v)))) : null);
  }

  // ---------------------------------------------------------------- tables, bars, chain, violations
  const DENY = /^(deny|denied|blocked|refused|revoked)/i;
  const ALLOW = /^(allow|allowed|ok)$/i;
  function cell(v) {
    const s = v == null ? "" : String(v);
    const cls = DENY.test(s) ? "deny" : ALLOW.test(s) ? "allow" : s.length > 22 && !/\s/.test(s) ? "mono" : "";
    return h("td", { class: cls }, s);
  }
  function tableCard(ev) {
    const q = ev.query ? h("div", { class: "kql" },
      details("Show the query", h("div", null,
        pre(ev.query),
        h("div", { class: "ops", style: { marginTop: "8px" } },
          h("button", { class: "btn tiny", onclick: () => copy(ev.query, "Query copied") }, "Copy query"),
          h("button", { class: "btn tiny", onclick: () => A.drawer.open("monitor") }, "Open Log Analytics \u2192")))) ) : null;
    const rows = ev.rows || [];
    return h("div", null,
      h("div", { class: "tbl-title" }, h("b", null, ev.title), ev.total != null ? h("span", { class: "eta" }, rows.length < ev.total ? "showing " + rows.length + " of " + ev.total : ev.total + " row" + (ev.total === 1 ? "" : "s")) : null),
      rows.length
        ? h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" }, h("thead", null, h("tr", null, ev.columns.map((c) => h("th", null, c)))), h("tbody", null, rows.map((r) => h("tr", null, r.map(cell))))))
        : h("div", { class: "callout" }, "No rows in this window yet \u2014 logs reach Log Analytics 5\u201310 minutes after a call."),
      q);
  }
  function statsCard(ev) {
    const total = ev.total || ev.rows.reduce((a, r) => a + r.count, 0) || 1;
    return h("div", null,
      h("div", { class: "bars" }, ev.rows.map((r) => h("div", { class: "bar-row" },
        h("b", null, r.code === 200 ? "200 OK" : r.code === 429 ? "429 Slow down" : String(r.code)),
        h("div", { class: "bar-track" }, h("div", { class: "bar-fill " + (r.code === 429 ? "c429" : r.code === 200 ? "" : "other"), style: { width: Math.max(2, (r.count / total) * 100) + "%" } })),
        h("span", null, r.count)))),
      h("div", { class: "eta", style: { marginTop: "6px" } },
        total + " calls in " + (ev.seconds != null ? ev.seconds + " s" : "a few seconds"),
        ev.as_user ? " \u00b7 as " + ev.as_user : "",
        ev.first429 ? " \u00b7 the limit kicked in after call " + ev.first429 : "",
        ev.retryAfter ? " \u00b7 Retry-After " + ev.retryAfter + " s" : ""));
  }
  // The whole path for one run, Entra sign-in to Sentinel, in the order it happened (the AbwFullChain function); each hop wears a verdict read from its own log row.
  const FULL_LAYER = {
    "Entra sign-in": "l-entra", "Entra token issued": "l-entra",
    "APIM front door": "l-gateway", "Tool discovery": "l-gateway", "APIM gateway": "l-gateway", "APIM policy": "l-gateway",
    "Foundry guardrail": "l-agent", "Foundry agent": "l-agent", "Foundry model": "l-agent", "Foundry tool call": "l-agent",
    "MCP server": "l-mcp",
    "Storage data plane": "l-data", "Search data plane": "l-data", "Cosmos data plane": "l-data",
    "Sentinel alert": "l-sent", "Sentinel incident": "l-sent",
  };
  // Seconds after the run's first platform row; negative for the Entra rows that came before it (a sign-in can be days older than the call).
  function offsetText(s) {
    if (s == null) return "";
    const sign = s < 0 ? "-" : "+";
    const a = Math.abs(s);
    if (a < 10) return sign + a.toFixed(1) + " s";
    const t = Math.round(a);
    if (t < 60) return sign + t + " s";
    if (t < 3600) return sign + Math.floor(t / 60) + " min " + (t % 60) + " s";
    const m = Math.round(t / 60);
    if (m < 2880) return sign + Math.floor(m / 60) + " h " + (m % 60) + " min";
    const hr = Math.round(m / 60);
    return sign + Math.floor(hr / 24) + " d " + (hr % 24) + " h";
  }
  const traceRow = (id) => h("div", { class: "rid" }, "Trace id ", h("code", null, id), h("button", { class: "btn tiny", onclick: () => copy(id, "Trace id copied") }, "Copy"));
  function fullChainCard(ev) {
    const q = ev.query ? h("div", { class: "kql" },
      details("Show the query", h("div", null,
        pre(ev.query),
        h("div", { class: "ops", style: { marginTop: "8px" } },
          h("button", { class: "btn tiny", onclick: () => copy(ev.query, "Query copied") }, "Copy query"),
          h("button", { class: "btn tiny", onclick: () => A.drawer.open("monitor") }, "Open Log Analytics \u2192"))))) : null;
    return h("div", null,
      h("div", { class: "tbl-title" }, h("b", null, ev.title), h("span", { class: "eta" }, ev.summary)),
      (ev.rids && ev.rids.length ? ev.rids : [ev.rid]).map((id) => ridRow(id)),
      (ev.traces || []).map((id) => traceRow(id)),
      h("div", { class: "chain", style: { marginTop: "10px" } }, ev.rows.map((r) => h("div", { class: "hop " + (FULL_LAYER[r.layer] || "") },
        h("div", { class: "no" }, String(r.n)),
        h("div", null,
          h("div", { class: "layer" }, [r.layer, r.time ? r.time + " UTC" : "", offsetText(r.offset), r.call ? "call " + r.call : ""].filter(Boolean).join(" \u00b7 "),
            r.badge ? h("span", { class: "vbadge " + (r.tone || "") }, r.badge) : null),
          h("div", { class: "who" }, r.actor || ""),
          h("div", { class: "act" }, r.action || ""),
          r.detail ? h("div", { class: "det mono" }, String(r.detail)) : null)))),
      ev.pending ? h("div", { class: "callout warn" }, ev.pending) : null,
      ev.note ? h("div", { class: "callout" }, ev.note) : null,
      ev.scope ? h("div", { class: "callout" }, ev.scope) : null,
      q);
  }
  function chainCard(ev) {
    if (ev.full) return fullChainCard(ev);
    const LAYER = { "Foundry agent": "l-agent", "APIM gateway": "l-gateway", "MCP server": "l-mcp", "Storage data plane": "l-data" };
    if (!ev.rows.length) return h("div", { class: "notice info" }, h("h4", null, "Not in the logs yet"), h("p", null, ev.note), ridRow(ev.rid));
    return h("div", null,
      ridRow(ev.rid),
      h("div", { class: "chain", style: { marginTop: "10px" } }, ev.rows.map((r, i) => h("div", { class: "hop " + (LAYER[r.layer] || "") },
        h("div", { class: "no" }, String(r.step != null ? r.step : i + 1)),
        h("div", null,
          h("div", { class: "layer" }, r.layer + (r.time ? " \u00b7 " + String(r.time).replace("T", " ").slice(0, 19) : "")),
          h("div", { class: "who" }, r.actor || ""),
          h("div", { class: "act" }, r.action || ""),
          r.detail ? h("div", { class: "det mono" }, String(r.detail)) : null)))),
      ev.note ? h("div", { class: "callout" }, ev.note) : null);
  }
  function violationRow(ev) {
    return h("div", { class: "viol" },
      h("div", null, h("div", { class: "out " + ev.outcome }, ev.outcome), h("div", { class: "eta", style: { textAlign: "center", marginTop: "3px" } }, ev.pass ? "as expected" : "UNEXPECTED")),
      h("div", null, h("div", { class: "t" }, ev.title || ev.id), h("div", { class: "p" }, ev.plain), (ev.note || []).length ? h("div", { class: "n mono" }, ev.note.join(" \u00b7 ")) : null));
  }
  function answerCard(ev) {
    const gate = [];
    if (ev.via === "apim") {
      gate.push("Came in through the APIM front door");
      if (ev.rounds) gate.push(ev.rounds + " model call" + (ev.rounds === 1 ? "" : "s") + " metered");
      if (ev.gateway_tokens != null) gate.push(Number(ev.gateway_tokens).toLocaleString("en-US") + " tokens counted by the gateway");
      if (ev.tokens_remaining != null) gate.push(Number(ev.tokens_remaining).toLocaleString("en-US") + " left in this hour\u2019s budget");
    } else if (ev.via === "direct") gate.push("Called Foundry directly \u2014 no APIM front door on this path");
    return h("div", { class: "answer" },
      h("div", { class: "a-head" }, "What the agent answered", h("span", null, [ev.seconds != null ? ev.seconds + " s" : "", ev.tokens_in != null ? ev.tokens_in + " tokens in / " + ev.tokens_out + " out" : ""].filter(Boolean).join(" \u00b7 "))),
      md(ev.text),
      gate.length ? h("div", { class: "a-via" }, gate.join(" \u00b7 "), ev.gateway_ids && ev.gateway_ids.length ? h("span", { class: "a-ids" }, " \u00b7 request id" + (ev.gateway_ids.length === 1 ? " " : "s "), h("code", null, ev.gateway_ids.slice(0, 3).join(", "), ev.gateway_ids.length > 3 ? " \u2026" : "")) : null) : null);
  }
  const notice = (cls, title, text, extra) => h("div", { class: "notice " + cls }, h("h4", null, title), text ? h("p", null, text) : null, extra);

  // ---------------------------------------------------------------- role matrix (Act 7)
  // One lane per person: a request that should be allowed and one that should be refused (the administrator gets two allowed and one refused),
  // each made with that person's own token. A person who has not signed in yet gets a dashed lane showing what the role model predicts, labelled "not run".
  const MX_BADGE = { allowed: "ALLOWED", denied: "REFUSED", failed: "FAILED" };
  const MX_EVIDENCE = {
    live: ["live", "request just made"],
    rbac: ["live", "Azure role assignment, read live"],
    logs: ["logs", "read from Log Analytics"],
    design: ["design", "predicted by the role model \u2014 not run"],
  };

  function matrixCell(c) {
    const design = c.evidence === "design";
    const verdict = c.verdict || "failed";
    const ev = MX_EVIDENCE[c.evidence] || ["design", String(c.evidence || "")];
    const match = design || c.as_expected == null ? null
      : c.as_expected ? h("span", { class: "mx-match ok" }, "\u2713 as the role model predicts")
        : h("span", { class: "mx-match bad" }, "\u2717 NOT as the role model predicts");
    const rows = [];
    if (c.tool) rows.push(["Tool", c.tool]);
    if (c.args && c.args !== "{}") rows.push(["Arguments", c.args]);
    if (c.status != null) rows.push(["HTTP status", String(c.status)]);
    if (c.seconds != null) rows.push(["Took", c.seconds + " s"]);
    if (c.evidence === "live" && Array.isArray(c.roles)) rows.push(["Roles in this token", c.roles.length ? c.roles.join(", ") : "none"]);
    if (c.reason) rows.push(["Reason code", c.reason]);
    const proof = rows.length || c.excerpt || c.request_id;
    return h("div", { class: "mx-cell " + (c.kind === "allow" ? "allow" : "refuse") + " v-" + verdict + (design ? " is-design" : "") + (c.as_expected === false ? " is-bad" : "") },
      h("div", { class: "mx-top" },
        h("span", { class: "mx-badge" }, (design ? "EXPECTED " : "") + (MX_BADGE[verdict] || String(verdict).toUpperCase())),
        h("span", { class: "mx-label" }, c.label),
        wallChip(verdict === "denied" ? c.wall : null)),
      h("div", { class: "mx-sub" }, h("span", { class: "tr-ev " + ev[0] }, ev[1]), match),
      c.title ? h("div", { class: "mx-title" }, c.title) : null,
      c.plain ? h("div", { class: "mx-plain" }, c.plain) : null,
      c.expect ? h("div", { class: "mx-why" }, h("b", null, "Role model: "), c.expect) : null,
      proof ? details("Proof and detail", h("div", null,
        rows.length ? h("table", { class: "facts" }, rows.map((r) => h("tr", null, h("td", null, r[0]), h("td", null, r[1])))) : null,
        c.excerpt ? h("div", null, h("div", { class: "eta", style: { margin: "6px 0 2px" } }, "What came back"), pre(c.excerpt)) : null,
        ridRow(c.request_id))) : null);
  }

  function matrixLane(lane) {
    const pill = lane.state === "signin" ? h("span", { class: "pill warn" }, "Not signed in")
      : lane.state === "error" ? h("span", { class: "pill fail" }, "A check failed")
        : h("span", { class: "pill ok" }, "Ran live");
    return h("div", { class: "mx-lane st-" + lane.state },
      h("div", { class: "mx-head" }, h("div", null, h("div", { class: "mx-name" }, lane.name), h("div", { class: "mx-job" }, lane.job)), pill),
      h("div", { class: "mx-roles" }, lane.roles && lane.roles.length ? lane.roles.map((r) => h("span", { class: "chip role" }, r)) : h("span", { class: "chip norole" }, "no data role on any MCP server")),
      lane.story ? h("div", { class: "mx-story" }, lane.story) : null,
      lane.note ? h("div", { class: "callout warn mx-note" }, lane.note) : null,
      h("div", { class: "mx-cells" }, (lane.cells || []).map(matrixCell)));
  }

  function matrixCard(ev) {
    const lanes = ev.lanes || [];
    const live = lanes.flatMap((l) => l.cells || []).filter((c) => c.evidence !== "design");
    const bad = live.filter((c) => c.as_expected === false);
    const waiting = lanes.filter((l) => l.state === "signin").map((l) => l.name);
    const tone = bad.length ? "stop" : waiting.length || !live.length ? "warn" : "ok";
    const headline = !live.length ? "No live checks ran \u2014 every lane below is the role model\u2019s prediction"
      : bad.length ? bad.length + " of " + live.length + " live checks did NOT behave as the role model predicts"
        : live.length + " of " + live.length + " live checks behaved as the role model predicts";
    const sub = !lanes.length ? "The role matrix returned no lanes."
      : waiting.length
        ? waiting.join(", ") + (waiting.length === 1 ? " has" : " have") + " not signed in: that lane shows the predicted outcome, dashed and labelled \u201cnot run\u201d. Open Acting as (press P), sign in once, then run this step again."
        : "Every lane ran with that person\u2019s own token.";
    return h("div", { class: "mx" },
      h("div", { class: "tr-banner " + tone }, h("div", { class: "tr-hl" }, headline), h("div", { class: "tr-out" }, sub)),
      h("div", { class: "mx-grid" }, lanes.map(matrixLane)),
      (ev.notes || []).length ? h("div", { class: "mx-notes" }, ev.notes.map((n) => h("div", { class: "callout" }, n))) : null);
  }

  // ---------------------------------------------------------------- cost and token board (Act 7)
  function finopsCard(ev) {
    return h("div", { class: "fin" },
      h("div", { class: "kpis" }, (ev.tiles || []).map((t) => h("div", { class: "kpi" + (t.tone ? " " + t.tone : "") },
        h("div", { class: "kpi-l" }, t.label), h("div", { class: "kpi-v" }, t.value), t.sub ? h("div", { class: "kpi-s" }, t.sub) : null))),
      (ev.notes || []).length ? h("div", { class: "fin-notes" }, ev.notes.map((n) => h("div", { class: "callout" }, n))) : null);
  }

  // ---------------------------------------------------------------- end-to-end trace board (Act 6)
  // One request, twelve layers: seven on the request path and five watchtowers beside it. The board arrives as one "trace" event and is
  // repainted in place when a refresh job reads the logs back, so the presenter keeps a single card and watches it fill in.
  const TR_GLYPH = { pass: "\u2713", block: "\u2717", skip: "\u2013", na: "\u00b7", info: "\u2139", due: "\u23f1", quiet: "\u25cb", seen: "\u25c9", portal: "\u2197" };
  const TR_STATE = { pass: "Passed", block: "Stopped here", skip: "Never reached", na: "Not used", info: "Note", due: "Waiting", quiet: "Quiet", seen: "Seen", portal: "Portal step" };
  const TR_EVIDENCE = {
    live: ["live", "seen live"],
    probe: ["live", "read live from Azure"],
    "live+probe": ["live", "seen live + read from Azure"],
    logs: ["logs", "from the logs"],
    "live+logs": ["logs", "seen live, confirmed in logs"],
    graph: ["logs", "from Entra\u2019s sign-in log"],
    "live+graph": ["logs", "seen live + Entra\u2019s sign-in log"],
    arm: ["live", "read from Azure (ARM)"],
    replay: ["replay", "replay of an earlier run"],
    portal: ["portal", "portal step \u2014 not read here"],
  };
  const TR_DUE = { "": "expected \u2014 not seen yet", logs: "waiting for the logs", graph: "waiting for Entra\u2019s log", arm: "waiting for an alert", probe: "plan read live; alert not seen yet" };
  const TR_LAG = "Logs reach Log Analytics 2\u201318 minutes after a call, Sentinel alerts 5\u201315 minutes, Entra\u2019s own sign-in log 10\u201320 minutes. A row changes only when the service really shows this request.";
  const TRACES = new Map();
  const AGES = new Set();

  const pad2 = (n) => String(n).padStart(2, "0");
  const clock = (d, withSeconds) => pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + (withSeconds ? ":" + pad2(d.getSeconds()) : "");
  const nodeLabel = (id) => { const n = A.catalog && A.catalog.nodes ? A.catalog.nodes[id] : null; return n ? n.short || n.title : id; };
  function ageText(at) {
    const t = Date.parse(at);
    if (!isFinite(t)) return "";
    const m = Math.floor((Date.now() - t) / 60000);
    return m < 1 ? "just now" : m < 120 ? m + " min ago" : Math.floor(m / 60) + " h ago";
  }
  setInterval(() => { for (const e of Array.from(AGES)) { if (!e.isConnected) AGES.delete(e); else e.textContent = ageText(e.dataset.at); } }, 15000);

  // "Azure portal -> ... [seen]" -> the path and the tag saying whether this path has been seen in the demo tenant.
  function splitClick(text) {
    const m = /^([\s\S]*?)\s*\[([^\]]+)\]\s*$/.exec(String(text || ""));
    return m ? { path: m[1], tag: m[2] } : { path: String(text || ""), tag: "" };
  }
  const tagLabel = (tag) => (tag === "seen" ? "seen in this tenant" : tag);
  const tagClass = (tag) => (/not seen|from docs/i.test(tag) ? "warn" : /\bseen\b/i.test(tag) ? "ok" : "info");

  function evidenceChip(row) {
    const ev = row.evidence || "";
    if (row.state === "due") return h("span", { class: "tr-ev wait" }, TR_DUE[ev] || TR_DUE.logs);
    if ((row.state === "skip" || row.state === "na") && (ev === "live" || ev === "")) return null;
    const got = TR_EVIDENCE[ev];
    return got ? h("span", { class: "tr-ev " + got[0] }, got[1]) : null;
  }

  function traceCard(ev, job) {
    const beat = String((job && job.beat) || "").replace(/L$/, "");
    const refreshBeat = (beat || "e2e") + "L";
    const open = new Set();
    const ctl = { tid: ev.tid, refreshJob: "" };
    let cur = ev;
    let seen = new Map();

    const el = h("div", { class: "trace" });
    const dyn = h("div", { class: "tr-dyn" });
    const checked = h("span", { class: "eta" });
    const refreshHost = h("div", { class: "tr-refresh-host" });
    const refreshBtn = h("button", { class: "btn tiny", onclick: () => startRefresh() }, "Refresh from logs");

    const jump = (layer) => {
      const row = document.getElementById("tr-" + cur.tid + "-" + layer);
      if (!row) return;
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add("hit");
      setTimeout(() => row.classList.remove("hit"), 1500);
    };

    function rowView(r, idx, last, moved) {
      const key = (what) => r.layer + ":" + what;
      const toggle = (what, label, panel, extra) => {
        const on = open.has(key(what));
        panel.classList.toggle("off", !on);
        const car = h("span", { class: "car" }, on ? "\u25b4" : "\u25be");
        const btn = h("button", { class: "tr-tog", "aria-expanded": on ? "true" : "false" }, label, " ", car);
        btn.addEventListener("click", () => {
          const now = !open.has(key(what));
          if (now) open.add(key(what)); else open.delete(key(what));
          panel.classList.toggle("off", !now);
          btn.setAttribute("aria-expanded", now ? "true" : "false");
          car.textContent = now ? "\u25b4" : "\u25be";
        });
        return h("span", { class: "tr-togwrap" }, btn, extra);
      };
      const { path, tag } = splitClick(r.click);
      const showClick = r.state !== "na" && !!path;
      const showQuery = r.state !== "na" && !!r.query;
      const clickPanel = h("div", { class: "tr-more" }, h("div", { class: "tr-path" }, path));
      const queryPanel = h("div", { class: "tr-more" },
        h("div", { class: "kql" }, pre(r.query || "")),
        h("div", { class: "tr-qbtns" },
          h("button", { class: "btn tiny", onclick: () => copy(r.query, "Query copied") }, "Copy query"),
          h("button", { class: "btn tiny ghost", onclick: () => { A.strip.pulse(["monitor"]); A.drawer.open("monitor"); } }, "Open Log Analytics \u2192")));
      const hasNode = !!(A.catalog && A.catalog.nodes && A.catalog.nodes[r.node]);
      const acts = [
        hasNode ? h("button", { class: "btn tiny ghost", title: "Open the side panel for this service", onclick: () => { A.strip.pulse([r.node]); A.drawer.open(r.node); } }, "Open " + nodeLabel(r.node) + " \u2197") : null,
        showClick ? toggle("click", "Where to click", clickPanel, tag ? h("span", { class: "tr-tag " + tagClass(tag) }, tagLabel(tag)) : null) : null,
        showQuery ? toggle("query", "Query", queryPanel, null) : null,
      ].filter(Boolean);
      return h("div", { class: "tr-row s-" + r.state + " g-" + r.group + (last ? " last" : "") + (moved ? " changed" : ""), id: "tr-" + cur.tid + "-" + r.layer },
        h("div", { class: "tr-no" }, r.group === "path" ? String(idx + 1) : TR_GLYPH[r.state] || "\u00b7"),
        h("div", { class: "tr-main" },
          h("div", { class: "tr-head" },
            h("b", { class: "tr-title" }, r.title),
            h("span", { class: "tr-pill s-" + r.state }, (TR_GLYPH[r.state] || "") + " " + (r.label || TR_STATE[r.state] || r.state)),
            evidenceChip(r)),
          h("div", { class: "tr-sub" }, r.sub),
          h("div", { class: "tr-text" }, r.text),
          acts.length ? h("div", { class: "tr-acts" }, acts) : null,
          showClick ? clickPanel : null,
          showQuery ? queryPanel : null));
    }

    function paint(data, flash) {
      cur = data;
      const before = seen;
      seen = new Map(data.rows.map((r) => [r.layer, [r.state, r.label, r.text, r.evidence, r.query].join("\u241f")]));
      const path = data.rows.filter((r) => r.group === "path");
      const watch = data.rows.filter((r) => r.group === "watch");
      let changed = 0;
      const view = (r, i, list) => {
        const moved = !!flash && before.get(r.layer) !== seen.get(r.layer);
        if (moved) changed += 1;
        return rowView(r, i, i === list.length - 1, moved);
      };
      const when = new Date(data.at);
      const age = h("span", { dataset: { at: data.at } }, ageText(data.at));
      AGES.add(age);
      const kind = /did not fire|not refused|no tool called/i.test(data.headline || "") ? "warn" : data.stopped_at ? "stop" : data.polarity === "positive" ? "ok" : "warn";
      const ids = [
        data.rid ? ridRow(data.rid) : null,
        data.nonce ? h("div", { class: "rid" }, "Marker ", h("code", null, "?e2e=" + data.nonce), h("button", { class: "btn tiny", onclick: () => copy("?e2e=" + data.nonce, "Marker copied") }, "Copy"),
          h("span", null, "added to this click\u2019s URL so its row can be found in the gateway log")) : null,
      ];
      dyn.replaceChildren(...[
        h("div", { class: "tr-top" },
          h("span", { class: "pill " + (data.polarity === "positive" ? "ok" : "warn") }, data.polarity === "positive" ? "Positive test" : "Negative test"),
          h("b", { class: "tr-scn" }, data.title),
          data.actor ? h("span", { class: "tr-as" }, "as ", h("b", null, data.actor)) : null,
          isFinite(when) ? h("span", { class: "tr-when" }, "clicked " + clock(when, true) + " \u00b7 ", age) : null),
        h("div", { class: "tr-banner " + kind },
          h("div", { class: "tr-hl" }, { stop: "\u2717", ok: "\u2713", warn: "\u26a0" }[kind] + " " + data.headline),
          data.outcome ? h("div", { class: "tr-out" }, data.outcome) : null),
        h("div", { class: "tr-flow" }, path.map((r) => h("button", { class: "tr-seg s-" + r.state, title: r.title + ": " + (r.label || TR_STATE[r.state] || r.state), onclick: () => jump(r.layer) },
          h("span", { class: "tr-seg-t" }, (TR_GLYPH[r.state] || "") + " " + r.title),
          h("span", { class: "tr-seg-l" }, r.label || TR_STATE[r.state] || r.state)))),
        ids,
        h("div", { class: "tr-group" }, "The path", h("span", null, data.stopped_at ? "the request stops at the first layer that says no" : "the request goes through every layer that applies, in order")),
        path.map(view),
        h("div", { class: "tr-group" }, "The watchtowers", h("span", null, "they watch the path; they are not on it")),
        watch.map(view),
        data.note ? h("div", { class: "callout" }, data.note) : null,
      ].flat(Infinity).filter(Boolean));
      if (flash) checked.textContent = "Last refreshed " + clock(new Date()) + " \u00b7 " + (changed ? changed + " row" + (changed === 1 ? "" : "s") + " updated" : "nothing new yet");
      return changed;
    }

    async function startRefresh() {
      refreshBtn.disabled = true;
      try {
        const rj = await A.startJob({ kind: "e2e_logs", trace: cur.tid }, "Refresh from logs \u00b7 " + cur.title, refreshBeat);
        rj.traceId = cur.tid;
        ctl.mountRefresh(rj);
      } catch (e) {
        refreshBtn.disabled = false;
        refreshHost.replaceChildren(notice("fail", "Can\u2019t refresh right now", e.message));
      }
    }

    ctl.el = el;
    ctl.paint = paint;
    ctl.mountRefresh = (rj) => {
      if (ctl.refreshJob === rj.id) return;
      ctl.refreshJob = rj.id;
      A.mount(refreshHost, rj.id);
      const sync = (j) => { refreshBtn.disabled = A.isLive(j); };
      sync(rj);
      const off = A.subscribe(rj.id, (j) => { if (!el.isConnected) { off(); return; } sync(j); });
    };

    // After a reload or a trip to another page the card is rebuilt from the job's events; pick up the refresh run that belongs to it.
    const adopt = (tries) => {
      if (!el.isConnected) { if (tries < 30) setTimeout(() => adopt(tries + 1), 100); return; }
      const rj = A.store.jobs.get(A.store.byBeat[refreshBeat]);
      if (!rj) return;
      const mine = (j) => j.traceId === ev.tid || !!(j.result && j.result.tid === ev.tid);
      if (mine(rj)) { ctl.mountRefresh(rj); return; }
      if (rj.loaded) return;
      const off = A.subscribe(rj.id, (j) => {
        if (!el.isConnected) { off(); return; }
        if (!j.loaded) return;
        off();
        if (mine(j)) ctl.mountRefresh(j);
      });
    };

    paint(ev, false);
    el.append(dyn, h("div", { class: "tr-refresh" }, refreshBtn, h("span", { class: "eta" }, TR_LAG), checked), refreshHost);
    TRACES.set(ev.tid, ctl);
    if (ev.mode !== "logs") setTimeout(() => adopt(0), 0);
    return el;
  }

  // ---------------------------------------------------------------- the renderer
  class JobRenderer {
    constructor(host) {
      this.host = host;
      this.job = null;
      this.lastRun = null;
      this.rawBox = null;
      this.rawPre = null;
      this.answered = new Map();
      this.approvals = new Map();
      this.timeEl = h("span", { class: "time" });
      this.stateEl = h("span", { class: "state" });
      this.sumEl = h("span", { class: "sum" });
      this.stopBtn = h("button", { class: "btn tiny danger", onclick: () => this.stop() }, "Stop");
      this.bar = h("div", { class: "job-bar running" }, this.stateEl, this.timeEl, this.sumEl, this.stopBtn);
      this.body = h("div", { class: "job-body" });
      host.replaceChildren(h("div", { class: "job" }, this.bar, this.body));
    }
    async stop() {
      if (!this.job) return;
      this.stopBtn.disabled = true;
      try { await api("/api/jobs/" + this.job.id + "/cancel", { method: "POST", body: {} }); } catch (e) { toast(e.message, true); }
    }
    update(job, events, live) {
      this.job = job;
      for (const ev of events) this.add(ev, live);
      this.paintApprovals();
      this.paintBar();
    }
    paintBar() {
      const j = this.job;
      if (!j) return;
      const s = j.status;
      this.bar.className = "job-bar " + s;
      this.stateEl.replaceChildren(...(s === "running" ? [h("span", { class: "spin" }), " Running"] : [{ waiting: "\u23f8 Waiting for your decision", done: "\u2713 Done", failed: "\u26a0 Needs attention", cancelled: "\u25a0 Stopped" }[s] || s]));
      this.sumEl.textContent = j.result && j.result.summary ? j.result.summary : "";
      this.stopBtn.style.display = s === "running" || s === "waiting" ? "" : "none";
      this.tick();
    }
    tick() {
      const j = this.job;
      if (!j) return false;
      const live = j.status === "running" || j.status === "waiting";
      this.timeEl.textContent = secs(j.elapsed + (live ? (Date.now() - j.fetchedAt) / 1000 : 0));
      return live;
    }
    push(node) {
      if (this.rawBox) this.body.insertBefore(node, this.rawBox);
      else this.body.append(node);
      return node;
    }
    settleRun() {
      if (!this.lastRun) return;
      this.lastRun.querySelector(".ic").replaceChildren("\u2022");
      this.lastRun = null;
    }
    paintApprovals() {
      for (const [id, rec] of this.approvals) {
        const wanted = this.answered.has(id) ? "a" : this.job.status === "waiting" && String(this.job.pending[0]) === id ? "w" : "x";
        if (rec.mode === wanted) continue;
        rec.mode = wanted;
        const node = approvalCard(rec.ev, { answered: this.answered.has(id) ? this.answered.get(id) : null }, this.job, () => {});
        rec.node.replaceWith(node);
        rec.node = node;
      }
    }
    add(ev, live) {
      if (this.lastRun && !(ev.type === "step" && ev.state === "run")) this.settleRun();
      if (live && ev.lights && A.strip) A.strip.apply(ev.lights);
      switch (ev.type) {
        case "say": this.push(h("div", { class: "ev-say" }, ev.text)); break;
        case "step": {
          const ic = ev.state === "run" ? h("span", { class: "spin" }) : { ok: "\u2713", fail: "\u2717", info: "\u2139" }[ev.state] || "\u2022";
          const node = h("div", { class: "ev-step " + ev.state }, h("span", { class: "ic" }, ic), h("span", null, ev.text, ev.detail ? h("div", { class: "detail" }, ev.detail) : null));
          this.push(node);
          if (ev.state === "run") this.lastRun = node;
          break;
        }
        case "who": {
          const route = !ev.legacy && ev.via === "apim" ? [" \u2192 ", h("span", { class: "pill" }, "APIM front door"), " \u2192 agent "] : " \u2192 agent ";
          this.push(h("div", { class: "ev-who" }, ev.legacy ? h("span", { class: "pill warn" }, "Shared key, no user") : h("span", { class: "pill ok" }, "Signed in"), ev.who, route, h("code", null, ev.agent),
            ev.prompt ? h("div", { style: { flexBasis: "100%", color: "var(--text)" } }, "\u201c" + ev.prompt + "\u201d") : null,
            ev.note ? h("div", { class: "eta", style: { flexBasis: "100%" } }, ev.note) : null));
          break;
        }
        case "tools":
          this.push(h("div", { class: "tools" }, h("div", { class: "eta" }, "Tools the gateway offered this user (filtered by the roles in the token):"),
            Object.entries(ev.servers || {}).map(([srv, names]) => h("div", { class: "srv" }, h("b", null, SERVER_LABEL[srv] || srv), names.length ? names.map((n) => h("span", { class: "chip" }, n)) : h("span", { class: "eta" }, "none \u2014 no role for this server")))));
          break;
        case "call": case "http": this.push(verdictCard(ev)); break;
        case "approval":
          if (ev.auto) { this.push(h("div", { class: "ev-step info" }, h("span", { class: "ic" }, "\u2139"), h("span", null, "Approval gate: the agent asked to call ", h("code", null, ev.tool), " \u2014 pre-approved for this run."))); break; }
          {
            const node = this.push(h("div"));
            this.approvals.set(String(ev.id), { ev, node, mode: "" });
          }
          break;
        case "approval_answer": this.answered.set(String(ev.id), !!ev.granted); break;
        case "failure":
          this.push(notice("fail", ev.title || "The call failed", ev.plain || ev.message, h("div", null,
            wallChip(ev.wall),
            ev.link ? h("p", null, h("a", { class: "btn primary", href: ev.link, target: "_blank", rel: "noopener" }, "Open the one-time consent page")) : null,
            ridRow(ev.request_id),
            ev.message && ev.plain ? details("Technical detail", pre(ev.message)) : null)));
          break;
        case "stop":
          this.push(notice("guard", ev.title, ev.plain, h("div", null, wallChip(ev.wall), ev.detail ? h("p", { class: "eta" }, ev.detail) : null)));
          break;
        case "answer": this.push(answerCard(ev)); break;
        case "stats": this.push(statsCard(ev)); break;
        case "violation": this.push(violationRow(ev)); break;
        case "table": this.push(tableCard(ev)); break;
        case "chain": this.push(chainCard(ev)); break;
        case "matrix": this.push(matrixCard(ev)); break;
        case "finops": this.push(finopsCard(ev)); break;
        case "trace": {
          // A refresh run re-sends the board it read back; repaint the card on screen instead of stacking a second one.
          const shown = ev.mode === "logs" ? TRACES.get(ev.tid) : null;
          if (shown && shown.el.isConnected) {
            const n = shown.paint(ev, !!live);
            if (live) this.push(h("div", { class: "ev-say" }, "Board updated from the logs at " + clock(new Date()) + (n ? " \u2014 " + n + " row" + (n === 1 ? "" : "s") + " changed." : " \u2014 nothing new yet.")));
          } else this.push(traceCard(ev, this.job));
          break;
        }
        case "probe": this.push(probeCard(ev.probe, A.probeTitle ? A.probeTitle(ev.probe.id) : ev.probe.id)); break;
        case "raw":
          if (!this.rawBox) {
            this.rawPre = pre("");
            this.rawBox = h("details", { class: "raw" }, h("summary", null, "Technical output"), this.rawPre);
            this.body.append(this.rawBox);
          }
          this.rawPre.textContent += ev.text + "\n";
          break;
        case "error": this.push(notice("err", "Something went wrong", ev.text)); break;
        default: break;
      }
    }
  }

  // Ticks every running renderer's clock; drops renderers whose card has been replaced.
  const ticking = new Set();
  setInterval(() => { for (const r of Array.from(ticking)) { if (!r.host.isConnected) ticking.delete(r); else r.tick(); } }, 500);

  // Attach a renderer to a host for a job id. Events already in the store are replayed quietly (no strip lights);
  // events that arrive afterwards drive the architecture strip - also for jobs started in this page session that
  // finished between two polls (j.startedHere), but not for old jobs restored after a reload.
  function mount(host, jobId) {
    const r = new JobRenderer(host);
    const j = A.track(jobId);
    ticking.add(r);
    r.update(j, j.loaded ? j.events : [], false);
    const off = A.subscribe(jobId, (job, fresh) => {
      if (!host.isConnected) { off(); return; }
      r.update(job, fresh, !!job.startedHere || job.status === "running" || job.status === "waiting");
    });
    return r;
  }

  Object.assign(A, { JobRenderer, mount, probeCard, verdictCard, wallChip, ridRow, details, pre, traceCard, matrixCard, finopsCard });
})(window.ABW);
