(() => {
const workspace=document.getElementById('main'), initial=document.getElementById('initial-state');if(!initial)return;
let state=JSON.parse(initial.textContent),latestState=state,stream,selectedCapture="latest",playTimer=null,selectionVersion=0,playbackVersion=0;
const el=id=>document.getElementById(id), node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const formatDate=value=>value?new Date(value).toLocaleString(undefined,{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'Unavailable';
function sourceLink(source){const text=typeof source==='string'?source:source.ref||JSON.stringify(source);const item=node('li');let path=null;const match=text.match(/(?:mail:|\/mail\/m\/)(m-[\w-]+)|(?:books:|\/books\/bills\/)(INV-[\w-]+)|(?:drive:|\/drive\/f\/)(f-[\w-]+)/);if(!match){const file=(state.company?.documents||[]).find(f=>text.includes(f.name));if(file)path='/drive/f/'+file.id;}if(match)path=match[1]?'/mail/m/'+match[1]:match[2]?'/books/bills/'+match[2]:'/drive/f/'+match[3];if(path){const link=node('a',text);link.href=state.apps_url+path;link.target='_blank';link.rel='noopener';item.append(link);}else item.textContent=text;return item;}
function renderStage(s) {
  const active = s.mode.startsWith('Live') && !s.finished;
  const phase = s.phase || 'prepare';
  const stages = ['prepare', 'execute', 'verify', 'finish'];
  stages.forEach((name, index) => { el('phase-' + name).dataset.state = index < stages.indexOf(phase) ? 'done' : name === phase ? 'current' : 'pending'; });
  el('work-stage').dataset.finished = String(!!s.finished);
  let title = 'Ava is getting ready.', detail = 'Your request is saved. The worker is starting and connecting to the company.', label = 'Task accepted';
  if (s.goal && phase === 'prepare') { title = 'Getting to know the company.'; detail = 'Ava is preparing company context from current records and policies before acting. Preparation reads happen in the background.'; label = 'Understanding the company'; }
  else if (s.wait && phase === 'prepare') { title = 'Turning your request into a goal.'; detail = 'Ava is defining the outcome and checks while gathering company context. The model is working; browser actions have not started yet.'; label = 'Preparing the task'; }
  if (phase === 'execute') { title = 'Ava is at work.'; detail = 'Follow her actual browser for typing, navigation and clicks. Her latest recorded decision and sources appear alongside this task.'; label = 'Executing in the company'; }
  if (phase === 'verify') { title = 'Checking what changed.'; detail = 'Ava is reading the company again and checking the requested outcome. A saved record alone does not prove every requirement is met.'; label = 'Fresh verification'; }
  if (s.question) { title = s.answer_submitted ? 'Your answer is with Ava.' : 'Ava needs your input.'; detail = s.answer_submitted ? 'Waiting for the worker to read your answer and resume.' : 'Answer the question above so she can continue with the right context.'; label = 'Human input'; }
  if (!active && !s.finished) { title = 'This session is no longer running.'; detail = 'The worker stopped without a final receipt. Inspect the recorded actions and company before assigning this task again.'; label = 'Interrupted'; }
  el('phase-label').textContent = label; el('phase-title').textContent = title; el('phase-detail').textContent = detail;
  const facts = el('prepare-facts'); facts.replaceChildren(); facts.hidden = phase !== 'prepare';
  if (phase === 'prepare') {
    const p = s.preparation || {};
    for (const [name, value] of [['Goal and checks', s.goal ? 'Ready' : active ? 'Preparing' : 'Not recorded'], ['Company records', p.records != null ? p.records + ' sources read · ' + p.rows + ' rows' : 'Not yet recorded'], ['Company context', p.context || 'Not yet recorded']]) {
      const row = node('li'); row.append(node('span', name), node('strong', value)); facts.append(row);
    }
  }
  el('native-browser').hidden = !active;
  const ready = s.headed && !!s.browser_focus;
  el('focus-browser').disabled = !ready;
  el('focus-browser').textContent = ready ? 'Bring Ava’s browser forward ↗' : s.headed ? 'Waiting for the browser…' : 'Native browser unavailable';
  el('native-explanation').textContent = s.headed ? 'Watch Ava in her own Chrome for Testing window. Her purple pointer follows actual worker actions.' : 'This run was started without a native browser. Follow the recorded events here; use a headed console for the visible demo.';
  const screenError = [...s.notes].reverse().find(n => n.kind === 'screen_unavailable');
  if (screenError) { el('focus-browser').textContent = 'Browser viewing unavailable'; el('native-explanation').textContent = 'The viewer could not connect. Ava may continue working; follow actual events and results here.'; }
  const failure = [...s.history].reverse().find(e => e.type === 'failure');
  el('recovery').hidden = !failure;
  if (failure) { const d = failure.data; const resumed = s.history.some(e => e.seq > failure.seq && e.type === 'action'); el('recovery').textContent = (resumed ? 'Work continued after a recorded issue: ' : 'Recorded issue: ') + (d.detail || d.reason || d.error || d.text || d.kind || 'See technical activity for the failure details.'); }
}
function render(s){
state=s; renderStage(s); if(s===latestState)window.AvaCompanion?.follow(s);
el('expand').textContent=workspace.classList.contains('expanded')?'Show details':'Focus view';
el('replay').hidden=latestState.mode.startsWith('Live')||(latestState.captures||[]).length<2;
el('status').textContent=s.status;el('status').dataset.tone=s.notice?'problem':'normal';
el('mode').textContent=s.validation?'Scripted validation · '+(s.mode.startsWith('Live')?'fixture events':'historical'):s.mode.startsWith('Live')?'Live task':'Historical run';
const learned = [...s.notes].reverse().find(n => ['skill_selected','memory_recalled','memory_unavailable'].includes(n.kind));
if(el('learning-activity')){el('learning-activity').hidden=!learned||!!s.finished;el('learning-activity').textContent=learned?.text||'';}
el('activity').textContent=s.notice?.title||(s.finished?'Session ended · results below':s.activity);
el('last-activity').textContent=formatDate(s.last_activity_at);el('cost').textContent=s.finished?.usd==null?'Unavailable':'USD '+s.finished.usd;
el('browser-url').textContent=s.observation?.url||'No observation recorded';
el('capture-count').textContent='('+s.captures.length+')';
const selector=el('capture-select');selector.replaceChildren();const latestOption=node('option','Latest saved view');latestOption.value='latest';selector.append(latestOption);
for(const c of s.captures||[]){const option=node('option','Observation '+c.observation_seq+' · '+formatDate(c.captured_at)+' · '+(c.title||'Browser'));option.value=String(c.observation_seq);selector.append(option);}selector.value=selectedCapture;
const capture=selectedCapture==='latest'?s.capture:(s.captures||[]).find(c=>String(c.observation_seq)===selectedCapture);
if(capture?.href){el('browser-image').hidden=false;el('browser-empty').hidden=true;if(el('browser-image').getAttribute('src')!==capture.href)el('browser-image').src=capture.href;el('capture-time').textContent='Captured '+formatDate(capture.captured_at);el('browser-url').textContent=capture.url||'URL unavailable';}
else{el('browser-image').hidden=true;el('browser-empty').hidden=false;el('capture-time').textContent='No capture available';}
const plan=el('plan');plan.replaceChildren();for(const step of s.plan){const li=node('li',step.intent);li.append(node('small',({todo:'Pending',doing:'In progress',done:'Done as reported',skipped:'Skipped',added:'Added'})[step.status]||'Pending'));if(step.expect)li.title='Expected: '+step.expect;plan.append(li);}if(!s.plan.length)plan.append(node('li','No plan recorded.'));
const precedents=el('precedents');precedents.replaceChildren();for(const p of s.precedents){precedents.append(node('h3',p.rule),node('p',[p.status,p.support,...(p.flags||[])].filter(Boolean).join(' · ')));const ul=node('ul',null,'source-list');for(const src of [p.governing,...(p.supporting||[])].filter(Boolean))ul.append(sourceLink(src));precedents.append(ul);}if(!s.precedents.length)precedents.append(node('p','No validated company context has been recorded yet. Preparation reads current company pages in the background.','muted'));
const decision=el('decision');decision.replaceChildren();const latest=s.decisions.at(-1);if(latest){decision.append(node('p',latest.decided,'decision-summary'));if(latest.means)decision.append(node('p',latest.means,'muted'));const detail=node('details');detail.append(node('summary','Decision evidence · '+(latest.sources||[]).length));const dl=node('dl',null,'decision-record');for(const [key,label] of [['observed','Observed'],['action','Intended action'],['check','Expected read-back']])if(latest[key])dl.append(node('dt',label),node('dd',latest[key]));detail.append(dl);const list=node('ul',null,'source-list');for(const src of latest.sources||[])list.append(sourceLink(src));detail.append(list);decision.append(detail);}else decision.append(node('p','No decision recorded yet.','muted'));
const goal=el('goal');goal.replaceChildren();if(s.goal){goal.append(node('p',s.goal.outcome));for(const c of s.conditions){const row=node('div',null,'condition '+(c.state==='Verified'?'verified':''));row.append(node('strong',(c.kind==='must_not_happen'?'Safeguard · ':'')+c.state),node('p',c.text));if(c.evidence){const d=node('details');d.append(node('summary','Check evidence'),node('p',c.evidence));row.append(d);}goal.append(row);}}else goal.append(node('p','Goal contract has not been recorded.','muted'));
const effects=el('effects');effects.replaceChildren();for(const e of s.effects)effects.append(node('p','Written · '+e.method+' '+e.path+' · HTTP '+e.status),node('small',e.text));if(!s.effects.length)effects.append(node('p','No acknowledged application changes recorded.','muted'));
const grade=el('grade');grade.replaceChildren();if(s.grade){const items=s.grade.items||[];grade.append(node('p','Independent grader: '+s.grade.overall+(items.length?' · '+items.filter(i=>i.result==='pass').length+'/'+items.length+' checks':'')),node('p','This result comes from privileged evaluation, separately from Ava’s browser verification.','muted'));const d=node('details');d.append(node('summary','Grade details'),node('pre',JSON.stringify(s.grade,null,2),'text'));grade.append(d);}else grade.append(node('p','No independent grade saved for this run.','muted'));
const outcome=el('outcome');outcome.replaceChildren();
if(s.finished||s.receipt){
  const counts = {Verified:0, Failed:0, Unknown:0};
  for (const c of s.conditions) counts[c.state === 'Verified' ? 'Verified' : c.state === 'Failed' ? 'Failed' : 'Unknown']++;
  const heading = s.notice?.title || (s.display_outcome==='pass' ? 'The work is complete.' : s.display_outcome==='blocked' ? 'Ava could not finish this task.' : counts.Failed ? 'The result needs attention.' : 'Work returned. Some checks remain open.');
  outcome.append(node('div', 'Task result', 'eyebrow'), node('h2', heading));
  outcome.append(node('p',s.notice?.text||s.receipt?.summary||'No fresh worker verification or evidence receipt is available for this recorded run.'));
  const stats=node('div',null,'verification-counts');
  for(const [name,count] of Object.entries(counts)){const item=node('span');item.append(node('strong',String(count)),node('span',name==='Unknown'?'unresolved':name.toLowerCase()));stats.append(item);}outcome.append(stats);
  const links=node('ul',null,'result-links');
  for(const artifact of s.artifacts||[]){const li=node('li'),a=node('a',artifact.label+' ↗');a.href=artifact.href||(s.apps_url+artifact.path);a.target='_blank';a.rel='noopener';li.append(a);links.append(li);}if(links.children.length)outcome.append(links);
  if(s.receipt?.pending?.length){const pending=node('details');pending.append(node('summary','Unresolved checks · '+s.receipt.pending.length));const list=node('ul');for(const text of s.receipt.pending)list.append(node('li',text));pending.append(list);outcome.append(pending);}
  if(s.finished?.error){const error=node('details',null,'error-details');error.append(node('summary','Technical error'),node('p',s.finished.error));outcome.append(error);}
  if(s.grade){const items=s.grade.items||[];outcome.append(node('p','Independent grading: '+s.grade.overall+' · '+items.filter(i=>i.result==='pass').length+'/'+items.length+' checks. Separate from Ava’s fresh verification.','muted'));}
  if(s.has_receipt_file){const a=node('a','Download evidence receipt');a.href='/runs/'+s.run_id+'/receipt.md';outcome.append(a);}
}
const history=el('history');history.replaceChildren();el('event-count').textContent='· '+s.history.length;for(const event of [...s.history].reverse()){const li=node('li');li.append(node('time',formatDate(event.ts)));const d=event.data;li.append(node('strong',event.type.replaceAll('_',' ')+' · '+(d.tool||d.decided||d.text||d.detail||d.kind||d.result||'')));const details=node('details');details.append(node('summary','Exact event'),node('pre',JSON.stringify(d,null,2)));li.append(details);history.append(li);}
const qa=el('question-area'),q=s.question;if(q){const signature=q.question_id+':'+s.can_answer+':'+s.answer_submitted;if(qa.dataset.signature!==signature){qa.dataset.signature=signature;qa.replaceChildren();const box=node('section',null,'question-box');box.append(node('h3','Ava needs a choice'),node('p',q.text));if(s.can_answer){const form=node('form');form.method='post';form.action='/runs/'+s.run_id+'/answer';const hidden=node('input');hidden.type='hidden';hidden.name='question_id';hidden.value=q.question_id;form.append(hidden);for(const option of q.options||[]){const b=node('button',option,'secondary');b.type='submit';b.name='choice';b.value=option;form.append(b);}const label=node('label','Your answer');label.htmlFor='human-answer';const input=node('input');input.id='human-answer';input.name='answer';input.maxLength=4000;form.append(label,input);const submit=node('button','Send answer');submit.type='submit';submit.addEventListener('click',e=>{if(!input.value.trim()){e.preventDefault();input.focus();}});form.append(submit);box.append(form);}else box.append(node('p',s.answer_submitted?'Answer submitted. Waiting for Ava to resume.':'This recorded run is no longer waiting on an active human channel.','muted'));qa.append(box);}}else{qa.replaceChildren();qa.dataset.signature='';}
updateTime();}
function updateTime(){const active=state.mode.startsWith('Live');const waiting=el('model-wait');waiting.hidden=!(active&&state.wait);if(!waiting.hidden){const seconds=Math.max(0,Math.floor((Date.now()-Date.parse(state.wait.started_at))/1000));waiting.textContent='Waiting for the model · '+seconds+'s'+(state.wait.phase==='goal'&&state.wait.timeout_seconds?' · Goal preparation stops after '+Math.ceil(state.wait.timeout_seconds)+'s if no goal is returned.':'. Ava will continue when the model responds.');}const seconds=state.finished?.seconds??(state.started_at?Math.max(0,Math.floor(((active?Date.now():Date.parse(state.last_activity_at||state.started_at))-Date.parse(state.started_at))/1000)):null);el('elapsed').textContent=seconds==null?'Unavailable':Math.floor(seconds/60)+'m '+Math.floor(seconds%60)+'s'+(!active?' recorded':'');const c=selectedCapture==='latest'?state.capture:(state.captures||[]).find(c=>String(c.observation_seq)===selectedCapture);if(!c){el('capture-freshness').textContent='';return;}const age=Math.max(0,Math.floor((Date.now()-Date.parse(c.captured_at))/1000));el('capture-freshness').textContent=selectedCapture!=='latest'?'Inspecting saved capture':!active?'Recorded capture':c.observation_seq!==state.observation?.seq?'Older than latest observation':age>45?'Stale · '+age+'s since capture':'Latest capture · '+age+'s ago';}
function stopPlayback(){playbackVersion++;if(playTimer){clearTimeout(playTimer);playTimer=null;}el('replay').textContent='Play recorded views';el('replay').setAttribute('aria-pressed','false');}
async function showCapture(value){selectedCapture=value;const version=++selectionVersion;if(value==='latest'){render(latestState);return;}try{const response=await fetch('/runs/'+encodeURIComponent(latestState.run_id)+'/state?at='+encodeURIComponent(value));if(!response.ok)throw new Error('Recorded view unavailable');const historic=await response.json();if(version===selectionVersion)render(historic);}catch(error){if(version===selectionVersion){stopPlayback();el('capture-freshness').textContent='Could not load recorded evidence. Select another view to retry.';}}}
el('capture-select').addEventListener('change',event=>{stopPlayback();showCapture(event.target.value);});
el('replay').addEventListener('click',()=>{if(playTimer){stopPlayback();return;}let index=0;const playbackId=++playbackVersion;const captures=latestState.captures||[];el('replay').textContent='Pause replay';el('replay').setAttribute('aria-pressed','true');async function advance(){await showCapture(String(captures[index].observation_seq));if(!playTimer||playbackId!==playbackVersion)return;index++;if(index<captures.length){playTimer=setTimeout(advance,2500);}else{playTimer=setTimeout(()=>{stopPlayback();showCapture('latest');},2500);}}playTimer=setTimeout(advance,0);});
el('expand').addEventListener('click',()=>{const expanded=workspace.classList.toggle('expanded');el('expand').textContent=expanded?'Show details':'Focus view';el('expand').setAttribute('aria-pressed',String(expanded));});
el('focus-browser').addEventListener('click', async () => {
  const button = el('focus-browser'), error = el('view-error'); button.disabled=true; error.hidden=true;
  try { const response = await fetch('/runs/'+encodeURIComponent(latestState.run_id)+'/focus', {method:'POST'}); if(!response.ok){const body=await response.json();throw new Error(body.detail||'Browser unavailable');} }
  catch(problem){error.textContent=problem.message;error.hidden=false;}
  finally {button.disabled=!latestState.browser_focus||!!latestState.finished;}
});
el('browser-image').addEventListener('error',()=>{el('browser-image').hidden=true;el('browser-empty').hidden=false;el('capture-time').textContent='Capture unavailable';});
if(matchMedia('(max-width:1000px)').matches)document.querySelectorAll('.evidence-area>details').forEach(d=>d.open=false);render(state);setInterval(updateTime,1000);
stream=new EventSource('/runs/'+encodeURIComponent(state.run_id)+'/events');stream.addEventListener('state',event=>{latestState=JSON.parse(event.data);if(selectedCapture==='latest')render(latestState);if(!latestState.mode.startsWith('Live')){el('connection').textContent='Recorded run';stream.close();}else el('connection').textContent=state.question?'Connected · waiting for answer':state.wait?'Connected · waiting for model':state.headed?'Connected · actual browser window':'Connected · task events';});stream.onerror=()=>{el('connection').textContent=state.mode.startsWith('Live')?'Disconnected · reconnecting':'Recorded run';};
})();
