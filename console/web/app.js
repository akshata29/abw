"use strict";
/* Boot, router, header (status lights, running jobs), left rail, keyboard. */
(function (A) {
  const { h, $, $$, api, toast, secs } = A;

  const SCENE_IDS = ["start", "act1", "act2", "act3", "act4", "act5", "e2e", "roles", "control", "scoreboard"];
  let current = "start";

  // ------------------------------------------------------------------------------------------------------------- navigation
  A.nav = function (sceneId, beatId) {
    const target = "#" + sceneId + (beatId ? "/" + beatId : "");
    if (location.hash === target) render(); else location.hash = target;
  };

  // The person tabs stick just under the architecture strip, so they need to know how tall it really is.
  function sizeStrip() {
    const s = $("#strip");
    document.documentElement.style.setProperty("--strip-h", (s && !s.classList.contains("hidden") ? s.offsetHeight : 0) + "px");
  }

  function render() {
    const [sid, beat] = (location.hash.slice(1) || "start").split("/");
    current = SCENE_IDS.includes(sid) ? sid : "start";
    let node;
    if (current === "start") node = A.pages.startPage();
    else if (current === "control") node = A.pages.controlRoom();
    else if (current === "scoreboard") node = A.pages.scoreboard();
    else node = A.pages.scenePage(A.catalog.scenes.find((s) => s.id === current), beat);
    $("#page").replaceChildren(node);
    A.strip.show(current !== "scoreboard");
    sizeStrip();
    A.paintRail();
    $("#main").scrollTop = 0;
    if (beat) {
      const el = document.getElementById("beat-" + beat);
      if (el) {
        (el.closest(".rt") || el).scrollIntoView({ block: "start" }); // a scenario on a person tab: show the tab bar above it
        el.classList.add("flash");
        setTimeout(() => el.classList.remove("flash"), 1500);
      }
    }
  }

  // ------------------------------------------------------------------------------------------------------------------ rail
  // The person tabs of Act 7 would add twenty-one dots, so they share one (green when every scenario has run, half when some have).
  function railDots(scene) {
    const dots = [];
    let people = null;
    for (const b of scene.beats) {
      const tab = b.tab && (scene.tabs || []).find((t) => t.id === b.tab);
      if (tab && tab.who) {
        if (!people) { people = { ids: [], title: "Person tabs" }; dots.push(people); }
        people.ids.push(b.id);
      } else dots.push({ ids: [b.id], title: b.title });
    }
    return dots;
  }
  function buildRail() {
    const scenes = A.catalog.scenes;
    const item = (id, label, scene) => h("button", { class: "rail-item", "data-scene": id, onclick: () => A.nav(id) },
      h("span", null, label),
      scene && scene.beats.length ? h("span", { class: "dots" }, railDots(scene).map((d) => h("i", { "data-beat": d.ids.join(" "), title: d.title }))) : null);
    $("#rail").replaceChildren(...[
      A.persona.pill(),
      item("start", "Start"),
      scenes.filter((s) => s.id !== "start").map((s) => item(s.id, s.nav, s)),
      h("div", { class: "rail-sep" }),
      item("control", "Control Room"),
      item("scoreboard", "Scoreboard"),
      h("div", { class: "rail-foot" }, "Keys: ", h("code", null, "N"), " notes \u00b7 ", h("code", null, "P"), " persona \u00b7 ", h("code", null, "1-7"), " acts \u00b7 ", h("code", null, "Esc"), " close panel"),
    ].flat());
  }
  A.paintRail = function () {
    $$(".rail-item").forEach((el) => el.classList.toggle("active", el.dataset.scene === current));
    $$(".rail-item i[data-beat]").forEach((dot) => {
      const ids = dot.dataset.beat.split(" ");
      const n = ids.filter((b) => { const id = A.store.byBeat[b]; const j = id && A.store.jobs.get(id); return !!j && j.status === "done"; }).length;
      dot.classList.toggle("on", n === ids.length);
      dot.classList.toggle("half", n > 0 && n < ids.length);
      if (ids.length > 1) dot.title = "Person tabs: " + n + " of " + ids.length + " run";
    });
    if (A.pages && A.pages.paintTabs) A.pages.paintTabs();
  };

  // ------------------------------------------------------------------------------------------------------------ status lights
  const SHORT = {
    gateway: (d) => (/^answering/i.test(d) ? "up" : A.trunc(d, 20)),
    kill: (d) => (/^ENGAGED/.test(d) ? "ENGAGED" : A.trunc(d, 14)),
    allow: (d) => (!d || d === "empty" ? "empty" : d.split(",").filter((x) => x.trim()).length + " clients"),
  };
  A.refreshStatus = async function (fresh) {
    try {
      const s = await api("/api/status" + (fresh ? "?fresh=1" : ""));
      $("#lights").replaceChildren(...s.lights.map((l) => {
        const cls = { ok: "ok", warn: "warn", bad: "fail" }[l.state] || "";
        const short = SHORT[l.id] && l.detail ? SHORT[l.id](l.detail) : "";
        const text = (l.id === "allow" ? "Allow-list" : l.label) + (short ? " \u00b7 " + short : "");
        return h("span", { class: "light " + cls, title: l.label + ": " + l.detail }, h("i"), text);
      }));
    } catch (e) {
      $("#lights").replaceChildren(h("span", { class: "light fail" }, h("i"), "Console server not answering"));
    }
  };

  // --------------------------------------------------------------------------------------------------------- running-jobs chips
  function paintRunning() {
    const live = Array.from(A.store.jobs.values()).filter((j) => j.status === "running" || j.status === "waiting");
    $("#running").replaceChildren(...live.slice(0, 3).map((j) => {
      const t = j.elapsed + (Date.now() - j.fetchedAt) / 1000;
      const base = String(j.beat || "").replace(/L$/, ""); // a "Refresh from logs" job carries its step's number plus an L
      const where = A.pages.beatScene(base);
      return h("span", { class: "run-chip " + j.status, title: "Click to go to this step", onclick: () => (where ? A.nav(where.id, base) : A.nav("start")) },
        j.status === "waiting" ? "\u23f8" : h("span", { class: "spin" }), (j.beat ? j.beat + " \u00b7 " : "") + A.trunc(j.title, 26) + " \u00b7 " + secs(t));
    }));
  }
  A.onJobUpdate = () => { paintRunning(); A.paintRail(); };
  setInterval(paintRunning, 1000);

  // ------------------------------------------------------------------------------------------------------------------ controls
  function setNotes(on) {
    document.body.classList.toggle("notes-on", on);
    $("#btn-notes").classList.toggle("on", on);
    try { localStorage.setItem("abw.notes", on ? "1" : "0"); } catch (e) { /* private mode */ }
  }
  function runOp(id) {
    A.nav("start");
    setTimeout(() => { const b = document.getElementById("ops-" + id); if (b && !b.disabled) b.click(); }, 120);
  }
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ""))) return;
    if (e.key === "Escape") A.drawer.close();
    else if (e.key === "n" || e.key === "N") setNotes(!document.body.classList.contains("notes-on"));
    else if (e.key === "p" || e.key === "P") A.persona.toggle();
    else if (e.key === "0") A.nav("start");
    else if (/^[1-5]$/.test(e.key)) A.nav("act" + e.key);
    else if (e.key === "6") A.nav("e2e");
    else if (e.key === "7") A.nav("roles");
  });

  // ------------------------------------------------------------------------------------------------------------------- boot
  async function boot() {
    $("#btn-notes").addEventListener("click", () => setNotes(!document.body.classList.contains("notes-on")));
    $("#btn-preflight").addEventListener("click", () => runOp("preflight"));
    $("#btn-reset").addEventListener("click", () => runOp("restore"));
    try { setNotes(localStorage.getItem("abw.notes") === "1"); } catch (e) { /* ignore */ }
    try {
      A.catalog = await api("/api/catalog");
    } catch (e) {
      $("#page").replaceChildren(h("div", { class: "notice err" }, h("h4", null, "The console server is not answering"), h("p", null, e.message)));
      return;
    }
    const sub = "Demo console \u00b7 " + (A.catalog.tenantDomain || A.catalog.tenant) + " \u00b7 resource group " + A.catalog.resourceGroup;
    $("#brand-sub").textContent = sub;
    $("#brand-sub").title = sub;
    await A.loadHistory();
    A.strip.build(A.catalog);
    buildRail();
    A.persona.init();
    window.addEventListener("hashchange", render);
    window.addEventListener("resize", sizeStrip);
    if (typeof ResizeObserver !== "undefined" && $("#strip")) new ResizeObserver(sizeStrip).observe($("#strip"));
    render();
    A.refreshStatus(false);
    setInterval(() => A.refreshStatus(false), 15000);
  }
  boot();
})(window.ABW);
