(() => {
  const form = document.querySelector('.assignment'), input = document.getElementById('request');
  const submit = form.querySelector('[type=submit]'), error = document.getElementById('task-error');
  const note = document.getElementById('draft-note');
  function drafted(context) {
    const from = context && context.surface ? ' from ' + context.surface.charAt(0).toUpperCase() + context.surface.slice(1) + (context.label ? ' · ' + context.label : '') : '';
    note.textContent = 'Drafted with Ava' + from + '. Review it, then assign. Nothing has started.'; note.hidden = false;
  }
  // A same-origin draft from Ava's panel on another console page; read once, then removed.
  try {
    const handed = JSON.parse(sessionStorage.getItem('ava.handoff') || 'null');
    sessionStorage.removeItem('ava.handoff');
    if (handed && typeof handed.text === 'string' && !input.disabled) { input.value = handed.text.slice(0, 2000); drafted(handed.context); }
  } catch {}
  document.addEventListener('ava:draft', event => drafted(event.detail && event.detail.context));
  if (location.pathname === '/compose') history.replaceState(null, '', '/#request');
  if ((location.hash === '#request' || input.value) && !input.disabled) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
  document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => { input.value = button.dataset.example; input.focus(); }));
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && document.activeElement === input && !submit.disabled) form.requestSubmit();
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); input.focus(); }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); error.hidden = true;
    if (/\[(vendor|colleague|topic)\]/.test(input.value)) { error.textContent = 'Replace the bracketed placeholders with your colleague, topic or vendor before assigning.'; error.hidden = false; input.focus(); return; }
    submit.disabled = true; submit.textContent = 'Handing over to Ava…';
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'}});
      if (!response.ok) { const body = await response.json(); throw new Error(typeof body.detail === 'string' ? body.detail : 'The task could not start. Check the company connection.'); }
      if (response.redirected) { window.location.assign(response.url); return; }
      throw new Error('No task was returned. Check history before trying again.');
    } catch (problem) {
      error.textContent = problem instanceof TypeError ? 'Connection interrupted. Check history before starting again.' : problem.message;
      error.hidden = false; submit.disabled = false; submit.textContent = 'Assign to Ava ↗';
    }
  });
  let filter = 'all';
  const search = document.getElementById('task-search'), rows = [...document.querySelectorAll('.task-row')];
  function update() {
    let visible = 0;
    rows.forEach(row => { row.hidden = (filter !== 'all' && row.dataset.kind !== filter) || !row.dataset.search.includes(search.value.toLowerCase()); if (!row.hidden) visible++; });
    document.getElementById('no-task-results').hidden = visible > 0 || rows.length === 0;
  }
  document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    filter = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(tab => { const on = tab === button; tab.classList.toggle('selected', on); tab.setAttribute('aria-pressed', String(on)); }); update();
  }));
  search.addEventListener('input', update);
  document.querySelectorAll('time[datetime]').forEach(time => { if (time.dateTime) { const date = new Date(time.dateTime); time.textContent = date.toLocaleDateString(undefined, {month:'short', day:'numeric'}) + ' · ' + date.toLocaleTimeString(undefined, {hour:'2-digit',minute:'2-digit'}); time.title = date.toLocaleString(); } });
})();
