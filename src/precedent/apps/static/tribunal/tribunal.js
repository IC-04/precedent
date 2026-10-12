// Verification screen. Renders the verifier's own event log (tribunal/events.jsonl):
// the pages Loki read, each proven field marked on the page, a linked list of conditions,
// and an escalation ladder that lights only as far as it had to go.
(() => {
  const page = document.querySelector(".verify-page");
  const run = page.dataset.run;
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const cap = (w) => (w ? w[0].toUpperCase() + w.slice(1) : w);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const MARK = { pass: "proven", fail: "contradicted", disputed: "disputed", unknown: "unproven" };
  const WORD = { pass: "Holds", fail: "Branch", disputed: "Possible branch", unknown: "Unconfirmed" };
  const LABEL = { proven: "holds", contradicted: "branch", disputed: "possible branch", unproven: "unconfirmed" };
  const VERDICT = { pass: "One timeline", fail: "Branched", disputed: "Possible branch", unknown: "Unconfirmed" };
  const HOW = { exact: "matched on the record", jury: "two model families agreed", arbiter: "settled by the senior model", process: "the write log shows no change", none: "nothing could settle it" };
  const RUNGS = ["rung-self", "rung-exact", "rung-models", "rung-senior", "rung-person"];

  let m, seen = 0, timers = [], polling = null, queue = [], draining = false, extra = {}, viewBefore = false;
  const PRISTINE = { rungs: $("rungs").innerHTML, summary: $("ladder-summary").textContent };

  function reset() {
    timers.forEach(clearTimeout); timers = [];
    queue = []; draining = false; seen = 0;
    m = { conds: [], exhibits: [], exact: {}, votes: {}, rulings: {}, checks: {}, plan: null, jurors: [], k: 3, shown: null, selected: null, arbiter: 0, verdict: null };
    ["conditions", "viewer-tabs", "viewer-marks", "audit-list", "unsupported"].forEach((id) => ($(id).textContent = ""));
    $("outcome").hidden = true;
    $("viewer-empty").hidden = false; $("viewer-page").hidden = true; $("viewer-doc").hidden = true;
    $("rungs").innerHTML = PRISTINE.rungs;
    $("ladder-summary").textContent = PRISTINE.summary;
    $("rungs").style.setProperty("--reach", "0%");
    hero("idle");
    pose("idle");
    drawStrand();
  }

  // ------------------------------------------------------------------ voice and hero
  function pose(name) {
    const loki = $("loki");
    loki.dataset.pose = "idle";
    void loki.getBoundingClientRect();
    loki.dataset.pose = name;
  }
  function say(text) { $("loki-says").textContent = text; }
  function hero(state, eyebrow) {
    $("hero").dataset.state = state;
    page.dataset.working = state === "working" ? "true" : "false";
    const titles = { idle: "Is this the real timeline?", working: "Checking the timeline", pass: "One timeline.", fail: "A branch has spawned.", disputed: "A possible branch.", unknown: "Unconfirmed." };
    $("hero-title").firstChild.textContent = titles[state];
    if (eyebrow) $("hero-eyebrow").textContent = eyebrow;
  }

  // ------------------------------------------------------------------ ladder
  function rung(id, state, detail) {
    $(id).dataset.state = state;
    if (detail) $(id).querySelector("[data-detail]").textContent = detail;
  }
  function ladder(final) {
    const n = m.conds.length;
    const exactPass = m.conds.filter((c) => (m.exact[c.id] || {}).result === "pass").length;
    const exactDone = Object.keys(m.exact).length;
    const ruled = Object.values(m.rulings);
    const byModels = ruled.filter((r) => r.basis === "jury").length;
    const voted = m.conds.filter((c) => (m.votes[c.id] || []).length).length;
    const disputedLeft = ruled.filter((r) => r.result === "disputed").length;
    const ava = extra.ava || {};
    const avaTotal = (ava.pass || 0) + (ava.fail || 0) + (ava.unknown || 0);
    rung("rung-self", "done", avaTotal ? `Ava's own re-read: ${ava.pass || 0} of ${avaTotal} passed${(extra.remanded || []).length ? ` · ${extra.remanded.length} branch sent back and pruned` : ""}` : "No self-check recorded");
    const planned = m.plan && !m.plan.error ? ` · ${m.plan.checks} checks planned by ${m.plan.model}` : "";
    if (exactDone) rung("rung-exact", final ? "done" : "active", `${exactPass} of ${n} proven by exact checks on fresh reads${planned}`);
    if (voted) rung("rung-models", final ? "done" : "active", `${voted} cross-checked · ${byModels} decided by agreement`);
    if (m.arbiter) rung("rung-senior", final ? "done" : "active", `Called for ${m.arbiter} disagreement${m.arbiter > 1 ? "s" : ""}`);
    if (!final) return;
    let settled = "rung-exact";
    if (byModels) settled = "rung-models";
    if (m.arbiter) settled = "rung-senior";
    if (!m.arbiter) rung("rung-senior", "skipped", "Not needed: no disagreement");
    if (disputedLeft) {
      rung("rung-person", "needed", `${disputedLeft} condition${disputedLeft > 1 ? "s" : ""} need your review`);
      settled = "rung-person";
    } else {
      rung("rung-person", "skipped", "Not needed");
      rung(settled, "settled", `${$(settled).querySelector("[data-detail]").textContent} · settled here`);
    }
    const reach = RUNGS.indexOf(settled) / (RUNGS.length - 1);
    $("rungs").style.setProperty("--reach", `calc(${reach * 100}% - ${reach * 14}px)`);
    const names = { "rung-exact": "the independent re-read", "rung-models": "two model families", "rung-senior": "the senior model", "rung-person": "a person" };
    $("ladder-summary").textContent = disputedLeft ? "Escalated to a person: a possible branch nothing else could settle." : `Settled by ${names[settled]}. No person needed.`;
  }

  // ------------------------------------------------------------------ the timeline strand
  const NS = "http://www.w3.org/2000/svg";
  function svg(tag, attrs, text) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
    if (text) node.textContent = text;
    return node;
  }
  function drawStrand(v) {
    const root = $("strand");
    const W = Math.max(Math.round(root.getBoundingClientRect().width) || 1000, 300);
    const Y = 84, n = Math.max(m.conds.length, 1);
    root.setAttribute("viewBox", `0 0 ${W} 120`);
    root.setAttribute("preserveAspectRatio", "xMidYMid meet");
    root.textContent = "";
    const x = (i) => 40 + ((W - 80) * (i + 0.5)) / n;
    const wave = `M0 ${Y} C ${W * 0.25} ${Y - 8}, ${W * 0.5} ${Y + 8}, ${W * 0.75} ${Y - 4} S ${W} ${Y + 2}, ${W} ${Y}`;
    root.append(svg("path", { class: "strand-glow", d: wave }), svg("path", { class: "strand-line", d: wave }));
    root.append(svg("circle", { class: "strand-pulse", r: 4, cx: 0, cy: Y }));
    const pruned = new Set(extra.remanded || []);
    m.conds.forEach((c, i) => {
      const r = m.rulings[c.id];
      const cx = x(i);
      const branch = (cls, label) => {
        const text = `${c.id} · ${label}`;
        const k = cx + 70 + text.length * 6 > W ? -1 : 1; // branch leftwards near the right edge
        const d = `M${cx} ${Y} C ${cx + 10 * k} ${Y - 24}, ${cx + 26 * k} ${Y - 46}, ${cx + 64 * k} ${Y - 58}`;
        root.append(svg("path", { class: `strand-branch ${cls}`, d }));
        root.append(svg("circle", { class: `strand-tip ${cls}`, cx: cx + 64 * k, cy: Y - 58, r: 3.5 }));
        root.append(svg("text", { class: `strand-label ${cls}`, x: cx + 70 * k, y: Y - 55, "text-anchor": k > 0 ? "start" : "end" }, text));
        if (cls === "pruned") root.append(svg("path", { class: "strand-cut", d: `M${cx + 27 * k - 5} ${Y - 46} l10 10 M${cx + 27 * k + 5} ${Y - 46} l-10 10` }));
      };
      if (pruned.has(c.id)) branch("pruned", "pruned");
      if (r && r.result === "fail") branch("spawned", c.added ? "missed" : "branch");
      else if (r && r.result === "disputed") branch("possible", "possible branch");
      const state = !r ? "" : r.result === "pass" ? "holds" : r.result === "fail" ? "branch" : r.result === "disputed" ? "possible" : "open";
      root.append(svg("circle", { class: `strand-node ${state}`, cx, cy: Y, r: 5 }));
    });
  }

  // ------------------------------------------------------------------ evidence viewer
  const CLAIM_FIELDS = {
    draft_saved: ["Status", "Email sent"],
    meeting_identity: ["Organizer ID", "Recipient ID", "Recipient email", "Topic"],
    meeting_times: ["Range start", "Range end", "Timezone", "Duration", "First option", "Second option"],
    meeting_grounding: ["Body", "Source paths"],
    meeting_no_duplicates: ["Draft ID"],
    meeting_availability: ["Coverage", "Coverage complete"],
    meeting_hold: ["Status", "Invitation sent", "Start", "End"],
  };
  function keysFor(cond, exhibit) {
    if (!exhibit.boxes) return [];
    const boxes = Object.keys(exhibit.boxes);
    const own = (m.checks[cond.id] || []).filter((c) => c.path === exhibit.path && c.label && boxes.includes(c.label)).map((c) => c.label);
    if (own.length) return [...new Set(own)];
    const claims = (cond.claims || []).flatMap((c) => CLAIM_FIELDS[c] || [c]);
    if (exhibit.path.startsWith("/books/vendors/")) return claims.includes("vendor_unchanged") ? boxes.filter((k) => !["Created", "Notes"].includes(k)) : [];
    const keys = claims.filter((c) => boxes.includes(c));
    if (claims.includes("bill_count") && boxes.includes("Invoice number")) keys.push("Invoice number");
    return [...new Set(keys)];
  }
  function exhibitFor(cond) {
    const checked = (m.checks[cond.id] || []).map((c) => m.exhibits.find((e) => e.path === c.path)).find(Boolean);
    if (checked) return checked;
    const withKeys = m.exhibits.find((e) => keysFor(cond, e).length);
    if (withKeys) return withKeys;
    if ((cond.claims || []).includes("latest_invoice")) return m.exhibits.find((e) => e.path.startsWith("/drive/")) || m.exhibits[0];
    return m.exhibits[0];
  }
  function statusOf(id) {
    if (m.rulings[id]) return MARK[m.rulings[id].result];
    if (m.exact[id]) return m.exact[id].result === "pass" ? "proven" : m.exact[id].result === "fail" ? "contradicted" : "pending";
    return "pending";
  }
  const RANK = { contradicted: 4, disputed: 3, unproven: 2, pending: 1, proven: 0 };

  function show(exhibit) {
    if (!exhibit) return;
    m.shown = exhibit.id;
    document.querySelectorAll(".viewer-tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.id === exhibit.id)));
    $("viewer-empty").hidden = true;
    if (exhibit.screenshot) {
      $("viewer-doc").hidden = true;
      $("viewer-page").hidden = false;
      const src = `/runs/${run}/tribunal/exhibits/${exhibit.screenshot}${viewBefore ? "?before=true" : ""}`;
      if ($("viewer-img").getAttribute("src") !== src) { $("viewer-img").src = src; $("viewer-img").alt = `Page Loki read: ${exhibit.title}`; }
    } else {
      $("viewer-page").hidden = true;
      $("viewer-doc").hidden = false;
      $("viewer-doc").textContent = exhibit.text;
    }
    $("viewer-foot").textContent = `${exhibit.title} · ${exhibit.path} · read ${exhibit.captured_at.replace("T", " ").replace("+00:00", " UTC")} · sha256 ${exhibit.sha256.slice(0, 16)}`;
    drawMarks();
  }

  function drawMarks() {
    const layer = $("viewer-marks");
    layer.textContent = "";
    const exhibit = m.exhibits.find((e) => e.id === m.shown);
    if (!exhibit || !exhibit.screenshot || !exhibit.size || !exhibit.size.length) return;
    const [W, H] = exhibit.size;
    const byKey = {};
    m.conds.forEach((cond) => keysFor(cond, exhibit).forEach((key) => {
      const status = statusOf(cond.id);
      const cur = byKey[key];
      if (!cur || RANK[status] > RANK[cur.status]) byKey[key] = { status, ids: [...(cur ? cur.ids : []), cond.id] };
      else cur.ids.push(cond.id);
    }));
    Object.entries(byKey).forEach(([key, info]) => {
      if (info.status === "pending") return;
      const [x, y, w, h] = exhibit.boxes[key];
      const mark = el("div", `mark ${info.status}${h > 60 ? " tall" : ""}`);
      mark.style.left = `${(x - 6) / W * 100}%`; mark.style.top = `${(y - 4) / H * 100}%`;
      mark.style.width = `${(w + 12) / W * 100}%`; mark.style.height = `${(h + 8) / H * 100}%`;
      const label = key === "approval_status" ? "Approval" : key;
      mark.append(el("span", "", `${label} · ${LABEL[info.status] || info.status}`));
      if (m.selected) mark.classList.add(info.ids.includes(m.selected) ? "focus" : "dim");
      mark.dataset.ids = info.ids.join(" ");
      layer.append(mark);
    });
  }

  function focusCondition(id, scroll) {
    m.selected = id;
    document.querySelectorAll(".condition-item").forEach((li) => li.classList.toggle("selected", li.dataset.id === id));
    const cond = m.conds.find((c) => c.id === id);
    if (cond) show(exhibitFor(cond));
    if (scroll) {
      const mark = document.querySelector(".mark.focus");
      if (mark) mark.scrollIntoView({ block: "center", behavior: "smooth", inline: "nearest" });
    }
  }

  // ------------------------------------------------------------------ conditions
  function conditionItem(c) {
    const li = el("li", "condition-item");
    li.dataset.id = c.id;
    li.tabIndex = 0;
    const body = el("div");
    const text = el("div", "condition-text", c.text);
    if (c.added) text.prepend(el("span", "tag-missed", c.origin === "demonstration" ? "From your demonstration" : "Missing from Ava's goal"));
    body.append(text, el("span", "condition-how", "Waiting to be checked"), el("ul", "court-checks"));
    const votes = el("div", "votes");
    m.jurors.forEach(() => { for (let s = 0; s < m.k; s++) votes.append(el("i", "vote")); });
    body.append(votes);
    const said = (extra.claims || {})[c.id];
    if (said) body.append(el("span", "condition-ava", `Ava reported: ${said}`));
    li.append(el("span", "status-icon"), body);
    const pick = () => focusCondition(c.id, true);
    li.addEventListener("click", pick);
    li.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(); } });
    return li;
  }
  function item(id) { return document.querySelector(`.condition-item[data-id="${CSS.escape(id)}"]`); }
  function how(id, html) {
    const node = item(id) && item(id).querySelector(".condition-how");
    if (!node) return;
    node.textContent = "";
    node.append(...html);
  }

  // ------------------------------------------------------------------ events
  function apply(e, quiet) {
    switch (e.event) {
      case "convened":
        hero("working", `Checking ${e.conditions} conditions at ${e.company}`);
        pose("think");
        say(`Holding Ava's account up against ${e.company}'s own records. All ${e.conditions} points must sit on the real timeline.`);
        break;
      case "adjourned":
        hero("unknown", "The Tribunal could not sit");
        pose("concern");
        say(`The Tribunal could not sit: ${e.reason}.`);
        showOutcome({ overall: "unknown", reason: e.reason });
        break;
      case "bench":
        m.jurors = e.jurors; m.k = e.samples;
        break;
      case "charge":
        m.conds.push(e);
        $("conditions").append(conditionItem(e));
        $("checklist-count").textContent = `${m.conds.length} points`;
        drawStrand();
        break;
      case "exhibit": {
        m.exhibits.push(e);
        const tab = el("button", "viewer-tab", e.title);
        tab.type = "button"; tab.dataset.id = e.id; tab.setAttribute("role", "tab");
        tab.append(el("small", "", e.kind === "record" ? "the work" : e.kind === "log" ? "write log" : "source"));
        tab.addEventListener("click", () => { m.selected = null; document.querySelectorAll(".condition-item").forEach((li) => li.classList.remove("selected")); show(e); });
        $("viewer-tabs").append(tab);
        if (m.exhibits.length === 1 || (!quiet && e.screenshot)) show(e);
        pose("inspect");
        say(`Reading ${e.title} myself. The record, not her memory of it.`);
        break;
      }
      case "audit": {
        const li = el("li", e.result === "fail" ? "fail" : "");
        li.append(el("span", "", e.rule), el("small", "", e.detail));
        $("audit-list").append(li);
        break;
      }
      case "plan": {
        m.plan = e;
        if (e.error) { say(`My own check plan failed (${e.error}); relying on the specialist checks.`); break; }
        rung("rung-exact", "active", `${e.model} planned ${e.checks} checks across ${e.pages.length} pages`);
        if (!quiet) { pose("think"); say(`I've planned ${e.checks} exact checks of my own across ${e.pages.length} pages${(e.missed || []).length ? `, and found ${e.missed.length} thing${e.missed.length > 1 ? "s" : ""} the request asked for that Ava's goal left out` : ""}.`); }
        break;
      }
      case "check": {
        (m.checks[e.condition_id] = m.checks[e.condition_id] || []).push(e);
        const node = item(e.condition_id);
        if (node) {
          const what = e.op === "field_equals" ? `${e.label} is ${e.value}` : e.op === "field_present" ? `${e.label} is filled` : e.op === "field_absent" ? `${e.label} is empty` : e.op === "row_count" ? `${e.value} matching row${e.value === "1" ? "" : "s"}` : e.op === "row_exists" ? "a matching row exists" : `contains "${(e.value || "").slice(0, 40)}"`;
          const li = el("li", `court-check ${e.result}`, `${what} · ${e.result === "pass" ? "holds" : e.result === "fail" ? "contradicted" : "not settled"}`);
          li.title = e.evidence;
          node.querySelector(".court-checks").append(li);
        }
        if (m.shown) drawMarks();
        break;
      }
      case "exact": {
        m.exact[e.condition_id] = e;
        const word = e.result === "pass" ? "Holds" : e.result === "fail" ? "Branch" : "Not settled by an exact check";
        how(e.condition_id, [el("b", "", word), document.createTextNode(e.result === "unknown" ? " · going to the models" : " · exact check")]);
        ladder(false);
        if (m.shown) drawMarks();
        if (!quiet) { pose("inspect"); say("Matching each claim to what the record shows. Nothing joins the timeline by default."); }
        break;
      }
      case "deliberating": {
        document.querySelectorAll(".condition-item.working").forEach((li) => li.classList.remove("working"));
        if (item(e.id)) item(e.id).classList.add("working");
        if (!quiet) {
          focusCondition(e.id, false);
          const cond = m.conds.find((c) => c.id === e.id);
          pose("think");
          say(`Two model families, asked separately: does this hold? ${cond ? cond.text : e.id}`);
        }
        break;
      }
      case "vote": {
        (m.votes[e.id] = m.votes[e.id] || []).push(e);
        const node = item(e.id);
        if (node) {
          const dots = node.querySelectorAll(".vote");
          const idx = m.jurors.findIndex((j) => j.name === e.juror) * m.k + (e.sample - 1);
          if (dots[idx]) { dots[idx].className = `vote ${e.ballot ? e.ballot.answer : ""}`; dots[idx].title = `${e.juror}: ${e.ballot ? e.ballot.answer.replaceAll("_", " ") : "no answer"}`; }
        }
        ladder(false);
        break;
      }
      case "arbiter_called":
        m.arbiter += 1;
        ladder(false);
        pose("wink");
        say(`The families disagree on ${e.id}. A senior model looks before anyone is disturbed.`);
        break;
      case "ruling": {
        m.rulings[e.id] = e;
        const node = item(e.id);
        if (node) {
          node.classList.remove("working");
          node.dataset.result = e.result;
          const tally = e.tally ? ` · ${e.tally.holds} of ${e.tally.holds + e.tally.does_not_hold + e.tally.cannot_tell} model votes agree` : "";
          how(e.id, [el("b", "", WORD[e.result]), document.createTextNode(` · ${HOW[e.basis] || ""}${e.basis === "jury" ? tally : ""}`)]);
        }
        if (m.shown) drawMarks();
        if (!quiet) { pose(e.result === "pass" ? "seal" : "concern"); say(e.result === "pass" ? `${e.id} holds. It's on the timeline.` : e.result === "fail" ? `${e.id} branched: ${e.reason.toLowerCase()}.` : `${e.id}: ${e.reason.toLowerCase()}.`); }
        drawStrand();
        break;
      }
      case "verdict":
        m.verdict = e;
        document.querySelectorAll(".condition-item.working").forEach((li) => li.classList.remove("working"));
        ladder(true);
        showOutcome(e);
        break;
    }
  }

  function showOutcome(v) {
    const box = $("outcome");
    box.hidden = false;
    box.dataset.result = v.overall;
    const titles = {
      pass: "One timeline. Everything Ava claimed happened, in the company's own records.",
      fail: "A branch has spawned. The records contradict what Ava claimed.",
      disputed: "A possible branch. The models could not agree, so a person decides.",
      unknown: "Unconfirmed. The records don't settle every point.",
    };
    $("outcome-title").textContent = v.reason ? `The Tribunal could not sit: ${v.reason}.` : titles[v.overall];
    const c = v.counts || {};
    $("outcome-note").textContent = v.counts
      ? `${c.pass} hold, ${c.fail} branched, ${c.disputed} possible, ${c.unknown} unconfirmed${(extra.remanded || []).length ? `, ${extra.remanded.length} pruned during the work` : ""}. ${m.exhibits.length} records read independently in ${v.seconds} s. The ground-truth grader is separate and never part of the Tribunal.`
      : "";
    $("w-ava").textContent = v.ava_claimed ? cap(v.ava_claimed) : "Nothing";
    $("w-loki").textContent = VERDICT[v.overall];
    const graded = extra.grade || v.grader;
    $("w-grader").textContent = graded ? cap(graded) : "Not run";
    const list = $("unsupported");
    list.textContent = "";
    if ((v.missed || []).length) {
      list.append(el("h3", "", "Missing from Ava's goal: the request asked for these"));
      const ul = el("ul");
      v.missed.forEach((x) => { const c = m.conds.find((k) => k.id === x.id); ul.append(el("li", "", `${c ? c.text : x.id} · ${WORD[x.ruling] || x.ruling}`)); });
      list.append(ul);
    }
    const groups = [
      ["fail", "Branches: things Ava reported that the records contradict"],
      ["disputed", "Possible branches: the models disagree"],
      ["unknown", "Unconfirmed: things Ava reported that the records can't settle"],
    ];
    groups.forEach(([ruling, heading]) => {
      const items = (v.unsupported_claims || []).filter((u) => u.ruling === ruling);
      if (!items.length) return;
      list.append(el("h3", "", heading));
      const ul = el("ul");
      items.forEach((u) => ul.append(el("li", "", `${u.id}: ${u.claimed || ""}`)));
      list.append(ul);
    });
    if (v.reason) return;
    const prunedCount = (extra.remanded || []).length;
    hero(v.overall, v.overall === "pass" ? `The Tribunal · ${m.exhibits.length} records read · ${prunedCount ? plural(prunedCount, "branch", "branches") + " pruned" : "no branches"}` : `The Tribunal · ${plural((v.counts || {}).fail || 0, "branch", "branches")} caught`);
    drawStrand(v);
    const pruned = (extra.remanded || []).length;
    const contradicted = (v.unsupported_claims || []).filter((u) => u.ruling === "fail").length;
    const unconfirmed = (v.unsupported_claims || []).length - contradicted;
    if (v.overclaimed && contradicted) { pose("wink"); say(`Ava's account spawned ${contradicted} branch${contradicted > 1 ? "es" : ""}: things she reported that the records contradict. They're listed below.`); }
    else if (v.overclaimed && unconfirmed) { pose("concern"); say(`Ava reported ${unconfirmed} thing${unconfirmed > 1 ? "s" : ""} I couldn't confirm from the records. Not contradicted, but not proven either, so I won't merge them into the timeline.`); }
    else if (v.overall === "pass" && pruned) { pose("pleased"); say(`${pruned} branch(es) spawned during the work. I sent them back and Ava pruned them. One timeline remains.`); }
    else if (v.overall === "pass") { pose("pleased"); say("One timeline. Nothing Ava claimed spawned a branch, and nobody needed to be asked."); }
    else if (v.overall === "disputed") { pose("concern"); say("A possible branch I can't settle alone. It's waiting for you."); }
    else { pose("concern"); say("Some points stay unconfirmed. I won't merge them into the timeline."); }
    // Open on the work itself (a record), else the first page with a picture.
    if (!m.selected && m.exhibits.length) show(m.exhibits.find((e) => e.kind === "record") || m.exhibits.find((e) => e.screenshot) || m.exhibits[0]);
  }

  // ------------------------------------------------------------------ pacing and data
  const PAUSE = { ruling: 520, verdict: 700, exhibit: 380, exact: 120, deliberating: 420, charge: 70, vote: 55 };
  function enqueue(events) { queue.push(...events); if (!draining) drain(); }
  function drain() {
    if (!queue.length) { draining = false; return; }
    draining = true;
    const e = queue.shift();
    apply(e, false);
    timers.push(setTimeout(drain, PAUSE[e.event] || 140));
  }
  async function fetchState() {
    const response = await fetch(`/runs/${run}/tribunal/state${viewBefore ? "?before=true" : ""}`, { cache: "no-store" });
    if (!response.ok) throw new Error(String(response.status));
    const s = await response.json();
    // As caught, nothing has been pruned yet: show the branches as they first appeared.
    extra = { ava: s.ava, remanded: viewBefore ? [] : s.remanded, grade: s.grade, claims: s.claims };
    $("timeline-switch").hidden = !s.has_before;
    return s;
  }
  async function poll() {
    try {
      const s = await fetchState();
      if (s.events.length < seen) { reset(); return; }
      const fresh = s.events.slice(seen);
      seen = s.events.length;
      if (fresh.length) enqueue(fresh);
      if (!s.hearing) { clearInterval(polling); polling = null; controls(true); }
    } catch (_) { /* the next poll retries */ }
  }
  function live() {
    reset();
    controls(false);
    hero("working", "The Tribunal · checking now");
    say("Checking now. Everything below arrives as it happens.");
    polling = setInterval(poll, 700);
    poll();
  }
  function controls(ready) {
    const done = page.dataset.finished === "true";
    $("convene").disabled = !ready || !done;
    $("convene").textContent = !ready ? "Checking" : seen ? "Check again" : "Check the timeline";
    $("replay").hidden = !ready || !seen;
    document.querySelector(".speed").hidden = !ready || !seen;
  }
  function replay(events) {
    reset();
    hero("working", "The Tribunal · replay");
    const speed = Number($("speed").value) || 2;
    let clock = 0, last = 0;
    events.forEach((e) => {
      const gap = Math.min(Math.max((e.t - last) * 1000, 40), 2200) / speed;
      last = e.t;
      clock += gap + (PAUSE[e.event] || 0) / Math.max(speed / 2, 1);
      timers.push(setTimeout(() => apply(e, false), clock));
    });
    seen = events.length;
  }

  $("convene").addEventListener("click", async () => {
    $("convene").disabled = true;
    const response = await fetch(`/runs/${run}/tribunal`, { method: "POST" });
    if (response.ok) live();
    else { $("convene").disabled = false; say((await response.json().catch(() => ({}))).detail || "The Tribunal could not sit."); }
  });
  window.addEventListener("resize", () => drawStrand());
  document.querySelectorAll("#timeline-switch button").forEach((b) => b.addEventListener("click", async () => {
    viewBefore = b.dataset.before === "true";
    document.querySelectorAll("#timeline-switch button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    const s = await fetchState();
    reset();
    s.events.forEach((e) => apply(e, true));
    seen = s.events.length;
    controls(true);
    if (viewBefore) say("This is the timeline as I first found it, before Ava was asked to look again.");
  }));
  $("replay").addEventListener("click", async () => { const s = await fetchState(); replay(s.events); });

  (async () => {
    reset();
    try {
      const s = await fetchState();
      if (s.hearing) return live();
      if (s.events.length) { s.events.forEach((e) => apply(e, true)); seen = s.events.length; }
    } catch (_) { /* nothing verified yet */ }
    controls(true);
  })();
})();
