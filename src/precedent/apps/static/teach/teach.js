// Teach Ava, watch page: Ava's notes arrive one by one as she watches the recording.
(() => {
  const page = document.querySelector(".watch-page");
  const demo = page.dataset.demo;
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const video = $("video");
  const taker = document.querySelector(".note-taker .ava");
  let seen = 0, queue = [], draining = false, steps = [], finished = false;

  const pose = (name) => { if (taker) taker.dataset.pose = name; };
  const seconds = (t) => {
    const m = /^(?:(\d+):)?(\d{1,2}):(\d{2})/.exec(t || "");
    return m ? (+(m[1] || 0)) * 3600 + (+m[2]) * 60 + (+m[3]) : null;
  };
  const QUESTION = new Set(["label_missing", "page_missing", "unknown_page"]);

  function sentence(s) {
    const b = (text) => { const x = el("b", "", text); return x; };
    const span = el("span", "note-text");
    const add = (...parts) => parts.forEach((p) => span.append(typeof p === "string" ? document.createTextNode(p) : p));
    const target = s.target || "the page";
    switch (s.action) {
      case "type": add("Typed ", b(s.value || "a value"), " into ", b(target)); break;
      case "select": add("Chose ", b(s.value || "an option"), " for ", b(target)); break;
      case "click": add("Clicked ", b(target)); break;
      case "navigate": add("Opened ", b(s.path || target)); break;
      case "read": add("Read ", b(target)); break;
      case "upload": add("Attached ", b(s.value || target)); break;
      case "check": add("Checked ", b(target)); break;
      default: add(`${s.action} `, b(target));
    }
    if (s.on_screen) add(" from ", s.on_screen);
    return span;
  }

  function addNote(s) {
    if (!steps.length) $("notes").textContent = "";
    steps.push(s);
    const li = el("li", "lesson-note");
    li.dataset.n = s.n;
    li.append(el("time", "", (s.t || `#${s.n}`).replace(/\.\d+$/, "")));
    const body = el("div");
    body.append(sentence(s));
    if (s.reason) body.append(el("span", "note-why", s.reason));
    const g = s.grounding || {};
    if (g.status === "grounded" || g.status === "page_found") body.append(el("span", "note-check", `Confirmed in the apps · ${g.path || ""}`));
    else if (QUESTION.has(g.status)) body.append(el("span", "note-check question", "Not found in the real apps · Ava will ask you"));
    li.append(body);
    if (s.frame) {
      const img = el("img");
      img.alt = `Frame at ${s.t}`;
      img.loading = "lazy";
      img.src = `/teach/${demo}/frames/${s.frame}`;
      li.append(img);
    }
    li.addEventListener("click", () => { const at = seconds(s.t); if (video && at !== null) { video.currentTime = at; video.play().catch(() => {}); } });
    $("notes").append(li);
    li.scrollIntoView({ block: "nearest", behavior: "smooth" });
    $("note-count").textContent = `${steps.length} step${steps.length === 1 ? "" : "s"}`;
    mark(s);
  }

  function mark(s) {
    const at = seconds(s.t);
    if (!video || at === null || !video.duration) return;
    const m = el("span", `scrub-mark ${QUESTION.has((s.grounding || {}).status) ? "question" : (s.grounding || {}).status === "grounded" ? "grounded" : ""}`);
    m.style.left = `${Math.min(99, (at / video.duration) * 100)}%`;
    m.dataset.n = s.n;
    m.title = `${s.t} · ${s.action} ${s.target || ""}`;
    m.addEventListener("click", () => { video.currentTime = at; });
    $("scrubber").append(m);
  }

  function learned(d, skill) {
    $("learned-empty").hidden = true;
    $("learned").hidden = false;
    $("l-description").textContent = d.description;
    const fill = (id, items, render) => { const ul = $(id); ul.textContent = ""; items.forEach((x) => ul.append(render(x))); };
    fill("l-parameters", d.parameters, (p) => { const li = el("li"); li.append(el("strong", "", p.name.replaceAll("_", " ")), el("span", "", `from ${p.source}`)); li.title = p.example ? `In the lesson: ${p.example}` : p.description; return li; });
    fill("l-rules", d.rules, (r) => el("li", "", r.why ? `${r.rule} (${r.why})` : r.rule));
    fill("l-done", d.done_when, (x) => el("li", "", x));
    fill("l-stop", d.stop_and_ask, (x) => el("li", "", x));
    const unconfirmed = steps.filter((s) => QUESTION.has((s.grounding || {}).status)).map((s) => `At ${(s.t || "").replace(/\.\d+$/, "")}, "${s.target}" wasn't found in the real apps. What did you click there?`);
    const questions = [...d.questions, ...unconfirmed];
    fill("l-questions", questions, (x) => el("li", "", x));
    $("l-questions-wrap").hidden = !questions.length;
    if (!$("l-trial").value) $("l-trial").value = d.trial_request;
    if (skill) $("l-skill").textContent = skill;
  }

  function apply(n) {
    if (n.event === "status") {
      $("watch-status").textContent = n.text;
      $("watch-status").classList.toggle("live", !n.done);
      $("taker-line").textContent = n.done ? "Done" : n.text.startsWith("Turning") ? "Thinking it through" : "Taking notes";
      pose(n.done ? "deliver" : n.text.startsWith("Turning") ? "think" : "read");
    } else if (n.event === "step") {
      addNote(n);
    } else if (n.event === "draft") {
      learned(n, null);
    } else if (n.event === "error") {
      $("watch-status").textContent = `Ava couldn't learn from this: ${n.text}`;
      $("watch-status").classList.remove("live");
      pose("ask");
      $("taker-line").textContent = "Needs help";
    }
  }

  function enqueue(items) { queue.push(...items); if (!draining) drain(); }
  function drain() {
    if (!queue.length) { draining = false; return; }
    draining = true;
    const n = queue.shift();
    apply(n);
    setTimeout(drain, n.event === "step" ? 260 : 120);
  }

  async function poll() {
    try {
      const r = await fetch(`/teach/${demo}/state`, { cache: "no-store" });
      if (!r.ok) return;
      const s = await r.json();
      const fresh = s.notes.slice(seen);
      seen = s.notes.length;
      enqueue(fresh);
      const status = s.meta.status;
      if (["ready", "failed", "saved"].includes(status)) {
        finished = true;
        if (s.skill_md) setTimeout(() => { $("l-skill").textContent = s.skill_md; }, 400);
        $("save-form").hidden = status !== "ready";
        if (status === "saved") {
          const a = el("a", "button secondary", "Open the skill in Ava’s mind");
          a.href = `/mind?tab=skills&entry=${s.meta.skill_id}`;
          document.querySelector(".watch-heading").append(a);
        }
      }
    } catch (_) { /* the next poll retries */ }
    if (!finished) setTimeout(poll, 900);
  }

  if (video) {
    video.addEventListener("loadedmetadata", () => { $("scrubber").textContent = ""; steps.forEach(mark); });
    video.addEventListener("timeupdate", () => {
      const now = video.currentTime;
      let current = null;
      steps.forEach((s) => { const at = seconds(s.t); if (at !== null && at <= now + 0.25) current = s.n; });
      document.querySelectorAll(".lesson-note.current, .scrub-mark.current").forEach((x) => x.classList.remove("current"));
      if (current !== null) document.querySelectorAll(`[data-n="${current}"]`).forEach((x) => x.classList.add("current"));
    });
  }
  pose("read");
  poll();
})();
