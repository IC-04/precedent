// Worker pointer, Ava's companion and captions. Only the executor calls move/clicked
// and only trusted runner callbacks call show/say; native human pointer and focus
// events are not listeners and cannot drive Ava. The host is aria-hidden with a
// closed shadow root and no pointer events, so page snapshots and clicks ignore it.
// AVA_ART is replaced by screen.py with the shared drawing (apps/static/ava).
(() => {
  if (window.__ava && window.__ava.show) return;
  const ART = /*AVA_ART*/ null;
  const KEY = "__ava_overlay";
  const POSES = ["idle", "read", "think", "work", "check", "ask", "listen", "deliver", "away"];
  const STATUS = { idle: "Ready", read: "Reading", think: "Choosing the next step", work: "Working",
    check: "Verifying", ask: "Needs your input", listen: "Reading your answer", deliver: "Verified result", away: "Stopped" };
  let caption = "", pose = "read", seq = 0;
  let point = { x: 35, y: 80 };
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) || "{}");
    caption = saved.caption || ""; point = saved.point || point;
    pose = POSES.includes(saved.pose) ? saved.pose : pose; seq = saved.seq || 0;
  } catch {}
  function remember() {
    try { sessionStorage.setItem(KEY, JSON.stringify({ caption, point, pose, seq })); } catch {}
  }
  function mount() {
    if (document.getElementById("__ava_host")) return;
    const host = document.createElement("div");
    host.id = "__ava_host";
    host.setAttribute("aria-hidden", "true");
    host.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483647;view-transition-name:none";
    const root = host.attachShadow({ mode: "closed" });
    const markup = `
      <style>
        ${ART ? ART.css : ""}
        .companion{position:fixed;left:14px;bottom:10px;display:flex;align-items:flex-end;gap:8px;max-width:min(520px,70vw)}
        .companion .ava{width:74px;flex:none;filter:drop-shadow(0 3px 6px #2a1d3322)}
        .bubble{margin-bottom:16px;font:500 13px/1.35 system-ui,sans-serif;color:#2f2536;background:rgba(255,253,250,.96);
          border:1px solid #d8cce2;border-radius:12px 12px 12px 3px;padding:8px 12px;box-shadow:0 6px 20px #2a1d3320;opacity:0;transition:opacity .2s}
        .bubble small{display:block;font:600 10px/1.3 system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#7d5f8f;margin-bottom:2px}
        .pointer{position:fixed;left:0;top:0;width:22px;height:22px;filter:drop-shadow(0 2px 2px #0005)}
        .tag{position:absolute;left:17px;top:18px;padding:3px 7px;background:#4338ca;color:white;
          border-radius:8px;font:600 11px/1 system-ui}
        .click{position:fixed;width:30px;height:30px;margin:-15px;border:2px solid #4338ca;
          border-radius:50%;opacity:0}
        .click.on{animation:pulse .6s ease-out}
        @media(prefers-reduced-motion:reduce){.click.on{animation:none}}
        @keyframes pulse{from{opacity:1;transform:scale(.4)}to{opacity:0;transform:scale(1.4)}}
      </style>
      <div class="click"></div>
      <div class="pointer"><svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2 L3 18 L7.5 14 L10.5 20.5 L13 19.4 L10 13 L16 13 Z" fill="#4338ca" stroke="white" stroke-width="1.4"/></svg><span class="tag">Ava</span></div>
      <div class="companion">${ART ? `<div class="ava ava-motion" data-pose="read">${ART.svg}</div>` : ""}<div class="bubble"><small></small><span></span></div></div>`;
    // Pages that enforce Trusted Types (Gmail, Calendar) refuse raw innerHTML. Try a named
    // policy; if the page forbids that too, build the pointer and caption with DOM calls and
    // leave the drawing out. Decoration must never stop Ava's work.
    try {
      const policy = window.trustedTypes && window.trustedTypes.createPolicy
        ? window.trustedTypes.createPolicy("ava-overlay-" + Math.random().toString(36).slice(2), { createHTML: (v) => v })
        : null;
      root.innerHTML = policy ? policy.createHTML(markup) : markup;
    } catch {
      const css = markup.slice(markup.indexOf("<style>") + 7, markup.indexOf("</style>"));
      try { const sheet = new CSSStyleSheet(); sheet.replaceSync(css); root.adoptedStyleSheets = [sheet]; } catch {}
      const make = (tag, cls, ns) => { const n = ns ? document.createElementNS(ns, tag) : document.createElement(tag); if (cls) n.setAttribute("class", cls); return n; };
      const SVG = "http://www.w3.org/2000/svg";
      const svg = make("svg", "", SVG); svg.setAttribute("width", "22"); svg.setAttribute("height", "22"); svg.setAttribute("viewBox", "0 0 22 22");
      const path = make("path", "", SVG);
      for (const [k, v] of [["d", "M3 2 L3 18 L7.5 14 L10.5 20.5 L13 19.4 L10 13 L16 13 Z"], ["fill", "#4338ca"], ["stroke", "white"], ["stroke-width", "1.4"]]) path.setAttribute(k, v);
      svg.append(path);
      const tag = make("span", "tag"); tag.textContent = "Ava";
      const pointerNode = make("div", "pointer"); pointerNode.append(svg, tag);
      const bubbleNode = make("div", "bubble"); bubbleNode.append(make("small"), make("span"));
      const companion = make("div", "companion"); companion.append(bubbleNode);
      root.append(make("div", "click"), pointerNode, companion);
    }
    (document.body || document.documentElement).appendChild(host);
    const bubble = root.querySelector(".bubble"), text = bubble.querySelector("span"), state = bubble.querySelector("small");
    const figure = root.querySelector(".ava");
    const pointer = root.querySelector(".pointer"), click = root.querySelector(".click");
    function paint() {
      text.textContent = caption; state.textContent = STATUS[pose] || "";
      bubble.style.opacity = caption ? "1" : "0";
      if (figure) figure.dataset.pose = pose;
      host.dataset.pose = pose;
    }
    window.__ava = {
      say(value) { caption = value || ""; remember(); paint(); },
      // A newer trusted state always wins; an older one arriving late is ignored.
      show(value) {
        if (!value || (value.seq && value.seq < seq)) return;
        if (value.seq) seq = value.seq;
        if (POSES.includes(value.pose)) pose = value.pose;
        if (typeof value.text === "string") caption = value.text;
        remember(); paint();
      },
      position() { return { ...point }; },
      move(value) {
        point = { x: value.x, y: value.y };
        pointer.style.transform = `translate(${point.x}px, ${point.y}px)`;
        host.dataset.pointerX = point.x; host.dataset.pointerY = point.y;
        host.dataset.pointerSource = 'worker';
        remember();
      },
      clicked() {
        click.style.left = point.x + 'px'; click.style.top = point.y + 'px';
        click.classList.remove('on'); void click.offsetWidth; click.classList.add('on');
      },
    };
    paint();
    window.__ava.move(point);
  }
  window.__ava = {
    say(value) { caption = value || ""; remember(); },
    show(value) { if (value && !(value.seq && value.seq < seq)) { seq = value.seq || seq; if (POSES.includes(value.pose)) pose = value.pose; if (typeof value.text === "string") caption = value.text; remember(); } },
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
})();
