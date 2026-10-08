// Ava's cursor and captions. Injected only into Ava's own browser (never served by the
// company apps). Hidden from accessibility (aria-hidden) so it never appears in her page
// snapshots, and pointer-events: none so it can never intercept a click.
(() => {
  if (window.__ava) return;
  const KEY = "__ava_overlay";
  const saved = (() => {
    try { return JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch { return {}; }
  })();
  const save = (patch) => {
    Object.assign(saved, patch);
    try { sessionStorage.setItem(KEY, JSON.stringify(saved)); } catch {}
  };

  function mount() {
    if (document.getElementById("__ava_host")) return;
    const host = document.createElement("div");
    host.id = "__ava_host";
    host.setAttribute("aria-hidden", "true");
    host.style.cssText =
      "position:fixed;inset:0;pointer-events:none;z-index:2147483647;view-transition-name:none";
    const root = host.attachShadow({ mode: "closed" });
    root.innerHTML = `
      <style>
        .cursor{position:fixed;left:0;top:0;width:22px;height:22px;transform:translate(-100px,-100px);
          transition:transform .45s cubic-bezier(.22,.8,.3,1);will-change:transform}
        .cursor svg{filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
        .tag{position:absolute;left:18px;top:16px;font:600 11px/1 system-ui,sans-serif;color:#fff;
          background:#4338ca;border-radius:9px;padding:3px 7px;white-space:nowrap}
        .ripple{position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;
          border:2px solid #6366f1;opacity:0;pointer-events:none}
        .ripple.on{animation:rip .55s ease-out}
        @keyframes rip{from{opacity:.9;transform:scale(.3)}to{opacity:0;transform:scale(1.6)}}
        .focus{position:fixed;border:2px solid #6366f1;border-radius:6px;opacity:0;
          box-shadow:0 0 0 4px rgba(99,102,241,.18);transition:all .3s ease}
        .caption{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);max-width:70vw;
          font:500 14px/1.35 system-ui,sans-serif;color:#fff;background:rgba(17,24,39,.88);
          border-radius:10px;padding:9px 14px;opacity:0;transition:opacity .25s ease}
        .caption b{color:#a5b4fc;font-weight:600;margin-right:6px}
        @media (prefers-reduced-motion: reduce){.cursor,.focus{transition:none}}
      </style>
      <div class="focus"></div><div class="ripple"></div>
      <div class="cursor"><svg width="22" height="22" viewBox="0 0 22 22">
        <path d="M3 2 L3 18 L7.5 14 L10.5 20.5 L13 19.4 L10 13 L16 13 Z" fill="#4338ca" stroke="#fff" stroke-width="1.4"/>
      </svg><span class="tag">Ava</span></div>
      <div class="caption"><b>Ava</b><span></span></div>`;
    (document.body || document.documentElement).appendChild(host);
    const cursor = root.querySelector(".cursor");
    const ripple = root.querySelector(".ripple");
    const focus = root.querySelector(".focus");
    const caption = root.querySelector(".caption");
    const captionText = caption.querySelector("span");

    const move = (x, y) => {
      cursor.style.transform = `translate(${x}px, ${y}px)`;
      save({ x, y });
    };
    if (saved.x != null) {
      cursor.style.transition = "none";
      move(saved.x, saved.y);
      requestAnimationFrame(() => { cursor.style.transition = ""; });
    }
    window.addEventListener("mousemove", (e) => move(e.clientX, e.clientY), { capture: true, passive: true });
    window.addEventListener("mousedown", (e) => {
      move(e.clientX, e.clientY);
      ripple.style.left = e.clientX + "px";
      ripple.style.top = e.clientY + "px";
      ripple.classList.remove("on");
      void ripple.offsetWidth;
      ripple.classList.add("on");
    }, { capture: true, passive: true });
    window.addEventListener("focusin", (e) => {
      const r = e.target && e.target.getBoundingClientRect ? e.target.getBoundingClientRect() : null;
      if (!r || !r.width) return;
      Object.assign(focus.style, { left: r.left - 3 + "px", top: r.top - 3 + "px",
        width: r.width + 6 + "px", height: r.height + 6 + "px", opacity: "1" });
      move(r.left + Math.min(24, r.width / 2), r.top + r.height / 2);
    }, { capture: true });
    window.addEventListener("focusout", () => { focus.style.opacity = "0"; }, { capture: true });

    window.__ava = {
      say(text) {
        captionText.textContent = text || "";
        caption.style.opacity = text ? "1" : "0";
        save({ caption: text || "" });
      },
    };
    if (saved.caption) window.__ava.say(saved.caption);
  }

  window.__ava = { say(text) { save({ caption: text || "" }); } };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  } else {
    mount();
  }
})();
