(() => {
  const initial = document.getElementById('live-state');
  let state = JSON.parse(initial.textContent), connecting = false, retryTimer = null;
  const image = document.getElementById('live-image'), stage = document.querySelector('.live-stage');
  const connection = document.getElementById('live-connection'), message = document.getElementById('live-message');
  const title = document.getElementById('live-message-title'), text = document.getElementById('live-message-text');
  const streamPath = '/runs/' + encodeURIComponent(state.run_id) + '/screen';
  function isLive() { return state.mode.startsWith('Live') && !state.finished; }
  function notice(heading, body, status) {
    title.textContent = heading; text.textContent = body; message.hidden = false;
    connection.textContent = status; connection.dataset.status = 'problem'; stage.dataset.paused = 'true';
  }
  function connectBrowser() {
    if (connecting || !isLive() || !state.screen) return;
    connecting = true;
    connection.textContent = 'Connecting to live browser'; connection.dataset.status = '';
    image.src = streamPath + '?connection=' + Date.now();
  }
  function render(next) {
    state = next;
    document.getElementById('live-request').textContent = state.request;
    document.getElementById('live-url').textContent = state.observation?.url || 'Preparing the browser';
    document.getElementById('live-activity').textContent = state.activity;
    document.getElementById('live-session-status').textContent = state.status;
    if (!isLive()) {
      clearTimeout(retryTimer); image.removeAttribute('src'); connecting = false;
      image.hidden = true;
      document.getElementById('live-session-label').textContent = 'Session ended · review the outcome in Task details';
      notice('This browser session has ended', 'Open Tasks to start another live session. The outcome and saved evidence are available in Task details.', 'Session ended');
    } else if (!state.screen) {
      notice('Preparing Ava’s browser', 'Waiting for the live stream. Saved captures will not be substituted here.', 'Waiting for browser');
    } else {
      connectBrowser();
    }
  }
  image.addEventListener('load', () => {
    if (!isLive()) return;
    image.hidden = false; message.hidden = true; stage.dataset.paused = 'false';
    connection.textContent = 'Live browser stream'; connection.dataset.status = 'live';
  });
  image.addEventListener('error', () => {
    connecting = false;
    if (!isLive()) return;
    notice('Reconnecting to Ava’s browser', 'The live stream was interrupted. Your task continues; this view will reconnect automatically.', 'Reconnecting');
    clearTimeout(retryTimer); retryTimer = setTimeout(connectBrowser, 1500);
  });
  render(state);
  const events = new EventSource('/runs/' + encodeURIComponent(state.run_id) + '/events');
  events.addEventListener('state', event => {
    render(JSON.parse(event.data));
    if (!isLive()) events.close();
  });
  events.onerror = () => {
    if (isLive()) { connection.textContent = 'Task connection reconnecting'; connection.dataset.status = 'problem'; }
  };
  window.addEventListener('pagehide', () => { events.close(); clearTimeout(retryTimer); image.removeAttribute('src'); });
})();
