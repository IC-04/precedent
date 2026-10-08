(() => {
  const dialog = document.getElementById('new-task-dialog');
  document.querySelectorAll('[data-new-task]').forEach(button => button.addEventListener('click', () => dialog.showModal()));
  document.querySelector('.close-dialog').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) { const r=dialog.getBoundingClientRect(); if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close(); } });
  const form=dialog.querySelector('form'),submit=form.querySelector('[type=submit]'),error=document.getElementById('task-error');
  form.addEventListener('submit',async event=>{
    event.preventDefault();error.hidden=true;submit.disabled=true;submit.textContent='Starting…';
    try{const response=await fetch(form.action,{method:'POST',body:new FormData(form),headers:{Accept:'application/json'}});if(!response.ok){const body=await response.json();throw new Error(typeof body.detail==='string'?body.detail:'The task could not start. Check the company connection.');}if(response.redirected){window.location.assign(response.url);return;}throw new Error('The server did not return a task. Check task history before trying again.');}
    catch(problem){error.textContent=problem instanceof TypeError?'Connection interrupted. Check task history before starting again.':problem.message;error.hidden=false;submit.disabled=false;submit.textContent='Start task →';}
  });
  let filter = 'all';
  const search = document.getElementById('task-search');
  const rows = [...document.querySelectorAll('.task-row')];
  function update() {
    let visible=0;
    rows.forEach(row => { row.hidden=(filter!=='all'&&row.dataset.kind!==filter)||!row.dataset.search.includes(search.value.toLowerCase()); if(!row.hidden)visible++; });
    document.getElementById('no-task-results').hidden=visible>0||rows.length===0;
  }
  document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    filter=button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(tab=>{const on=tab===button;tab.classList.toggle('selected',on);tab.setAttribute('aria-pressed',String(on));}); update();
  }));
  search.addEventListener('input', update);
  document.querySelectorAll('time[datetime]').forEach(time=>{if(time.dateTime){const date=new Date(time.dateTime);time.textContent=date.toLocaleDateString(undefined,{month:'short',day:'numeric'})+' · '+date.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'});time.title=date.toLocaleString();}});
})();
