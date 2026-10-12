// Ava's companion on human-facing pages: one Ava per page, a small task panel, and a
// draft handoff to the console's composer. Opening Ava, choosing a suggestion or
// navigating never starts work: the person reviews the draft and assigns it there.
// Poses come from the console's recorded run state (precedent/companion.py).
(() => {
  const configNode = document.getElementById('ava-config');
  if (!configNode || window.AvaCompanion) return;
  const config = JSON.parse(configNode.textContent);
  const ctx = config.context || {surface: config.surface};
  const inline = config.mount === 'inline';
  const consoleUrl = config.console || '';
  const trigger = inline ? document.querySelector('[data-ava-mount]') : document.querySelector('[data-ava-dock] .ava-dock-button');
  if (!trigger) return;
  const dock = trigger.closest('[data-ava-dock]');
  const figure = trigger.querySelector('.ava');
  const store = (kind, key, value) => {
    try {
      const s = kind === 'local' ? localStorage : sessionStorage;
      if (value === undefined) return s.getItem(key);
      if (value === null) s.removeItem(key); else s.setItem(key, value);
    } catch { return null; }
  };
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  // ---- presence: pose and bubble -------------------------------------------------
  let work = {reachable: true, active: false}, override = null, panel = null, overrideTimer;
  const bubble = el('p', 'ava-bubble'); bubble.setAttribute('role', 'status'); bubble.hidden = true;
  (dock || trigger).append(bubble);
  if (dock) document.body.classList.add('has-ava-dock');
  function pose() {
    if (override) return override;
    if (work.pose) return work.pose;
    if (panel && !panel.hidden) return 'listen';
    return work.reachable ? 'idle' : 'away';
  }
  function render() {
    if (figure && !figure.dataset.guided) figure.dataset.pose = pose();
    const line = work.line || (!work.reachable ? 'Ava’s workspace is unreachable' : '');
    trigger.setAttribute('aria-label', 'Ava' + (line ? ' · ' + line : '') + ' · open task helper');
    if (dock && work.active && line && (!panel || panel.hidden)) say(line, 0);
    else if (bubble.dataset.persistent) { bubble.hidden = true; delete bubble.dataset.persistent; }
    if (panel) fillPanel();
  }
  let bubbleTimer;
  function say(text, seconds = 5) {
    clearTimeout(bubbleTimer); bubble.textContent = text; bubble.hidden = false;
    if (seconds) { delete bubble.dataset.persistent; bubbleTimer = setTimeout(() => { bubble.hidden = true; }, seconds * 1000); }
    else bubble.dataset.persistent = '1';
  }
  function flash(name, ms) {
    clearTimeout(overrideTimer); override = name; render();
    overrideTimer = setTimeout(() => { override = null; render(); }, ms);
  }

  // ---- work state: the console's managed run, never guessed --------------------------
  function absolute(url) { return url && url.startsWith('/') ? consoleUrl + url : url; }
  function normalize(data) {
    if (config.handoff === 'apps') {
      if (!data || data.unavailable) return {reachable: false, active: false};
      const run = data.run;
      if (!run || !run.active) return {reachable: true, active: false};
      return {reachable: true, active: true, runUrl: absolute(run.run_url), request: run.request, pose: run.companion?.pose, line: run.companion?.line};
    }
    if (!data || !data.run_url) return {reachable: true, active: false};
    return {reachable: true, active: true, runUrl: data.run_url, request: data.request, pose: data.companion?.pose, line: data.companion?.line};
  }
  let followed = null;  // a run page's own state outranks polling
  async function poll() {
    if (document.hidden || followed) return;
    try {
      const response = await fetch(config.status, {cache: 'no-store', signal: AbortSignal.timeout(3000)});
      work = normalize(response.ok ? await response.json() : null);
    } catch { work = {reachable: false, active: false}; }
    render();
  }
  function follow(state) {
    const active = String(state.mode || '').startsWith('Live') && !state.finished;
    followed = {reachable: true, active, runUrl: '/runs/' + state.run_id, request: state.request, pose: state.companion?.pose, line: state.companion?.line};
    work = followed; render();
  }

  // ---- the panel -------------------------------------------------------------------
  const F1 = vendor => `Find the latest invoice from ${vendor}, enter it into Books and route it for approval.`;
  const F2 = vendor => `Find the latest invoice from ${vendor} and check whether it is already recorded in Books. Do not create or change any records.`;
  // Only task families the worker has been validated on. Planned capabilities are not offered.
  const owns = name => name + (/s$/i.test(name) ? '’' : '’s');
  function suggestions() {
    const v = ctx.vendor, missing = '[vendor]';
    if (ctx.surface === 'calendar' || ctx.kind === 'draft') return [
      {label: 'Prepare a catch-up', text: 'Prepare a catch-up with [colleague] next week about [topic]. Read our recent email and chat, find two suitable 30-minute times, and save an email draft for me to review. Do not send it.'},
      {label: 'Prepare a draft with a local hold', text: 'Prepare a catch-up with [colleague] next week about [topic], save an email draft with two suitable 30-minute options, and place a local tentative hold for the first option. Do not send anything.'}];
    if (ctx.kind === 'bill' && v && ctx.invoice) return [
      {label: `Is ${ctx.invoice} a duplicate?`, text: `Check whether ${v} invoice ${ctx.invoice} is recorded more than once in Books. Do not create or change any records.`},
      {label: `Enter ${owns(v)} latest invoice`, text: F1(v)}];
    if (ctx.kind === 'file' && ctx.attachment) return [
      {label: `Enter ${ctx.label} as a bill`, text: `Enter the invoice in ${ctx.label} into Books as a bill and route it for approval.`},
      {label: `Is ${ctx.label} already recorded?`, text: `Check whether the invoice in ${ctx.label} is already recorded in Books. Do not create or change any records.`}];
    if (v) return [{label: `Enter & route ${owns(v)} latest invoice`, text: F1(v)}, {label: `Check ${v} for a duplicate`, text: F2(v)}];
    return [{label: 'Enter & route an invoice', text: F1(missing)}, {label: 'Check for a duplicate', text: F2(missing)}];
  }
  const where = {calendar: 'Calendar', mail: 'Mail', books: 'Books', drive: 'Drive', chat: 'Chat', overview: 'the company overview', tasks: 'your tasks', guide: 'the guide', run: 'this task'};
  function buildPanel() {
    panel = el('section', 'ava-panel'); panel.id = 'ava-panel'; panel.hidden = true;
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-labelledby', 'ava-panel-title');
    const head = el('header', 'ava-panel-head'); const title = el('strong', null, 'Ava'); title.id = 'ava-panel-title';
    const close = el('button', 'ava-panel-close secondary', 'Close'); close.type = 'button'; close.addEventListener('click', () => toggle(false));
    head.append(title, el('span', 'ava-panel-status'), close);
    const line = el('p', 'ava-panel-line');
    const active = el('div', 'ava-panel-active');
    active.append(el('p', 'ava-panel-working'), el('p', 'ava-panel-request'));
    const back = el('a', 'button ava-panel-return', 'Return to Ava’s task ↗'); active.append(back);
    const form = el('form', 'ava-panel-form'); form.noValidate = true;
    const label = el('label', null, 'What should Ava do?'); label.htmlFor = 'ava-draft';
    const draft = el('textarea'); draft.id = 'ava-draft'; draft.rows = 3; draft.maxLength = 2000;
    draft.value = store('session', 'ava.draft') || '';
    draft.addEventListener('input', () => { store('session', 'ava.draft', draft.value || null); hint(''); });
    const list = el('div', 'ava-suggestions'); list.setAttribute('role', 'group'); list.setAttribute('aria-label', 'Suggested tasks');
    for (const item of suggestions()) {
      const chip = el('button', 'ava-chip secondary', item.label); chip.type = 'button';
      chip.addEventListener('click', () => choose(item.text));
      list.append(chip);
    }
    const message = el('p', 'ava-panel-hint'); message.setAttribute('role', 'status'); message.id = 'ava-hint';
    draft.setAttribute('aria-describedby', 'ava-hint');
    const submit = el('button', 'ava-panel-submit', 'Review in task composer ↗'); submit.type = 'submit';
    form.append(label, draft, el('span', 'ava-suggestions-label', 'Suggestions'), list, message, submit, el('p', 'ava-panel-note', 'Nothing starts until you assign it there.'));
    form.addEventListener('submit', event => { event.preventDefault(); handoff(); });
    const foot = el('footer', 'ava-panel-foot');
    if (consoleUrl === '' && config.surface !== 'guide') { const guide = el('a', null, 'Meet Ava in the guide'); guide.href = '/guide'; foot.append(guide); }
    if (dock) { const tuck = el('button', 'secondary ava-tuck', 'Tuck Ava away'); tuck.type = 'button'; tuck.addEventListener('click', () => tucked(true)); foot.append(tuck); }
    panel.append(head, line, active, form, foot);
    panel.addEventListener('keydown', event => { if (event.key === 'Escape') { event.stopPropagation(); toggle(false); } });
    document.body.append(panel);
    trigger.setAttribute('aria-controls', panel.id);
  }
  const part = selector => panel.querySelector(selector);
  function hint(text, tone) { const h = part('.ava-panel-hint'); h.textContent = text; h.dataset.tone = tone || ''; }
  function choose(text) {
    const draft = part('#ava-draft'); draft.value = text; store('session', 'ava.draft', text);
    const at = text.indexOf('[vendor]');
    draft.focus();
    if (at >= 0) { draft.setSelectionRange(at, at + 8); hint('Replace [vendor] with the vendor’s name.'); }
    else { draft.setSelectionRange(text.length, text.length); hint('Edit it if you like, then review it in the composer.'); }
  }
  function fillPanel() {
    const status = !work.reachable ? 'Workspace unreachable' : work.active ? 'Working' : 'Ready';
    part('.ava-panel-status').textContent = status;
    part('.ava-panel-active').hidden = !work.active;
    part('.ava-panel-form').hidden = work.active;
    if (work.active) {
      part('.ava-panel-line').textContent = 'I’m on one task at a time. Here’s where it stands.';
      part('.ava-panel-working').textContent = work.line || 'Working';
      part('.ava-panel-request').textContent = work.request || '';
      part('.ava-panel-return').href = work.runUrl;
      part('.ava-panel-return').hidden = config.surface === 'run' && location.pathname === work.runUrl;
    } else {
      const here = ctx.label ? `${where[ctx.surface] || 'here'} · ${ctx.label}` : where[ctx.surface] || 'here';
      part('.ava-panel-line').textContent = !work.reachable ? 'I can’t reach my workspace right now. Your draft stays here until it’s back.'
        : followed && work.line ? `This task: ${work.line}. Want to start something new?` : `Hi. What should I take on from ${here}?`;
      part('.ava-panel-submit').disabled = !work.reachable;
    }
  }
  function toggle(open) {
    if (!panel) buildPanel();
    if (open === undefined) open = panel.hidden;
    if (open && panel.hidden) {
      panel.hidden = false; bubble.hidden = true; fillPanel(); place();
      trigger.setAttribute('aria-expanded', 'true');
      if (!work.active) flash('greet', 1700);
      (work.active ? part('.ava-panel-return') : part('#ava-draft')).focus();
      poll();
    } else if (!open && !panel.hidden) {
      panel.hidden = true; trigger.setAttribute('aria-expanded', 'false'); render(); trigger.focus({preventScroll: true});
    }
  }
  function place() {
    if (dock) { panel.classList.add('ava-panel-docked'); return; }
    const box = trigger.getBoundingClientRect();
    const width = Math.min(340, innerWidth - 24);
    panel.style.left = Math.max(12, Math.min(innerWidth - width - 12, box.left)) + 'px';
    const below = box.bottom + 8, above = box.top - 8;
    if (below + 380 < innerHeight || above < 380) { panel.style.top = Math.min(below, innerHeight - 200) + 'px'; panel.style.bottom = ''; }
    else { panel.style.bottom = (innerHeight - above) + 'px'; panel.style.top = ''; }
  }
  async function handoff() {
    const text = part('#ava-draft').value.trim();
    if (!text) { hint('Write what Ava should do, or choose a suggestion.', 'problem'); part('#ava-draft').focus(); return; }
    if (text.includes('[vendor]')) { hint('Replace [vendor] with the vendor’s name first.', 'problem'); choose(text); return; }
    const submit = part('.ava-panel-submit'); submit.disabled = true;
    if (config.handoff === 'console') {
      const composer = document.getElementById('request');
      if (composer && !composer.disabled) {
        composer.value = text; store('session', 'ava.draft', null); toggle(false); composer.focus();
        document.dispatchEvent(new CustomEvent('ava:draft', {detail: {context: ctx}}));
        submit.disabled = false; return;
      }
      store('session', 'ava.handoff', JSON.stringify({text, context: ctx}));
      store('session', 'ava.draft', null);
      location.assign('/#request'); return;
    }
    try {
      const response = await fetch('/ava/handoff', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text, context: ctx}), signal: AbortSignal.timeout(4000)});
      const body = await response.json();
      if (!response.ok || !body.token) throw new Error(body.detail || 'The draft could not be handed over.');
      store('session', 'ava.draft', null);
      location.assign(consoleUrl + '/compose?handoff=' + encodeURIComponent(body.token));
    } catch (problem) {
      hint((problem instanceof TypeError || problem.name === 'TimeoutError' ? 'Connection interrupted.' : problem.message) + ' Your draft is still here.', 'problem');
      submit.disabled = false;
    }
  }
  function tucked(on) {
    if (!dock) return;
    store('local', 'ava.tucked', on ? '1' : null);
    dock.classList.toggle('ava-tucked', on);
    if (on && panel && !panel.hidden) { panel.hidden = true; trigger.setAttribute('aria-expanded', 'false'); }
    trigger.setAttribute('title', on ? 'Show Ava' : 'Ava');
    if (on) trigger.focus({preventScroll: true});
  }

  // ---- wiring ----------------------------------------------------------------------
  trigger.setAttribute('aria-expanded', 'false'); trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.addEventListener('click', event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey) return;  // let new-tab links work
    event.preventDefault();
    if (dock && dock.classList.contains('ava-tucked')) { tucked(false); return; }
    toggle();
  });
  document.addEventListener('pointerdown', event => {
    if (panel && !panel.hidden && !panel.contains(event.target) && !trigger.contains(event.target)) toggle(false);
  });
  addEventListener('resize', () => { if (panel && !panel.hidden) place(); });
  if (store('local', 'ava.tucked') === '1') tucked(true);
  if (config.surface === 'run') {
    try { follow(JSON.parse(document.getElementById('initial-state').textContent)); } catch {}
  }
  let timer;
  function schedule() { clearInterval(timer); timer = setInterval(poll, 5000); }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  addEventListener('pageshow', () => { poll(); schedule(); });
  addEventListener('pagehide', () => clearInterval(timer));
  render();
  if (!store('session', 'ava.greeted') && !work.active) {
    store('session', 'ava.greeted', '1');
    setTimeout(() => { if (!work.active && (!panel || panel.hidden)) say(config.lines[Math.floor(Math.random() * config.lines.length)], 5); }, 1200);
  }
  window.AvaCompanion = {follow, open: () => toggle(true), close: () => toggle(false), say, figure: () => figure};
})();
