"use strict";
/* Personas: the "Acting as" switcher. The button at the top of the left rail picks who the gateway steps run as; the side panel signs people
   in and proves what each token really carries. Agent steps always run as the operator.
   Passwords and authenticator keys never reach this page: the console server copies a password to the clipboard and keeps
   the setup key on disk. This page only ever sees the short-lived six-digit code. */
(function (A) {
  const { h, $, api, toast, copy } = A;

  const KEY = "abw.persona";
  const OPERATOR = "operator";
  const AS_KINDS = ["gateway", "xpia", "burst"]; // the job kinds the server can run as a persona (jobs.PERSONA_KINDS)
  // Act 6 scenarios: "follow" ones run as whoever is chosen here; ones with a fixed persona are pinned to that person (e2e.persona_for).

  const S = { data: null, error: "", current: OPERATOR, want: OPERATOR, busy: new Set(), verify: {}, codes: {}, draft: {}, mfa: {} };
  let timer = null;

  const byId = (pid) => (S.data ? S.data.personas.find((p) => p.id === pid) || null : null);
  const first = (p) => (p ? p.name.split(" ")[0] : "Operator");
  const selected = () => (S.current === OPERATOR ? null : byId(S.current));
  const isOpen = () => !!A.drawer && A.drawer.current === "personas";
  const busy = (pid, what) => S.busy.has(pid + ":" + what);
  const applies = (run) => !!run && ((AS_KINDS.includes(run.kind) && run.server !== "legacy") || (run.kind === "e2e" && !!run.follow));
  const pinnedOf = (run) => (run && run.kind === "e2e" && !run.follow && typeof run.persona === "string" && run.persona ? run.persona : null);
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const secsLeft = (until) => Math.max(0, Math.round((until - Date.now()) / 1000));
  const clock = (until) => { const s = secsLeft(until); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };

  // The job request gets the persona only for steps that go through the gateway (never the shared-key legacy contrast).
  function withPersona(run) {
    return S.current !== OPERATOR && applies(run) && !run.persona ? Object.assign({}, run, { persona: S.current }) : run;
  }

  // ------------------------------------------------------------------------------------------------ live labels
  function fillPill(btn) {
    const p = selected();
    btn.classList.toggle("on", !!p);
    btn.replaceChildren(...[h("span", { class: "pp-k" }, "Acting as"), h("b", null, p ? p.name : "Operator"), p ? h("span", { class: "pp-j" }, p.job) : null].filter(Boolean));
    btn.title = (p ? p.label : S.data ? S.data.operator.label : "Operator") + " \u2014 click to switch who the gateway steps run as (P)";
  }
  function paintPill() {
    const btn = $("#btn-persona");
    if (btn) fillPill(btn);
  }
  // Built here, placed at the top of the left rail by app.js (the top bar has no spare width at laptop sizes).
  function pill() {
    const btn = h("button", { class: "btn persona-pill", id: "btn-persona", onclick: toggle });
    fillPill(btn);
    return btn;
  }
  function paintChip(el) {
    const p = selected();
    el.hidden = !p;
    el.textContent = p ? "as " + first(p) : "";
  }
  // A pinned scenario always runs as one named person: show who, and warn while that person is not signed in on this computer.
  function paintPinned(el) {
    const pid = el.dataset.pid;
    const p = byId(pid);
    const need = !!S.data && !(p && p.signedIn);
    el.classList.toggle("need", need);
    el.textContent = "as " + (p ? first(p) : cap(pid)) + (need ? " \u00b7 sign in first (P)" : "");
    el.title = (p ? "This scenario always runs as " + p.name + " (" + p.job + ")" : "This scenario always runs as " + cap(pid)) + (need ? ". Open Acting as (P) and sign in once, then run it." : ".");
  }
  function paintBanner(el) {
    const p = selected();
    el.hidden = !p;
    el.replaceChildren(...(p ? [
      h("b", null, "Acting as " + p.name + " (" + p.job + "). "),
      "Steps marked \u201cas " + first(p) + "\u201d use this person\u2019s own token at the gateway. Agent steps still run as the operator, because Foundry holds the operator\u2019s sign-in.",
    ] : []));
  }
  function paintAll() {
    paintPill();
    document.querySelectorAll(".as-chip:not(.pinned)").forEach(paintChip);
    document.querySelectorAll(".as-chip.pinned").forEach(paintPinned);
    document.querySelectorAll(".persona-banner").forEach(paintBanner);
    if (A.pages && A.pages.paintTabs) A.pages.paintTabs();
  }
  const chip = (run) => {
    if (applies(run)) { const el = h("span", { class: "as-chip", hidden: true }); paintChip(el); return el; }
    const pid = pinnedOf(run);
    if (!pid) return null;
    const el = h("span", { class: "as-chip pinned", dataset: { pid } });
    paintPinned(el);
    return el;
  };
  const banner = () => { const el = h("div", { class: "callout persona-banner", hidden: true }); paintBanner(el); return el; };

  function remember() { try { localStorage.setItem(KEY, S.want); } catch (e) { /* private mode */ } }

  function choose(pid) {
    const p = pid === OPERATOR ? null : byId(pid);
    if (pid !== OPERATOR && !(p && p.signedIn)) { toast("Sign " + first(p) + " in first.", true); return; }
    S.want = S.current = p ? p.id : OPERATOR;
    remember();
    paintAll();
    renderPanel();
    toast(p ? "Gateway steps now run as " + p.name : "Gateway steps now run as the operator");
  }

  // The stored choice only counts while that person is still signed in on this computer.
  function reconcile() {
    if (S.want === OPERATOR) { S.current = OPERATOR; return; }
    const p = byId(S.want);
    if (p && p.signedIn) { S.current = p.id; return; }
    toast((p ? p.name : "That person") + " is not signed in on this computer, so gateway steps run as the operator.", true);
    S.want = S.current = OPERATOR;
    remember();
  }

  // ------------------------------------------------------------------------------------------------ server calls
  const post = (pid, action, body) => api("/api/personas/" + pid + "/" + action, { method: "POST", body: body || {} });

  async function act(pid, what, fn) {
    const k = pid + ":" + what;
    if (S.busy.has(k)) return;
    S.busy.add(k);
    renderPanel();
    try { await fn(); } catch (e) { toast(e.message, true); } finally { S.busy.delete(k); renderPanel(); }
  }

  function setLogin(pid, login) {
    const p = byId(pid);
    if (p) p.login = login && login.state ? Object.assign(login, { at: Date.now() }) : null;
  }

  const signIn = (p) => act(p.id, "login", async () => {
    setLogin(p.id, await post(p.id, "login"));
    delete S.verify[p.id];
    schedule();
  });
  const cancelLogin = (p) => act(p.id, "cancel", async () => { setLogin(p.id, (await post(p.id, "login/cancel")).login); });
  const openWindow = (p) => act(p.id, "open", async () => {
    const r = await post(p.id, "open");
    toast("Opened a private " + r.browser + " window. The code is on your clipboard: paste it with Ctrl+V.");
  });
  const copyPassword = (p) => act(p.id, "password", async () => {
    const r = await post(p.id, "password");
    toast("Password copied. It leaves the clipboard in " + r.clearsInSeconds + " s.");
  });
  const showCode = (p) => act(p.id, "code", async () => {
    const r = await post(p.id, "code");
    S.codes[p.id] = { code: r.code, until: Date.now() + r.secondsLeft * 1000 };
  });
  const saveKey = (p) => act(p.id, "totp", async () => {
    const raw = (S.draft[p.id] || "").trim();
    if (!raw) { toast("Paste the authenticator setup key first.", true); return; }
    const r = await post(p.id, "totp", { secret: raw });
    S.draft[p.id] = "";
    S.codes[p.id] = { code: r.code, until: Date.now() + r.secondsLeft * 1000 };
    const q = byId(p.id);
    if (q) q.hasTotp = true;
    toast("Setup key saved. The code shown is live.");
  });
  async function verifyToken(p) {
    S.verify[p.id] = { loading: true };
    await act(p.id, "verify", async () => {
      try { S.verify[p.id] = await post(p.id, "verify"); } catch (e) { S.verify[p.id] = { error: e.message }; }
    });
  }

  function noteSignIns(prev, next) {
    for (const p of next.personas) {
      const was = prev && prev.personas.find((q) => q.id === p.id);
      if (was && was.login && was.login.state === "pending" && p.login && p.login.state === "ok") {
        toast(p.name + " is signed in. Checking the real token\u2026");
        verifyToken(p);
      }
    }
  }

  async function refresh() {
    const prev = S.data;
    try {
      const next = await api("/api/personas");
      const now = Date.now();
      next.personas.forEach((p) => { if (p.login) p.login.at = now; });
      S.data = next;
      S.error = "";
      reconcile();
      noteSignIns(prev, next);
    } catch (e) {
      S.error = e.status === 404 ? "This console was started before the persona switcher was added. Close it and start Start-Console.bat again." : e.message;
    }
    paintAll();
    renderPanel();
  }

  // Poll only while a sign-in is waiting for someone to finish it in the other window.
  function schedule() {
    clearTimeout(timer);
    if (!isOpen() || !S.data || !S.data.personas.some((p) => p.login && p.login.state === "pending")) return;
    timer = setTimeout(async () => { if (!isOpen()) return; await refresh(); schedule(); }, 2000);
  }

  // Countdowns (device code, one-time code) tick in place; nothing is re-fetched.
  function tick() {
    for (const el of document.querySelectorAll("[data-until]")) {
      const until = Number(el.dataset.until);
      el.textContent = el.dataset.fmt === "clock" ? clock(until) : secsLeft(until) + " s";
      if (secsLeft(until) === 0 && el.dataset.expire && S.codes[el.dataset.expire]) { delete S.codes[el.dataset.expire]; renderPanel(); }
    }
  }

  // ------------------------------------------------------------------------------------------------ panel
  const step = (n, kids) => h("div", { class: "pc-step" }, h("b", null, n), h("div", { class: "grow" }, kids));

  function loginBox(p) {
    const lg = p.login;
    const until = lg.at + lg.expiresIn * 1000;
    const found = S.data.browser;
    return h("div", { class: "pc-login" },
      step("1", [
        "Open the Microsoft sign-in page in a private window. The code is already on your clipboard: paste it with Ctrl+V.",
        h("div", { class: "pc-row" },
          h("button", { class: "btn tiny primary-s", disabled: !found || busy(p.id, "open"), onclick: () => openWindow(p) }, "Open private window"),
          h("span", { class: "eta" }, found ? found + " \u00b7 its own profile, nothing shared with your own session" : "No Edge or Chrome found. Open " + lg.uri + " yourself.")),
        h("div", { class: "pc-row" },
          h("span", { class: "lbl" }, "Code"),
          h("code", { class: "mono pc-codebig" }, lg.userCode),
          h("button", { class: "btn tiny", onclick: () => copy(lg.userCode, "Code copied") }, "Copy"),
          h("span", { class: "eta" }, "expires in ", h("span", { dataset: { until: String(until), fmt: "clock" } }, clock(until)))),
      ]),
      step("2", [
        ["Sign in as ", h("code", null, p.upn)],
        h("div", { class: "pc-row" },
          h("button", { class: "btn tiny", onclick: () => copy(p.upn, "Username copied") }, "Copy username"),
          p.hasPassword
            ? [h("button", { class: "btn tiny", disabled: busy(p.id, "password"), onclick: () => copyPassword(p) }, "Copy password"), h("span", { class: "eta" }, "never shown; leaves the clipboard after 60 s")]
            : h("span", { class: "eta" }, "no stored password; type it yourself")),
      ]),
      step("3", "If it asks for a verification code, use the one-time code just below."),
      h("div", { class: "pc-row" }, h("button", { class: "btn tiny danger", disabled: busy(p.id, "cancel"), onclick: () => cancelLogin(p) }, "Cancel sign-in")));
  }

  function mfaBlock(p) {
    const c = S.codes[p.id];
    const kids = [];
    if (c) {
      kids.push(h("div", { class: "pc-row" },
        h("code", { class: "mono pc-otp" }, c.code.slice(0, 3) + " " + c.code.slice(3)),
        h("button", { class: "btn tiny", onclick: () => copy(c.code, "Code copied") }, "Copy"),
        h("span", { class: "eta" }, "valid for ", h("span", { dataset: { until: String(c.until), fmt: "s", expire: p.id } }, secsLeft(c.until) + " s"))));
    } else if (p.hasTotp) {
      kids.push(h("div", { class: "pc-row" }, h("button", { class: "btn tiny", disabled: busy(p.id, "code"), onclick: () => showCode(p) }, "Show the current code")));
    }
    kids.push(h("div", { class: "pc-row" },
      h("input", {
        class: "secret-input", type: "text", autocomplete: "off", spellcheck: "false", dataset: { keep: "key-" + p.id }, value: S.draft[p.id] || "",
        placeholder: p.hasTotp ? "Paste a new setup key to replace the stored one" : "Paste the authenticator setup key",
        oninput: (e) => { S.draft[p.id] = e.target.value; },
        onkeydown: (e) => { if (e.key === "Enter") saveKey(p); },
      }),
      h("button", { class: "btn tiny", disabled: busy(p.id, "totp"), onclick: () => saveKey(p) }, "Save key")));
    kids.push(h("div", { class: "eta" }, "First time only: when Entra offers an authenticator, choose \u201cI want to use a different authenticator app\u201d, then \u201cCan\u2019t scan image?\u201d, and paste the key here. It stays on this computer."));
    return h("div", { class: "pc-mfa" }, h("div", { class: "pc-sub" }, "One-time code (MFA)"), kids);
  }

  // What the persona's real tokens carry, next to what the story says they should carry.
  function verifyView(p) {
    const v = S.verify[p.id];
    if (!v) return null;
    if (v.loading) return h("div", { class: "pc-verify eta" }, "Reading the real tokens from Entra\u2026");
    if (v.error) return h("div", { class: "pc-verify" }, h("div", { class: "notice fail" }, h("p", null, v.error)));
    const expect = {};
    for (const r of p.roles) (expect[r.server] = expect[r.server] || []).push(r.role);
    const rows = Object.entries(v.servers || {}).map(([srv, s]) => {
      if (!s.ok) return h("tr", null, h("td", { class: "mono" }, srv), h("td", { class: "bad" }, s.error || "could not get a token"), h("td", { class: "bad" }, "\u26a0"));
      const got = (s.roles || []).slice().sort();
      const want = (expect[srv] || []).slice().sort();
      const same = got.length === want.length && got.every((x, i) => x === want[i]);
      return h("tr", null,
        h("td", { class: "mono" }, srv),
        h("td", null, got.length ? got.map((r) => h("span", { class: "chip role" }, r)) : h("span", { class: "eta" }, "no roles")),
        h("td", { class: same ? "okc" : "bad" }, same ? "\u2713 as designed" : "\u26a0 differs"));
    });
    return h("div", { class: "pc-verify" },
      h("div", { class: "pc-sub" }, "Real token check \u00b7 " + new Date(v.checkedAt * 1000).toLocaleTimeString()),
      h("div", { class: "eta" }, "Signed in as ", h("code", null, (v.who && v.who.upn) || p.upn)),
      h("table", null, h("tbody", null, rows)));
  }

  function card(p) {
    const sel = S.current === p.id;
    const lg = p.login;
    const pending = !!lg && lg.state === "pending";
    const bad = !!lg && (lg.state === "failed" || lg.state === "expired") && !!lg.error;
    const status = p.signedIn ? h("span", { class: "pill ok" }, "Signed in") : pending ? h("span", { class: "pill warn" }, "Signing in") : h("span", { class: "pill na" }, "Not signed in");
    const actions = [];
    if (p.signedIn) {
      actions.push(sel
        ? h("button", { class: "btn tiny sel", disabled: true }, "Acting as " + first(p) + " \u2713")
        : h("button", { class: "btn tiny good", onclick: () => choose(p.id) }, "Act as " + first(p)));
      actions.push(h("button", { class: "btn tiny", disabled: busy(p.id, "verify"), onclick: () => verifyToken(p) }, "Verify token"));
    }
    if (!pending) actions.push(h("button", { class: "btn tiny" + (p.signedIn ? " ghost" : " primary-s"), disabled: busy(p.id, "login"), onclick: () => signIn(p) }, p.signedIn ? "Sign in again" : "Sign in"));
    actions.push(h("button", { class: "btn tiny ghost", onclick: () => { S.mfa[p.id] = !S.mfa[p.id]; renderPanel(); } }, S.mfa[p.id] ? "Hide one-time code" : "One-time code"));
    return h("div", { class: "pc" + (sel ? " sel" : ""), id: "pc-" + p.id },
      h("div", { class: "pc-head" }, h("div", { class: "who" }, h("b", { class: "pc-name" }, p.name), h("span", { class: "pc-job" }, p.job)), status),
      h("div", { class: "pc-chips" }, p.roles.length ? p.roles.map((r) => h("span", { class: "chip role" }, r.server + " \u00b7 " + r.role)) : h("span", { class: "chip norole" }, "no data roles")),
      h("div", { class: "pc-groups" }, "Groups: " + (p.groups.length ? p.groups.join(", ") : "none")),
      h("p", { class: "pc-story" }, p.story),
      h("div", { class: "pc-actions" }, actions),
      bad ? h("div", { class: "notice fail" }, h("p", null, lg.error)) : null,
      pending ? loginBox(p) : null,
      S.mfa[p.id] || pending ? mfaBlock(p) : null,
      verifyView(p));
  }

  function operatorCard() {
    const sel = S.current === OPERATOR;
    return h("div", { class: "pc" + (sel ? " sel" : "") },
      h("div", { class: "pc-head" }, h("div", { class: "who" }, h("b", { class: "pc-name" }, "Operator"), h("span", { class: "pc-job" }, S.data.operator.label)), h("span", { class: "pill na" }, "Default")),
      h("p", { class: "pc-story" }, S.data.operator.story),
      h("div", { class: "pc-actions" }, sel
        ? h("button", { class: "btn tiny sel", disabled: true }, "Acting as the operator \u2713")
        : h("button", { class: "btn tiny good", onclick: () => choose(OPERATOR) }, "Act as the operator")));
  }

  function panel() {
    const kids = [
      h("div", { class: "dr-head" }, h("h2", null, "Who the gateway steps run as"), h("button", { class: "btn tiny", onclick: A.drawer.close }, "Close \u2715")),
      h("div", { class: "dr-plain" }, "Pick a person and the gateway steps use that person\u2019s own Entra token, so the same tool can be allowed for one role and refused for another. Agent steps keep running as the operator."),
    ];
    if (!S.data) {
      kids.push(S.error
        ? h("div", { class: "notice err", style: { marginTop: "14px" } }, h("h4", null, "Could not read the personas"), h("p", null, S.error), h("p", null, h("button", { class: "btn tiny", onclick: refresh }, "Try again")))
        : h("div", { class: "skeleton", style: { marginTop: "14px" } }, "Reading who is signed in\u2026"));
      return kids;
    }
    kids.push(operatorCard(), S.data.personas.map(card),
      h("p", { class: "eta", style: { marginTop: "16px" } }, "Each sign-in is saved on this computer only. Passwords are never shown on screen: \u201cCopy password\u201d puts one on the clipboard for 60 seconds, kept out of the Windows clipboard history."));
    return kids;
  }

  // Rebuilds the panel but keeps the scroll position and whatever text box has focus (an in-progress key paste).
  function renderPanel() {
    if (!isOpen()) return;
    const el = $("#drawer");
    const a = document.activeElement;
    const keep = a && el.contains(a) && a.dataset ? a.dataset.keep : "";
    const sel = keep ? [a.selectionStart, a.selectionEnd] : null;
    const top = el.scrollTop;
    el.replaceChildren(...panel().flat(Infinity));
    el.scrollTop = top;
    if (keep) {
      const n = el.querySelector('[data-keep="' + keep + '"]');
      if (n) { n.focus(); try { n.setSelectionRange(sel[0], sel[1]); } catch (e) { /* not a text field */ } }
    }
  }

  function open(pid) {
    A.drawer.current = "personas";
    if (A.strip) for (const b of A.strip.nodes.values()) b.style.outline = "";
    const el = $("#drawer");
    el.classList.remove("closed");
    renderPanel();
    el.scrollTop = 0;
    const card = typeof pid === "string" ? document.getElementById("pc-" + pid) : null; // the person tabs send you straight to that person to sign in
    if (card && card.scrollIntoView) card.scrollIntoView({ block: "start" });
    refresh().then(schedule);
  }
  const toggle = () => { if (isOpen()) A.drawer.close(); else open(); };

  function init() {
    try { S.want = localStorage.getItem(KEY) || OPERATOR; } catch (e) { S.want = OPERATOR; }
    paintPill();
    setInterval(tick, 1000);
    refresh();
  }

  A.persona = { init, toggle, open, applies, chip, banner, pill, info: (pid) => byId(pid), operator: () => (S.data ? S.data.operator : null) };
  A.withPersona = withPersona;
})(window.ABW);
