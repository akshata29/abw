"use strict";
/* Pages: Start, the seven acts (beat cards), Control Room, Scoreboard. */
(function (A) {
  const { h, api, md, secs, toast } = A;

  const nodeName = (id) => { const n = A.catalog.nodes[id]; return n ? n.short || n.title : id; };
  const callout = (label, text, cls) => h("div", { class: "callout " + (cls || "") }, h("b", null, label + " "), text);
  const beatScene = (beatId) => { const base = String(beatId || "").replace(/L$/, ""); return A.catalog.scenes.find((s) => s.beats.some((b) => b.id === base)); }; // "6.1L" is the refresh job of step 6.1
  const isLive = (j) => j && (j.status === "running" || j.status === "waiting");

  const nodeChip = (id) => h("button", { class: "chip node-chip", onclick: () => { A.strip.pulse([id]); A.drawer.open(id); } }, nodeName(id), h("span", { class: "go" }, "\u2197"));
  const beatChip = (id) => h("button", { class: "chip", onclick: () => A.nav(beatScene(id).id, id) }, "Beat " + id, h("span", { class: "go" }, "\u203a"));

  // ------------------------------------------------------------------------------------------ operations (preflight / reset)
  function opsBlock() {
    const result = h("div", { class: "result" });
    const mk = (id, label, run, title, cls) => {
      const b = h("button", { class: "btn " + (cls || ""), id: "ops-" + id, title }, label);
      b.addEventListener("click", async () => {
        A.strip.clear();
        try {
          const j = await A.startJob(run, label, "ops");
          b.disabled = true;
          A.mount(result, j.id);
          A.subscribe(j.id, (job) => { if (!isLive(job)) { b.disabled = false; A.refreshStatus(); } });
        } catch (e) {
          result.replaceChildren(h("div", { class: "notice fail" }, h("h4", null, "Can't start that right now"), h("p", null, e.message)));
        }
      });
      return b;
    };
    const prior = A.store.byBeat.ops && A.store.jobs.get(A.store.byBeat.ops);
    if (prior) A.mount(result, prior.id);
    return h("div", null,
      h("div", { class: "ops" },
        mk("preflight", "Run preflight", { kind: "preflight" }, "Sign-in, roles, gateway, kill switch and allow-list - about 15 seconds", "primary"),
        mk("restore", "Reset demo to baseline", { kind: "restore" }, "Kill switch off, client allow-list restored. About 1\u20131.5 minutes.", ""),
        h("span", { class: "eta" }, "Preflight ~15 s \u00b7 Reset ~1.5 min")),
      result);
  }

  // ------------------------------------------------------------------------------------------------------------------ Start
  function startPage() {
    const cat = A.catalog;
    const scene = cat.scenes.find((s) => s.id === "start");
    return h("div", null,
      h("div", { class: "hero" },
        h("div", { class: "eyebrow" }, "Live demo console \u00b7 real Azure tenant"),
        h("h1", null, scene.title),
        h("p", { class: "lead" }, scene.story)),
      h("div", { class: "section-title" }, "The six asks \u2014 and where each one is answered"),
      h("div", { class: "asks" }, cat.asks.map((a) => h("div", { class: "ask" },
        h("div", { class: "n" }, String(a.n)),
        h("div", { class: "q" }, a.ask),
        h("div", { class: "a" }, a.answer),
        h("div", { class: "chips" }, a.beats.map(beatChip)),
        h("div", { class: "chips" }, h("span", { class: "eta" }, "open the real service:"), a.nodes.map(nodeChip))))),
      h("div", { class: "section-title" }, "Before you go on stage"),
      opsBlock(),
      callout("Tip", "Press N to show or hide the presenter notes, P to pick who the gateway steps run as, 1\u20137 to jump to an act, Esc to close the side panel. Every box in the strip above opens the real service.", ""),
      h("div", { class: "section-title" }, "Run of show (30 minutes)"),
      h("div", { class: "plan" }, [
        ["0:00", "Hook \u2014 the six questions (slides)"], ["0:03", "The idea \u2014 v0 vs v1, identity chain, four walls (slides)"],
        ["0:07", "Act 1 \u2014 same question, two answers (this console)"], ["0:11", "Act 2 \u2014 no keys"], ["0:13", "Act 3 \u2014 whose hands are on the data"],
        ["0:15", "Act 4 \u2014 when it goes wrong"], ["0:19", "Act 5 \u2014 what InfoSec sees, then the scoreboard"],
        ["0:22", "Take it to your customer \u00b7 honest edges \u00b7 Q&A (slides)"],
      ].map(([t, x]) => [h("div", { class: "tm" }, t), h("div", null, x)])),
      callout("Act 6", "One request through all twelve layers, as a failure or as a success: press 6. Use it as the follow-one-request story on its own, or as the proof you open when someone asks \u201cshow me where that was stopped\u201d.", ""),
      callout("Act 7", "The back-pocket act, press 7: one tab for every kind of user (an allowed and a refused request each, plus the administrator running every agent and MCP server), the APIM front door in front of the agent, what it all costs and who spends the tokens, and a runaway agent hitting its budget. Open it when someone asks \u201cwhat about a trader, compliance or InfoSec?\u201d, \u201cshouldn\u2019t the user call APIM, not the agent?\u201d or \u201cwhat does this cost?\u201d.", ""));
  }

  // ------------------------------------------------------------------------------------------------------------------ beat card
  // A tagged scenario (ALLOWED, REFUSED, ATTACK...) shows its expected outcome where the step number would be.
  const beatHead = (beat) => (beat.tag
    ? [h("span", { class: "beat-num tag-" + (beat.tone || "pos") }, beat.tag), h("h3", null, beat.title), h("span", { class: "beat-id mono" }, beat.id)]
    : [h("span", { class: "beat-num" }, beat.id), h("h3", null, beat.title)]);

  function beatCard(beat) {
    const result = h("div", { class: "result" });
    const buttons = [];
    const setBusy = (b) => buttons.forEach((x) => { x.disabled = b; });
    const attach = (jobId) => {
      A.mount(result, jobId);
      const j = A.store.jobs.get(jobId);
      setBusy(isLive(j) || !j.loaded);
      A.subscribe(jobId, (job) => { setBusy(isLive(job)); if (!isLive(job)) A.refreshStatus(); });
    };
    const run = async (spec, label) => {
      A.strip.clear();
      try {
        const j = await A.startJob(spec, label, beat.id);
        attach(j.id);
        A.paintRail();
      } catch (e) {
        result.replaceChildren(h("div", { class: "notice fail" }, h("h4", null, "Can't start that right now"), h("p", null, e.message)));
      }
    };
    const primary = h("button", { class: "btn primary", onclick: () => run(beat.run, beat.title) }, beat.button);
    buttons.push(primary);
    const alts = (beat.alt || []).map((a) => {
      const b = h("button", { class: "btn alt", onclick: () => run(a.run, a.label) }, a.label);
      buttons.push(b);
      return h("span", { class: "chips" }, b, A.persona.chip(a.run), h("span", { class: "eta" }, a.eta));
    });
    const notes = h("div", { class: "notes" },
      h("div", { class: "note" }, h("h5", null, "What you should see"), h("p", null, beat.expect)),
      h("div", { class: "note tech" }, h("h5", null, "Under the hood"), h("p", null, beat.tech)),
      h("div", { class: "note sales" }, h("h5", null, "Why it matters"), h("p", null, beat.sales)),
      (beat.faq || []).length ? h("div", { class: "note faq" }, h("h5", null, "If someone asks\u2026"), beat.faq.map((f) => h("div", { class: "qa" }, h("div", { class: "qq" }, f.q), h("p", null, f.a)))) : null);
    const card = h("section", { class: "beat", id: "beat-" + beat.id },
      h("div", { class: "beat-head" }, beatHead(beat)),
      h("p", { class: "beat-say" }, beat.say),
      h("div", { class: "beat-actions" }, primary, A.persona.chip(beat.run), h("span", { class: "eta" }, beat.eta), alts),
      h("div", { class: "prove", style: { marginTop: "12px" } }, h("span", { class: "lbl" }, "Prove it\u2019s real"), (beat.prove || []).map(nodeChip)),
      result, notes);
    const prior = A.store.byBeat[beat.id];
    if (prior) attach(prior);
    return card;
  }

  function tourCard(tour) {
    const pills = new Map();
    const cards = tour.items.filter((it) => A.catalog.nodes[it.node]).map((it) => {
      const pill = h("span", { class: "pill na" }, "\u2026");
      pills.set(it.node, pill);
      return h("button", { class: "cc", onclick: () => { A.strip.pulse([it.node]); A.drawer.open(it.node); } },
        h("div", { class: "cc-t" }, nodeName(it.node)), h("div", { class: "cc-h" }, it.say), h("div", { class: "cc-f" }, pill, h("span", { class: "eta" }, "open \u203a")));
    });
    const ids = Array.from(new Set(Array.from(pills.keys()).map((i) => A.catalog.nodes[i].probe).filter(Boolean)));
    api("/api/probes?ids=" + ids.join(",")).then((probes) => {
      for (const [id, pill] of pills) {
        const p = probes[A.catalog.nodes[id].probe];
        const [cls, label] = p ? PILL[p.status] || PILL.na : PILL.na;
        pill.className = "pill " + cls;
        pill.textContent = p ? label : "Portal step";
      }
    }).catch(() => { for (const pill of pills.values()) pill.textContent = "\u2014"; });
    return h("section", { class: "beat tour" },
      h("div", { class: "beat-head" }, h("span", { class: "beat-num" }, "\u2605"), h("h3", null, tour.title)),
      h("p", { class: "beat-say" }, tour.say),
      h("div", { class: "grid-cards" }, cards));
  }

  // ------------------------------------------------------------------------------------------------------ person tabs (Act 7)
  // Act 7 shows one tab per person, and on each tab that person's scenarios, instead of one long list of cards. The open tab and the
  // scenario open on each tab are remembered while you move between acts. Every scenario card stays in the page (one is visible per
  // tab), so a run keeps its result and its live board when you switch away and back.
  const TAB = { tab: "", beat: {} };
  const RT = { root: null, paint: null };
  const MARKS = { done: "\u2713 ran", live: "\u25cf running", failed: "\u2715 failed" };
  const COVER = { allowed: "\u2713 Allowed", refused: "\u2715 Refused", both: "\u2713\u2715 Both", before: "\u26a0 Before" };
  const shortOf = (b) => b.short || A.trunc(b.title, 34);
  const flash = (el) => { el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1500); };
  // What a scenario is called on the "Next" button that leads to it.
  const WHAT = { refused: "refused case", allowed: "allowed case", audit: "audit case", before: "before picture", attack: "attack case" };
  const kindOf = (b) => (b.tone === "neg" ? "refused" : b.tone === "pos" ? (b.tag === "AUDIT" ? "audit" : "allowed") : b.tag === "BEFORE" ? "before" : "attack");

  function stateOf(beatId) {
    const jid = A.store.byBeat[beatId];
    const j = jid && A.store.jobs.get(jid);
    if (!j || (!j.loaded && !j.startedHere)) return "";
    if (!j.loaded || isLive(j)) return "live";
    return j.status === "done" ? "done" : "failed";
  }

  function tabCard(scene, target) {
    const tabs = scene.tabs;
    const beats = new Map(scene.beats.filter((b) => b.tab).map((b) => [b.id, b]));
    const idsOf = (t) => t.groups.flatMap((g) => g.beats).filter((id) => beats.has(id));
    const tabOf = (id) => tabs.find((t) => idsOf(t).includes(id));
    const shown = (t) => { const ids = idsOf(t); return ids.includes(TAB.beat[t.id]) ? TAB.beat[t.id] : ids[0]; };
    const hit = target ? tabOf(target) : null;
    if (hit) { TAB.tab = hit.id; TAB.beat[hit.id] = target; }
    if (!tabs.some((t) => t.id === TAB.tab)) TAB.tab = tabs[0].id;

    const root = h("section", { class: "rt", id: "rt-" + scene.id });
    const cards = new Map(Array.from(beats.values()).map((b) => [b.id, beatCard(b)]));
    const tabBtns = new Map();
    const panels = new Map();
    const pillBtns = new Map();
    const goBtns = new Map(tabs.map((t) => [t.id, []]));
    const heads = [];

    // ---- selection: which tab and which scenario are visible
    function apply(tabId, beatId) {
      const t = tabs.find((x) => x.id === tabId) || tabs[0];
      TAB.tab = t.id;
      if (idsOf(t).includes(beatId)) TAB.beat[t.id] = beatId;
      for (const x of tabs) {
        const on = x.id === t.id;
        const btn = tabBtns.get(x.id);
        btn.classList.toggle("on", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
        btn.tabIndex = on ? 0 : -1;
        panels.get(x.id).hidden = !on;
        const cur = shown(x);
        for (const id of idsOf(x)) {
          cards.get(id).hidden = id !== cur;
          const pill = pillBtns.get(id);
          if (pill) { pill.classList.toggle("on", id === cur); pill.setAttribute("aria-pressed", id === cur ? "true" : "false"); }
        }
        paintGo(x);
      }
      return shown(t);
    }
    // Bring the tab bar back into view when you have scrolled past it (always, when asked to).
    function bring(always) {
      if (!root.scrollIntoView) return;
      const main = document.getElementById("main");
      const strip = document.getElementById("strip");
      const top = root.getBoundingClientRect().top - (main ? main.getBoundingClientRect().top : 0) - (strip ? strip.offsetHeight : 0);
      if (always || top < -2) root.scrollIntoView({ block: "start" });
    }
    function show(tabId, beatId, mode) {
      const id = apply(tabId, beatId);
      try { history.replaceState(null, "", "#" + scene.id + "/" + id); } catch (e) { /* the address bar is only a convenience */ }
      if (mode !== "keep") bring(mode === "top");
      return cards.get(id);
    }

    // ---- one person's header: who, which data roles the token carries, and whether they are signed in on this computer
    function fillHead(el) {
      const t = tabs.find((x) => x.id === el.dataset.tab);
      const pid = el.dataset.pid;
      const op = pid === "operator";
      const p = op ? null : A.persona.info(pid);
      const o = op ? A.persona.operator() : null;
      const name = op ? "Operator" : p ? p.name : t.label;
      const job = op ? (o && o.label) || t.sub : p ? p.job : t.sub;
      const roles = p ? p.roles || [] : [];
      el.replaceChildren(
        h("span", { class: "rt-av" }, name.charAt(0)),
        h("div", { class: "rt-who" }, h("b", null, name), h("span", null, job)),
        h("div", { class: "rt-roles" }, p ? (roles.length ? roles.map((r) => h("span", { class: "chip role" }, r.server + " \u00b7 " + r.role)) : h("span", { class: "chip norole" }, p.signedIn ? "no data roles" : "roles show after sign-in")) : null),
        h("div", { class: "rt-sign" },
          op ? h("span", { class: "pill na" }, "Default")
            : !p ? h("span", { class: "pill na" }, "\u2026")
              : p.signedIn ? h("span", { class: "pill ok" }, "Signed in")
                : [h("span", { class: "pill warn" }, "Not signed in"), h("button", { class: "btn tiny primary-s", onclick: () => A.persona.open(pid) }, "Sign in\u2026")]));
    }

    function reachRow(r) {
      if (!r) return null;
      const scope = r.scope || {};
      const design = r.design || [];
      const chip = (kind, id) => {
        const dz = design.includes(id);
        const cls = "rt-r " + kind + (dz ? " design" : "");
        const body = [h("span", { class: "mk" }, kind === "ok" ? "\u2713" : "\u2715"), nodeName(id), scope[id] ? h("small", null, scope[id]) : null, dz ? h("small", null, "designed, not run") : null];
        return A.catalog.nodes[id]
          ? h("button", { class: cls, title: dz ? "Predicted by the role model. A person cannot reach this server directly, so it is not run here; the Admin tab runs it through the agent." : "Open the real service", onclick: () => { A.strip.pulse([id]); A.drawer.open(id); } }, body)
          : h("span", { class: cls }, body);
      };
      return h("div", { class: "rt-reach" },
        h("span", { class: "lbl" }, "What this role can reach"),
        (r.ok || []).map((id) => chip("ok", id)),
        (r.no || []).map((id) => chip("no", id)),
        (r.gap || []).map((g) => h("span", { class: "rt-r gap", title: "Nobody holds this role, on purpose" }, h("span", { class: "mk" }, "\u2715"), g)));
    }

    const howBlock = (t) => (t.how ? h("details", { class: "rt-how" }, h("summary", null, "How these requests run"), h("p", null, t.how)) : null);

    // ---- the scenarios of one tab, as pills grouped under their captions; only the chosen scenario's card is shown
    function pillRow(t, ids) {
      if (ids.length < 2) return null;
      return h("div", { class: "rt-pills", role: "group", "aria-label": "Scenarios for " + t.label },
        t.groups.filter((g) => g.beats.some((id) => beats.has(id))).map((g) => h("div", { class: "rt-grp" },
          g.title ? h("div", { class: "rt-grp-t" }, g.title) : null,
          h("div", { class: "rt-grp-p" }, g.beats.filter((id) => beats.has(id)).map((id) => {
            const b = beats.get(id);
            const pill = h("button", { class: "rt-pill " + (b.tone || "pos"), "aria-pressed": "false", dataset: { beat: id }, onclick: () => show(t.id, id, "auto") },
              b.tag ? h("span", { class: "tag" }, b.tag) : null, h("span", { class: "tt" }, b.title), h("span", { class: "rt-st" }));
            pillBtns.set(id, pill);
            return pill;
          })))),
        goButton(t));
    }

    // ---- "Next scenario": one button beside the pills and one under the open card. It names the scenario after the open one (the one
    // before it, from the last), and nudges once the open one has run - so the refused case is never left unseen behind a pill.
    function goButton(t) {
      const el = h("button", { class: "rt-go", dataset: { tab: t.id } });
      el.addEventListener("click", () => { if (el.dataset.beat) show(t.id, el.dataset.beat, "auto"); });
      goBtns.get(t.id).push(el);
      return el;
    }
    function paintGo(t) {
      const list = goBtns.get(t.id) || [];
      const ids = idsOf(t);
      if (!list.length || ids.length < 2) return;
      const at = ids.indexOf(shown(t));
      const back = at >= ids.length - 1;
      const to = ids[back ? at - 1 : at + 1];
      const b = beats.get(to);
      const here = stateOf(ids[at]);
      const there = stateOf(to);
      const cls = "rt-go " + (b.tone || "pos") + (back ? " back" : "") + (here === "done" && there !== "done" && there !== "live" ? " attn" : "");
      const label = back ? "\u2039 Back: the " + WHAT[kindOf(b)] : "Next: the " + WHAT[kindOf(b)] + " \u203a";
      const tip = (back ? "Back to: " : "Next scenario: ") + b.title + (there === "done" ? " (already run)" : there === "live" ? " (running)" : " (not run yet)");
      for (const el of list) {
        if (el.className !== cls) el.className = cls;
        if (el.textContent !== label) el.textContent = label;
        el.title = tip;
        el.dataset.beat = to;
      }
    }

    // ---- the coverage table: every deployed piece against every tab
    function coverage(cov) {
      const cell = (row, c) => {
        const x = (row.cells || {})[c.id];
        if (!x) return h("td", { class: "cov-0" });
        const label = x.state === "design" ? (x.expect === "allowed" ? "Would allow" : "Would refuse") : COVER[x.state] || x.state;
        const first = (x.beats || [])[0];
        const where = first && tabOf(first);
        return h("td", null, h("button", { class: "cov-b " + x.state, title: (x.note || label) + (first ? " (beat " + first + ")" : ""), disabled: !where, onclick: () => flash(show(where.id, first, "top")) }, label));
      };
      const rowHead = (row) => h("th", { scope: "row", class: "cov-r" },
        h("div", { class: "cov-k" }, row.kind),
        A.catalog.nodes[row.node]
          ? h("button", { class: "cov-n", title: "Open the real service", onclick: () => { A.strip.pulse([row.node]); A.drawer.open(row.node); } }, row.label)
          : h("span", { class: "cov-n" }, row.label),
        row.sub ? h("div", { class: "cov-s mono" }, row.sub) : null,
        row.also ? h("div", { class: "cov-a" }, row.also) : null);
      return h("div", { class: "rt-cover" },
        h("h3", { class: "rt-h3" }, "What each tab covers"),
        h("p", { class: "rt-intro" }, "One row for each deployed piece: the front door, every MCP server, every agent and the audit log. Click a result to open that scenario."),
        h("div", { class: "cov-wrap" }, h("table", { class: "cov" },
          h("thead", null, h("tr", null,
            h("th", { scope: "col", class: "cov-r" }, "Deployed piece"),
            cov.cols.map((c) => h("th", { scope: "col" }, c.label, c.who && c.who !== "operator" ? h("span", { class: "rt-sd", dataset: { pid: c.who } }) : null)))),
          h("tbody", null, cov.rows.map((row) => h("tr", null, rowHead(row), cov.cols.map((c) => cell(row, c))))))),
        h("div", { class: "cov-legend" },
          cov.legend.map((l) => h("span", { class: "cov-lg" }, h("span", { class: "cov-b " + l.state }, l.label), l.text)),
          h("span", { class: "cov-lg" }, "Blank: no scenario exercises it.")));
    }

    // ---- previous / next person; the first and last tab lead to the steps on either side of the tabs
    const firstAt = scene.beats.findIndex((b) => b.tab);
    let lastAt = firstAt;
    scene.beats.forEach((b, i) => { if (b.tab) lastAt = i; });
    const before = scene.beats[firstAt - 1];
    const after = scene.beats[lastAt + 1];
    function foot(i) {
      const p = tabs[i - 1];
      const n = tabs[i + 1];
      const go = (x) => () => show(x.id, null, "top");
      const out = (b, text) => h("button", { class: "btn tiny ghost", onclick: () => A.nav(scene.id, b.id) }, text);
      return h("div", { class: "rt-foot" },
        p ? h("button", { class: "btn tiny ghost", onclick: go(p) }, "\u2039 " + p.label + " \u00b7 " + p.sub) : before ? out(before, "\u2039 " + before.id + " " + shortOf(before)) : h("span"),
        n ? h("button", { class: "btn tiny ghost", onclick: go(n) }, "Next: " + n.label + " \u00b7 " + n.sub + " \u203a") : after ? out(after, "Next: " + after.id + " " + shortOf(after) + " \u203a") : h("span"));
    }

    tabs.forEach((t, i) => {
      const ids = idsOf(t);
      const ds = { tab: t.id, beats: ids.join(" ") };
      if (t.who && t.who !== "operator") ds.pid = t.who;
      tabBtns.set(t.id, h("button", { class: "rt-tab", role: "tab", id: "rt-tab-" + t.id, "aria-controls": "rt-panel-" + t.id, "aria-selected": "false", tabindex: "-1", dataset: ds, onclick: () => show(t.id, null, "auto") },
        h("b", null, t.label, h("i", { class: "rt-dot" })),
        h("span", { class: "sub" }, t.sub)));
      let head = null;
      if (t.who) { head = h("div", { class: "rt-head", dataset: { tab: t.id, pid: t.who } }); heads.push(head); }
      panels.set(t.id, h("div", { class: "rt-panel", role: "tabpanel", id: "rt-panel-" + t.id, "aria-labelledby": "rt-tab-" + t.id, hidden: true },
        head,
        h("h2", { class: "rt-title" }, t.title),
        h("p", { class: "rt-intro" }, t.intro),
        reachRow(t.reach),
        howBlock(t),
        pillRow(t, ids),
        h("div", { class: "rt-beats" }, ids.map((id) => cards.get(id))),
        ids.length > 1 ? h("div", { class: "rt-next" }, goButton(t)) : null,
        t.coverage && scene.coverage ? coverage(scene.coverage) : null,
        foot(i)));
    });

    const bar = h("div", { class: "rt-bar", role: "tablist", "aria-label": "Pick a person" }, tabs.map((t) => tabBtns.get(t.id)));
    bar.addEventListener("keydown", (e) => {
      const at = tabs.findIndex((t) => t.id === TAB.tab);
      const to = e.key === "ArrowRight" ? (at + 1) % tabs.length : e.key === "ArrowLeft" ? (at + tabs.length - 1) % tabs.length : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : -1;
      if (to < 0) return;
      e.preventDefault();
      show(tabs[to].id, null, "keep");
      tabBtns.get(tabs[to].id).focus();
    });
    root.append(bar, ...tabs.map((t) => panels.get(t.id)));

    // ---- progress marks, sign-in state: repainted whenever a run changes or someone signs in
    function paint() {
      for (const t of tabs) {
        const ids = idsOf(t);
        const st = ids.map(stateOf);
        const nDone = st.filter((s) => s === "done").length;
        const btn = tabBtns.get(t.id);
        const p = btn.dataset.pid ? A.persona.info(btn.dataset.pid) : null;
        btn.classList.toggle("done", ids.length > 0 && nDone === ids.length);
        btn.classList.toggle("part", nDone > 0 && nDone < ids.length);
        btn.classList.toggle("live", st.includes("live"));
        btn.classList.toggle("need", !!p && !p.signedIn);
        btn.title = t.title + " \u2014 " + nDone + " of " + ids.length + " run" + (p && !p.signedIn ? ". " + p.name + " is not signed in yet: open Acting as (P) and sign in once." : "");
        paintGo(t);
      }
      for (const [id, pill] of pillBtns) {
        const s = stateOf(id);
        const mk = pill.querySelector(".rt-st");
        mk.className = "rt-st " + (s || "none");
        mk.textContent = MARKS[s] || "not run yet";
      }
      root.querySelectorAll(".rt-sd").forEach((d) => {
        const p = A.persona.info(d.dataset.pid);
        d.className = "rt-sd" + (p ? (p.signedIn ? " ok" : " no") : "");
        d.title = p ? (p.signedIn ? p.name + " is signed in" : p.name + " is not signed in") : "";
      });
      heads.forEach(fillHead);
    }

    apply(TAB.tab, TAB.beat[TAB.tab]);
    RT.root = root;
    RT.paint = paint;
    paint();
    return root;
  }
  const paintTabs = () => { if (RT.root && RT.root.isConnected && RT.paint) RT.paint(); };

  // A short row of links at the top of a tabbed act: the tab block counts as one stop.
  function jumpRow(scene) {
    let tabsDone = false;
    const chips = [];
    for (const b of scene.beats) {
      if (b.tab && tabsDone) continue;
      if (b.tab) tabsDone = true;
      const go = b.tab ? () => { if (RT.root && RT.root.scrollIntoView) RT.root.scrollIntoView({ block: "start" }); } : () => A.nav(scene.id, b.id);
      chips.push(h("button", { class: "chip", title: b.tab ? "Jump to the person tabs" : b.title, onclick: go }, b.id + " " + shortOf(b), h("span", { class: "go" }, "\u203a")));
    }
    return h("div", { class: "rt-jump" }, h("span", { class: "lbl" }, "Jump to"), chips);
  }

  function scenePage(scene, target) {
    const tabbed = Array.isArray(scene.tabs) && scene.tabs.length > 0 && scene.beats.some((b) => b.tab);
    const body = [];
    let placed = false;
    for (const b of scene.beats) {
      if (!(tabbed && b.tab)) body.push(beatCard(b));
      else if (!placed) { body.push(tabCard(scene, target)); placed = true; }
    }
    return h("div", null,
      h("div", { class: "eyebrow" }, scene.nav),
      h("h1", { style: { fontSize: "34px", margin: 0 } }, scene.title),
      h("p", { class: "story" }, scene.story),
      scene.order ? callout("Order:", scene.order, "warn") : null,
      scene.wait ? callout("Timing:", scene.wait, "") : null,
      scene.beats.some((b) => [b.run].concat((b.alt || []).map((a) => a.run)).some(A.persona.applies)) ? A.persona.banner() : null,
      tabbed ? jumpRow(scene) : null,
      body,
      scene.tour ? tourCard(scene.tour) : null);
  }

  // --------------------------------------------------------------------------------------------------------------- Control Room
  const GROUPS = [
    ["Build & run", ["foundry", "guardrail", "agentid", "controlplane", "entra", "ca"]],
    ["Gateway & tools", ["apim", "apic", "m-research", "m-wall", "m-actions", "m-private", "m-vendor", "m-legacy"]],
    ["Data", ["data", "worm"]],
    ["Watchtower", ["monitor", "sentinel", "defender", "purview", "policy", "agent365"]],
  ];
  const PILL = { ok: ["ok", "Live"], warn: ["warn", "Check"], fail: ["fail", "Problem"], na: ["na", "Portal step"] };

  function controlRoom() {
    const cards = new Map();
    const paint = (probes) => {
      for (const [id, rec] of cards) {
        const n = A.catalog.nodes[id];
        const p = n.probe ? probes[n.probe] : null;
        const [cls, label] = p ? PILL[p.status] || PILL.na : PILL.na;
        rec.pill.className = "pill " + cls;
        rec.pill.textContent = p ? label : "Portal step";
        rec.hint.textContent = p ? p.headline : "No live check - open it in the portal.";
      }
    };
    const refresh = (force) => {
      const ids = Array.from(new Set(Array.from(cards.keys()).map((i) => A.catalog.nodes[i].probe).filter(Boolean)));
      api("/api/probes?ids=" + ids.join(",") + (force ? "&force=1" : "")).then(paint).catch((e) => toast(e.message, true));
    };
    const sections = GROUPS.map(([title, ids]) => h("div", null,
      h("div", { class: "section-title" }, title),
      h("div", { class: "grid-cards" }, ids.filter((i) => A.catalog.nodes[i]).map((id) => {
        const n = A.catalog.nodes[id];
        const pill = h("span", { class: "pill na" }, "\u2026");
        const hint = h("div", { class: "cc-h" }, n.plain);
        cards.set(id, { pill, hint });
        return h("button", { class: "cc", onclick: () => A.drawer.open(id) }, h("div", { class: "cc-t" }, n.title), hint, h("div", { class: "cc-f" }, pill, h("span", { class: "eta" }, "open \u203a")));
      }))));
    const page = h("div", null,
      h("div", { class: "eyebrow" }, "Control Room"),
      h("h1", { style: { fontSize: "34px", margin: 0 } }, "Every component, live"),
      h("p", { class: "story" }, "Each card reads the real state from Azure just now (read-only, no secrets). Open one to see the live facts, the portal link and what to point at."),
      h("div", { class: "ops" }, h("button", { class: "btn", onclick: () => refresh(true) }, "Refresh all"), h("span", { class: "eta" }, "\u201cPortal step\u201d means the configuration lives in a portal with no API we can read - the card shows the click-path.")),
      sections);
    refresh(false);
    return page;
  }

  // ------------------------------------------------------------------------------------------------------------------ Scoreboard
  const SAFE_EVIDENCE = /^(prove|try-violations|burst)-[0-9T_-]+\.json$/;
  function scoreboard() {
    const body = h("div", null, h("div", { class: "skeleton" }, "Loading the proof catalogue\u2026"));
    api("/api/scoreboard").then((rows) => {
      const pass = rows.filter((r) => r.passed).length;
      const checksOk = rows.reduce((n, r) => n + (r.checks_ok || 0), 0);
      const checksTotal = rows.reduce((n, r) => n + (r.checks_total || 0), 0);
      body.replaceChildren(
        h("div", { class: "sb-sum", style: { color: pass === rows.length && rows.length ? "var(--green)" : "var(--amber)" } }, pass + " / " + rows.length + " proofs passed \u00b7 " + checksOk + " / " + checksTotal + " checks"),
        h("div", { class: "tbl-wrap", style: { maxHeight: "none" } }, h("table", { class: "tbl sb" },
          h("thead", null, h("tr", null, ["", "Proof", "Layer", "Checks", "Time", "Evidence"].map((c) => h("th", null, c)))),
          h("tbody", null, rows.map((r) => h("tr", null,
            h("td", null, h("span", { class: "pill " + (r.passed ? "ok" : "fail") }, r.id)),
            h("td", null, r.title),
            h("td", null, r.layer),
            h("td", null, r.checks_ok + " / " + r.checks_total),
            h("td", null, secs(r.seconds)),
            h("td", null, SAFE_EVIDENCE.test(r.evidence || "") ? h("a", { href: "/api/evidence/" + r.evidence, target: "_blank", rel: "noopener" }, "open") : "\u2014")))))));
    }).catch((e) => body.replaceChildren(h("div", { class: "notice err" }, e.message)));
    return h("div", null,
      h("div", { class: "eyebrow" }, "Scoreboard"),
      h("h1", { style: { fontSize: "34px", margin: 0 } }, "Everything on this console is re-provable"),
      h("p", { class: "story" }, "Eighteen automated proofs, each re-runnable from the command line (python demo\\prove.py). Each one stores its evidence as a JSON file."),
      body,
      h("div", { class: "section-title" }, "Re-check the baseline now"),
      opsBlock());
  }

  A.pages = { startPage, scenePage, controlRoom, scoreboard, beatScene, paintTabs };
})(window.ABW);
