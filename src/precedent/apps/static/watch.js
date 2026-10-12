(() => {
  const status = document.getElementById('watch-status');
  async function followTask() {
    try {
      const response = await fetch('/watch/state', {cache: 'no-store'});
      if (!response.ok) throw new Error('Workspace unavailable');
      const data = await response.json();
      if (typeof data.run_url === 'string' && /^\/runs\/[A-Za-z0-9_-]+$/.test(data.run_url)) {
        window.location.replace(data.run_url + '/workspace');
        return;
      }
      status.textContent = 'Connected · waiting for a task';
    } catch {
      status.textContent = 'Connection interrupted · reconnecting';
    }
    window.setTimeout(followTask, 1000);
  }
  followTask();
})();
