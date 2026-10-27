"use strict";
/* The architecture strip (lights up as a job runs) and the "Prove it's real" drawer. */
(function (A) {
  const { h, $, api, md, toast, copy } = A;

  const PROBE_TITLES = {
    foundry: "Foundry account", guardrail: "Guardrails", apim: "API Management gateway", mcp: "MCP servers", data: "Data plane (keys off)", worm: "WORM audit store",
    monitor: "Monitoring workspace", sentinel: "Microsoft Sentinel", policy: "Azure Policy initiative", defender: "Defender for Cloud", licenses: "Licences", entra: "Entra ID",
    ca: "Conditional Access", apic: "API Center", agentid: "Entra Agent ID", agent365: "Agent 365",     purview: "Purview", controlplane: "Foundry Control Plane", legacy: "Legacy PoC (shared key)",
  };
  A.probeTitle = (id) => PROBE_TITLES[id] || id;

  const COLS = ["You", "AI gateway", "Agent", "Tools (MCP)", "Data"];
  const WALL_OF = { guardrail: 0, apim: 1, "m-research": 2, "m-wall": 2, "m-actions": 2, "m-private": 2, "m-vendor": 2, data: 3 };

  // ------------------------------------------------------------------------------------------------ strip
  const strip = {
    nodes: new Map(),
    build(cat) {
      const root = $("#strip");
      const mk = (id) => {
        const n = cat.nodes[id];
        if (!n) return null;
        const w = WALL_OF[id];
        const el = h("button", { class: "node" + (w != null ? " w" + w : "") + (id === "m-legacy" ? " legacy" : ""), title: n.plain, "data-node": id, onclick: () => drawer.open(id) },
          h("span", { class: "n-short" }, n.short || n.title), h("span", { class: "n-sub" }, n.sub || ""));
        strip.nodes.set(id, el);
        return el;
      };
      const flow = h("div", { class: "flow" }, cat.strip.path.map((col, i) =>
        h("div", { class: "col" }, h("div", { class: "col-title" }, COLS[i] || ""), h("div", { class: "col-nodes" + (col.length > 3 ? " grid" : "") }, col.map(mk)))));
      const watch = h("div", { class: "watch" }, h("span", { class: "label" }, "Watching and\u00a0governing"), cat.strip.watch.map(mk));
      const legend = h("div", { class: "legend" },
        h("span", null, h("i", { style: { background: "var(--green)" } }), "allowed"),
        h("span", null, h("i", { style: { background: "var(--red)" } }), "refused"),
        h("span", null, h("i", { style: { background: "var(--amber)" } }), "warning"),
        h("span", null, h("i", { style: { background: "var(--w0)" } }), "W0 ", h("i", { style: { background: "var(--w1)" } }), "W1 ", h("i", { style: { background: "var(--w2)" } }), "W2 ", h("i", { style: { background: "var(--w3)" } }), "W3 walls"));
      root.replaceChildren(h("div", { class: "strip-head" }, h("span", { class: "t" }, "How a request travels \u2014 click any box to open the real service"), cat.strip.caption ? h("span", { class: "cap" }, cat.strip.caption) : null, legend), flow, watch);
    },
    show(on) { $("#strip").classList.toggle("hidden", !on); },
    clear() { for (const el of strip.nodes.values()) el.classList.remove("lit-ok", "lit-deny", "lit-warn"); },
    apply(lights) {
      for (const [id, v] of Object.entries(lights || {})) {
        const el = strip.nodes.get(id);
        if (!el) continue;
        el.classList.remove("lit-ok", "lit-deny", "lit-warn");
        el.classList.add(v === "deny" ? "lit-deny" : v === "warn" ? "lit-warn" : "lit-ok");
      }
    },
    pulse(ids) { strip.clear(); strip.apply(Object.fromEntries((ids || []).map((i) => [i, "ok"]))); },
  };

  // ---------------------------------------------------------------------------------------------- policy viewer
  const HOT = [
    [/<validate-jwt/, "token check"], [/abw-deny-oids/, "kill switch"], [/abw-allowed-azp/, "client allow-list"], [/rate-limit-by-key/, "rate limit"],
    [/missing_role|required\.Contains/, "role check"], [/emit-metric/, "telemetry"], [/abw-vendor-key/, "vendor key (Key Vault)"], [/Ocp-Apim-Subscription-Key|subscriptionKeyParameterNames/i, "shared key"],
  ];
  function xmlLine(line, st) {
    const out = [];
    let rest = line;
    if (st.inComment) {
      const end = rest.indexOf("-->");
      if (end === -1) return [h("span", { class: "c" }, rest)];
      out.push(h("span", { class: "c" }, rest.slice(0, end + 3)));
      rest = rest.slice(end + 3);
      st.inComment = false;
    }
    const re = /(<!--)|(<\/?[A-Za-z][\w:-]*)|(\/?>)|([\w:-]+)(?==)|("[^"]*")/g;
    let last = 0, m;
    while ((m = re.exec(rest))) {
      if (m.index > last) out.push(rest.slice(last, m.index));
      if (m[1]) {
        const end = rest.indexOf("-->", m.index);
        if (end === -1) { out.push(h("span", { class: "c" }, rest.slice(m.index))); st.inComment = true; last = rest.length; break; }
        out.push(h("span", { class: "c" }, rest.slice(m.index, end + 3)));
        last = end + 3;
        re.lastIndex = last;
        continue;
      }
      if (m[2] || m[3]) out.push(h("span", { class: "t" }, m[0]));
      else if (m[4]) out.push(h("span", { class: "a" }, m[0]));
      else out.push(m[0]);
      last = m.index + m[0].length;
    }
    if (last < rest.length) out.push(rest.slice(last));
    return out;
  }
  // The policy section of the drawer. It shows the policy API Management is enforcing right now (read through ARM on every
  // click). The repo template is shown only when asked for, and is labelled as not read from Azure.
  const SERVER_LABEL = { wall: "Wall", research: "Research", actions: "Trading actions", vendor: "Market data vendor", legacy: "Legacy PoC (shared key)" };
  const TEMPLATE_OF = (server) => (server === "legacy" ? "mcp-legacy" : "mcp-jwt");

  function paint(pre, text) {
    const st = { inComment: false };
    const jumps = new Map();
    pre.className = "xml";
    pre.replaceChildren(...text.split(/\r?\n/).map((line) => {
      const comment = st.inComment || /^\s*<!--/.test(line);
      const hot = comment ? null : HOT.find(([re]) => re.test(line));
      const span = h("span", { class: "ln" + (hot ? " hot" : "") }, xmlLine(line, st), hot ? h("span", { class: "tag" }, hot[1]) : null, "\n");
      if (hot && !jumps.has(hot[1])) jumps.set(hot[1], span);
      return span;
    }));
    return jumps;
  }
  function flash(el) {
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("flash");
    setTimeout(() => el.classList.remove("flash"), 1800);
  }
  const factRow = (k, v) => h("tr", null, h("td", null, k), h("td", null, v));
  // {server} becomes the live API title; {governed}...{/governed} is kept only when the policy really has the token check
  const whereFor = (where, g) => where.replace(/\{governed\}([\s\S]*?)\{\/governed\}/g, g.hasJwt ? "$1" : "").split("{server}").join(g.title);

  function policyViewer(servers, where) {
    let current = servers[0];
    let text = "";
    let seq = 0;
    const tabs = servers.length > 1 ? h("div", { class: "pol-tabs" }) : null;
    const meta = h("div", { class: "pol-meta" });
    const jump = h("div", { class: "pol-jump" });
    const pre = h("pre", { class: "xml skeleton" }, "Reading the policy from API Management\u2026");
    const root = h("div", { class: "pol" }, tabs, meta, jump, pre);
    const drawTabs = () => tabs && tabs.replaceChildren(...servers.map((s) => h("button", { class: "btn tiny" + (s === current ? " sel" : ""), onclick: () => show(s) }, SERVER_LABEL[s] || s)));

    async function template(server) {
      const mine = ++seq;
      const name = TEMPLATE_OF(server);
      try {
        const r = await fetch("/api/policy/" + name, { cache: "no-store" });
        if (!r.ok) throw new Error("The template file was not found.");
        const t = await r.text();
        if (mine !== seq) return;
        text = t;
        const jumps = paint(pre, t);
        meta.replaceChildren(h("div", { class: "notice fail" },
          h("h4", null, "TEMPLATE \u2014 not read from Azure"),
          h("p", null, "This is infra\\apim\\policies\\" + name + ".policy.xml from the repo, not what API Management holds." + (name === "mcp-jwt" ? " Bicep fills in the __SERVER__, __AUDIENCE__ and __ROLES_CS__ placeholders for each server when it deploys." : "")),
          h("button", { class: "btn tiny", style: { marginTop: "8px" }, onclick: () => show(server) }, "Read the live policy from Azure")));
        jump.replaceChildren(...[...jumps].map(([label, el]) => h("button", { class: "chip", onclick: () => flash(el) }, label)));
      } catch (e) {
        if (mine === seq) pre.textContent = e.message;
      }
    }

    async function show(server) {
      current = server;
      drawTabs();
      const mine = ++seq;
      text = "";
      jump.replaceChildren();
      meta.replaceChildren(h("div", { class: "skeleton" }, "Reading from API Management\u2026"));
      pre.className = "xml skeleton";
      pre.textContent = "Reading the policy from API Management\u2026";
      try {
        const g = await api("/api/gateway-policy/" + server);
        if (mine !== seq) return;
        text = g.xml;
        const jumps = paint(pre, g.xml);
        const jwt = g.hasJwt ? "validate-jwt on \u2014 audience " + g.audience : "none \u2014 this policy has no validate-jwt";
        meta.replaceChildren(
          h("div", { class: "pol-line" }, h("strong", null, "Read live from API Management"), " at " + g.asOf + " \u00b7 API ", h("code", null, g.apiName), " \u00b7 " + g.lines + " lines ",
            h("button", { class: "btn tiny", onclick: () => show(server) }, "Re-read"), h("button", { class: "btn tiny", onclick: () => copy(text, "Policy copied") }, "Copy")),
          h("table", { class: "facts" },
            factRow("Token check", jwt),
            g.hasJwt ? factRow("Roles that may call", g.roles.join(", ") + (g.discoveryOpen ? " \u2014 tool discovery stays open" : " \u2014 including discovery")) : null,
            factRow("Rate limit", g.rate || "none"),
            factRow("Subscription key", g.subscriptionRequired ? "required (the shared key)" : "not required \u2014 the Entra token is the only credential"),
            g.vendorKey ? factRow("Vendor key", "attached here from a Key Vault-backed named value; the caller never sees it") : null),
          where ? h("div", { class: "pol-where" }, h("b", null, "In the portal: "), A.inline(whereFor(where, g))) : null);
        jump.replaceChildren(h("span", { class: "label" }, "Jump to"), ...[...jumps].map(([label, el]) => h("button", { class: "chip", onclick: () => flash(el) }, label)));
      } catch (e) {
        if (mine !== seq) return;
        const stale = e.status === 404 && !e.data; // a console started before this feature answers 404 with plain text, not our JSON
        pre.className = "xml";
        pre.textContent = "";
        meta.replaceChildren(h("div", { class: "notice err" },
          h("h4", null, stale ? "This console window is an older version" : "Could not read the policy from Azure"),
          h("p", null, stale ? "Close it and start Start-Console.bat again to read the live policy." : e.message),
          h("div", { class: "pol-fix" },
            h("button", { class: "btn tiny", onclick: () => show(server) }, "Try again"),
            h("button", { class: "btn tiny", onclick: () => template(server) }, "Show the repo template instead (not read from Azure)"))));
      }
    }

    show(current);
    return root;
  }

  // ------------------------------------------------------------------------------------------------- drawer
  const drawer = {
    current: null,
    open(id) {
      const n = A.catalog.nodes[id];
      if (!n) return;
      drawer.current = id;
      const el = $("#drawer");
      const probeHost = h("div", null, h("div", { class: "skeleton" }, "Reading the live state from Azure\u2026"));
      const load = (force) => {
        if (!n.probe) { probeHost.replaceChildren(h("div", { class: "callout" }, "No live check for this one \u2014 use the links below.")); return; }
        probeHost.replaceChildren(h("div", { class: "skeleton" }, "Reading the live state from Azure\u2026"));
        api("/api/probe/" + n.probe + (force ? "?force=1" : "")).then((p) => {
          if (drawer.current !== id) return;
          probeHost.replaceChildren(A.probeCard(p, A.probeTitle(n.probe)));
        }).catch((e) => probeHost.replaceChildren(h("div", { class: "notice err" }, e.message)));
      };
      const links = (n.links || []).map((l) => h("div", { class: "dr-link" },
        h("div", { class: "lt" }, l.label, !l.verified ? h("span", { class: "badge" }, "bookmark in dry run") : null, l.path ? h("span", { class: "path" }, l.path) : null),
        h("a", { class: "btn tiny", href: l.url, target: "_blank", rel: "noopener" }, "Open \u2197")));
      el.replaceChildren(...[
        h("div", { class: "dr-head" }, h("h2", null, n.title), h("button", { class: "btn tiny", onclick: drawer.close }, "Close \u2715")),
        h("div", { class: "dr-plain" }, n.plain),
        h("div", { class: "dr-sec" }, h("h4", null, "Live from Azure right now ", h("button", { class: "btn tiny", style: { marginLeft: "8px" }, onclick: () => load(true) }, "Refresh")), probeHost),
        links.length ? h("div", { class: "dr-sec" }, h("h4", null, "Open the real thing"), links) : null,
        (n.point || []).length ? h("div", { class: "dr-sec" }, h("h4", null, "What to point at"), h("ul", { class: "point" }, n.point.map((p) => h("li", null, A.inline(p))))) : null,
        n.policyServers ? h("div", { class: "dr-sec" }, h("h4", null, "The policy the gateway is enforcing \u2014 read live"), policyViewer(n.policyServers, n.policyWhere)) : null,
      ].filter(Boolean));
      el.classList.remove("closed");
      el.scrollTop = 0;
      load(false);
      for (const [nid, b] of strip.nodes) b.style.outline = nid === id ? "2px solid var(--blue)" : "";
    },
    close() {
      $("#drawer").classList.add("closed");
      drawer.current = null;
      for (const b of strip.nodes.values()) b.style.outline = "";
    },
  };

  Object.assign(A, { strip, drawer });
})(window.ABW);
