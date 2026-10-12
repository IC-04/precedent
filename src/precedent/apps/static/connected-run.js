(() => {
 const list = document.querySelector('#run-events'); if (!list) return;
 const seen = new Set(); let providerSeen = 0;
 const status = document.querySelector('#run-status');
 const providerLabels = {gmail_read:'Read Gmail', gmail_draft:'Save Gmail draft', calendar_list:'Read calendar access', calendar_read:'Read calendar events', calendar_availability:'Check owner availability', calendar_reserve:'Save owner-only hold'};
 function append(text) { const p = document.createElement('p'); p.textContent = text; list.append(p); }
 async function poll() {
  try {
   const response = await fetch(`/runs/${list.dataset.run}/events`);
   if (!response.ok) throw Error('Run access changed or the evidence expired.');
   const data = await response.json();
   for (const event of data.events) {
    if (seen.has(event.seq)) continue; seen.add(event.seq);
    const d = event.data;
    if (event.type === 'question') {
     document.querySelector('#human-answer').hidden = false;
     document.querySelector('#human-question').textContent = d.text;
     document.querySelector('#question-id').value = d.question_id;
     status.textContent = 'Ava needs your input';
    }
    if (event.type === 'answer' || event.type === 'run_finished') document.querySelector('#human-answer').hidden = true;
    let text = event.type === 'check' ? `${d.result}: ${d.text}` :
     event.type === 'run_finished' ? `Result: ${d.outcome}${d.error ? ' · ' + d.error : ''}` :
     event.type === 'note' ? d.text : event.type === 'decision_record' ? d.decided : null;
    if (event.type === 'goal_contract') text = d.outcome;
    if (event.type === 'plan' || event.type === 'plan_changed') {
     const plan = document.querySelector('#run-plan'); plan.replaceChildren();
     for (const step of d.steps || []) { const li = document.createElement('li'); li.dataset.status = step.status; li.textContent = `${step.status} · ${step.intent}`; plan.append(li); }
     text = d.reason || null;
    }
    const avatar = document.querySelector('.connected-companion .ava');
    if (avatar) {
     if (event.type === 'note' && d.kind === 'model_wait') avatar.dataset.pose = 'think';
     if (event.type === 'action') avatar.dataset.pose = 'work';
     if (event.type === 'question') avatar.dataset.pose = 'ask';
     if (d.phase === 'verify') avatar.dataset.pose = 'check';
     if (event.type === 'run_finished') avatar.dataset.pose = d.outcome === 'pass' ? 'deliver' : 'idle';
    }
    if (event.type === 'action' && d.caption) text = d.caption;
    if (event.type === 'note' && d.kind === 'model_wait') text = null;
    if (text) append(text);
    if (event.type === 'note' && d.kind === 'phase') status.textContent = d.phase === 'verify' ? 'Checking the result in Google' : d.phase === 'prepare' ? 'Understanding your task' : 'Ava is working';
    if (d.kind === 'connected_artifacts') {
     for (const url of d.artifacts || []) { const link = document.createElement('a'); link.href = url; link.textContent = 'Review native result →'; link.className = 'button'; document.querySelector('#run-artifacts').append(link); }
    }
    if (event.type === 'run_finished') status.textContent = d.outcome === 'pass' ? 'Completed and independently checked' : 'Review the result';
   }
   const activity = data.provider_activity || [];
   for (const a of activity.slice(providerSeen)) { const p = document.createElement('p'); p.textContent = `${providerLabels[a.capability] || 'Google operation'} · ${a.status} · ${a.seconds}s`; document.querySelector('#provider-activity').append(p); }
   providerSeen = activity.length;
   if (data.active) setTimeout(poll, 2000);
   else if (!data.events.some(e => e.type === 'run_finished')) status.textContent = 'Run stopped · review activity';
  } catch(e) { status.textContent = e.message; }
 }
 poll();
})();
