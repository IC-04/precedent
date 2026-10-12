(() => {
  const {chapters} = JSON.parse(document.getElementById('guide-data').textContent);
  const audio = document.getElementById('tour-audio');
  const player = document.querySelector('.tour-player');
  const start = document.getElementById('tour-start'), toggle = document.getElementById('tour-toggle');
  const stopButton = document.getElementById('tour-stop'), mute = document.getElementById('tour-mute');
  const select = document.getElementById('tour-chapter'), seek = document.getElementById('tour-seek');
  const status = document.getElementById('tour-status'), time = document.getElementById('tour-time');
  let index = 0, generation = 0, mediaFailed = false;
  let active = document.querySelector('.guide-task').getAttribute('href').startsWith('/runs/');
  const followButton = document.getElementById('tour-follow');
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  let follow = !motion.matches, storyIndex = -1, sceneOnly = false, followOff = false;

  // ---- Ava's travel ---------------------------------------------------------------
  // One Ava. Between transitions she sits in-flow inside the chapter's perch, so page
  // scrolling, resizing and font loading move her with the layout and need no work.
  // A transition lifts her into a fixed layer and drives both the viewport scroll and
  // her position from one clock, then seats her in the next perch. Interrupting it
  // retargets from where she visibly is; nothing snaps back to an old origin.
  const heroMount = document.querySelector('.guide-hero .ava-companion');
  const heroAva = heroMount.querySelector('.ava');
  const traveler = document.createElement('div');
  traveler.className = 'tour-guide-ava'; traveler.setAttribute('aria-hidden', 'true'); traveler.hidden = true;
  const hop = document.createElement('div'); hop.className = 'tour-hop';
  const figure = heroAva.cloneNode(true);
  figure.removeAttribute('role'); figure.removeAttribute('aria-label'); figure.dataset.pose = 'idle';
  hop.append(figure); traveler.append(hop); document.body.append(traveler);
  let flight = null;  // {frame, x, y, scale, done}
  const perch = i => document.querySelector(`#${chapters[i].id} .story-perch`);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const ease = t => t < .5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
  const pose = name => { figure.dataset.pose = name; };
  const touring = () => !player.hidden && storyIndex >= 0;
  function hideHero(on) {
    heroAva.dataset.guided = on ? '1' : '';
    heroMount.classList.toggle('ava-departed', on);
  }
  function seat(target) {
    traveler.classList.remove('flying'); traveler.style.transform = ''; hop.style.transform = '';
    traveler.hidden = false; target.append(traveler);
  }
  function visualBox() {
    // Where Ava is on screen right now: mid-flight, seated, or still in the hero.
    if (flight) return {x: flight.x, y: flight.y, scale: flight.scale};
    const node = traveler.isConnected && !traveler.hidden && traveler.parentElement !== document.body ? traveler : heroAva;
    const box = node.getBoundingClientRect(), base = perchWidth();
    return {x: box.left, y: box.top, scale: box.width / base};
  }
  const perchWidth = () => perch(0).getBoundingClientRect().width || 90;
  function cancelFlight(settle = true) {
    if (!flight) return;
    cancelAnimationFrame(flight.frame);
    const current = flight; flight = null;
    if (settle) seat(current.target);
    current.done();
  }
  function scrollTarget(section) {
    // A chapter may name what the tour should frame (the Tribunal frames its scene, so the
    // dialogue stays above the tour player); otherwise the chapter's heading.
    const anchor = section.querySelector('[data-scroll-anchor]') || section;
    const margin = parseFloat(getComputedStyle(anchor).scrollMarginTop) || 0;
    const max = document.documentElement.scrollHeight - innerHeight;
    let offset = margin;
    if (anchor !== section) {
      // Centre the whole stage in the room between the header and the tour player, so no
      // line of the scene is hidden behind the player. Too tall: keep its lower edge clear.
      const floor = (player.hidden ? innerHeight : player.getBoundingClientRect().top) - 10;
      const room = floor - margin, height = anchor.offsetHeight;
      offset = height <= room ? margin + (room - height) / 2 : floor - height;
    }
    return clamp(anchor.getBoundingClientRect().top + scrollY - offset, 0, Math.max(0, max));
  }
  function fly(next, {scroll = follow, onSeen} = {}) {
    const target = perch(next), section = document.getElementById(chapters[next].id);
    const from = visualBox();
    const retarget = Boolean(flight);
    if (flight) { cancelAnimationFrame(flight.frame); const old = flight; flight = null; old.done(); }
    hideHero(true);
    if (motion.matches || document.hidden) {
      if (scroll) window.scrollTo({top: scrollTarget(section), behavior: 'instant'});
      seat(target); onSeen?.(); return Promise.resolve();
    }
    const width = perchWidth();
    const height = traveler.getBoundingClientRect().height || width * 1.05;
    // Start from her visible position; if she is off screen, enter from the nearest edge.
    // The tour player owns the bottom of the screen; she emerges above it, never behind it.
    const floor = player.hidden ? innerHeight : player.getBoundingClientRect().top;
    from.y = clamp(from.y, -height * from.scale * .6, floor - height * from.scale * .7);
    // Place her at the start before she joins the fixed layer: no frame at the origin.
    traveler.style.transform = `translate3d(${from.x}px,${from.y}px,0) scale(${from.scale})`;
    traveler.classList.add('flying'); traveler.hidden = false;
    document.body.append(traveler);
    let scrollFrom = scrollY, scrollTo = scroll ? scrollTarget(section) : scrollY;
    const first = target.getBoundingClientRect();
    const distance = Math.hypot(first.left - from.x, first.top - (scrollTo - scrollFrom) - from.y);
    const duration = 640 + Math.min(520, distance * .28);
    let lift = retarget ? 0 : .14, began = performance.now(), scrolling = scroll;
    const land = .86, arc = Math.min(70, 26 + distance * .05);
    let seen = false;
    return new Promise(resolve => {
      flight = {x: from.x, y: from.y, scale: from.scale, target, done: resolve};
      const step = now => {
        if (!flight) return;
        if (scrolling && !follow) {
          // The reader took over: stop scrolling now and land from where she is.
          scrolling = false; lift = 0; began = now;
          Object.assign(from, {x: flight.x, y: flight.y, scale: flight.scale});
        }
        const t = Math.min(1, (now - began) / duration);
        // Read layout once per frame, then write. Scrolling and travel share one clock,
        // and she travels in screen space to where the perch will be when the scroll ends.
        const box = target.getBoundingClientRect(), current = scrollY;
        const wanted = scrolling ? scrollFrom + (scrollTo - scrollFrom) * ease(t) : current;
        const end = scrolling ? scrollTo : current;
        const goal = {x: box.left, y: box.top + current - end};
        const q = t <= lift ? 0 : t >= land ? 1 : ease((t - lift) / (land - lift));
        const x = from.x + (goal.x - from.x) * q;
        const y = Math.max(Math.min(6, from.y, goal.y), from.y + (goal.y - from.y) * q - arc * Math.sin(Math.PI * q));
        const scale = from.scale + (1 - from.scale) * q;
        flight.x = x; flight.y = y; flight.scale = scale;
        traveler.style.transform = `translate3d(${x}px,${y}px,0) scale(${scale})`;
        // Anticipation squash, a lean into the travel, a small landing, then calm.
        let squash = 'none';
        if (t < lift) { const k = Math.sin(Math.PI * t / lift); squash = `scale(${1 + .06 * k},${1 - .1 * k})`; }
        else if (t < land) { const k = Math.sin(Math.PI * q); squash = `rotate(${(goal.x >= from.x ? 1 : -1) * 7 * k}deg) scale(${1 - .03 * k},${1 + .05 * k})`; }
        else { const k = Math.sin(Math.PI * (t - land) / (1 - land)); squash = `scale(${1 + .07 * k},${1 - .09 * k})`; }
        hop.style.transform = squash;
        if (wanted !== current) window.scrollTo({top: wanted, behavior: 'instant'});
        if (!seen && t >= .7) { seen = true; onSeen?.(); }
        if (t < 1) flight.frame = requestAnimationFrame(step);
        else { flight = null; seat(target); if (!seen) onSeen?.(); resolve(); }
      };
      flight.frame = requestAnimationFrame(step);
    });
  }
  function visitStory(next, options = {}) {
    storyIndex = next;
    document.body.classList.add('tour-wandering');
    document.querySelectorAll('.guide-section').forEach(section => {
      section.classList.toggle('story-current', section.id === chapters[next].id);
    });
    return fly(next, options);
  }
  function finishStory() {
    storyIndex = -1; cancelFlight(false); traveler.hidden = true; hideHero(false);
    document.body.classList.remove('tour-wandering');
    document.querySelectorAll('.story-current, .beat-current').forEach(node => node.classList.remove('story-current', 'beat-current'));
  }
  function setFollow(on, manual = false) {
    follow = on; followButton.setAttribute('aria-pressed', String(on));
    followButton.textContent = on ? 'Auto-scroll on' : 'Follow Ava';
    document.getElementById('tour-follow-hint').textContent = on
      ? 'Ava follows the story. Scroll yourself to take control.'
      : manual ? 'You’re in control for this chapter. Ava picks up the next one.' : 'Read at your own pace.';
  }
  function storyProgress() {
    if (storyIndex < 0 || !Number.isFinite(audio.duration)) return;
    const cues = chapters[index].cues;
    if (cues) {  // a dialogue: the line whose start time has passed drives the scene
      scene.stop();
      let line = 0;
      cues.forEach((start, i) => { if (audio.currentTime + 0.05 >= start) line = i; });
      scene.show(line);
      return;
    }
    const beats = [...document.querySelectorAll(`#${chapters[index].id} [data-beat]`)];
    const beat = Math.min(beats.length - 1, Math.floor(audio.currentTime / audio.duration * beats.length));
    beats.forEach((node, i) => node.classList.toggle('beat-current', i === beat));
  }
  followButton.addEventListener('click', () => { setFollow(!follow); followOff = !follow; if (follow && storyIndex >= 0) visitStory(index, {scroll: true}); });
  function manualScroll(event) {
    if (player.hidden || !follow || event.target.closest?.('.tour-player')) return;
    if (event.type === 'keydown' && (!['ArrowDown','ArrowUp','PageDown','PageUp','Home','End',' '].includes(event.key) || event.target.closest('button,input,select,textarea,a,summary'))) return;
    setFollow(false, true);  // the running transition stops scrolling at once and still lands
  }
  window.addEventListener('wheel', manualScroll, {passive:true});
  window.addEventListener('touchmove', manualScroll, {passive:true});
  window.addEventListener('keydown', manualScroll);
  motion.addEventListener('change', () => { if (motion.matches) { setFollow(false); cancelFlight(); } });
  setFollow(follow);

  // ---- narration ------------------------------------------------------------------
  const clock = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  function speaking(on) {
    document.body.classList.toggle('tour-speaking', on);
    if (!chapters[index].cues) pose(on ? 'speak' : 'idle');
    toggle.textContent = on ? 'Pause' : 'Play';
    toggle.setAttribute('aria-label', on ? 'Pause narration' : 'Play narration');
  }
  function progress() {
    const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
    seek.disabled = !duration || mediaFailed;
    seek.max = String(duration || 100); seek.value = String(audio.currentTime || 0);
    time.textContent = `${clock(audio.currentTime || 0)} / ${clock(duration)}`;
    storyProgress();
  }
  function unavailable() {
    mediaFailed = true; finishStory();
    speaking(false); toggle.disabled = true; seek.disabled = true;
    status.textContent = 'Audio unavailable · the transcript is below';
    player.querySelector('details').open = true;
  }
  function load(next) {
    generation++; audio.pause(); mediaFailed = false; index = next; select.value = String(index);
    document.getElementById('tour-caption').textContent = chapters[index].narration;
    audio.removeAttribute('src');
    if (chapters[index].audio) audio.src = chapters[index].audio;
    audio.load(); progress();
    toggle.disabled = active || !chapters[index].audio;
    status.textContent = active ? 'Tour paused while Ava works' : `${index + 1} of ${chapters.length} · ${chapters[index].label}`;
    if (!chapters[index].audio && !active) unavailable();
  }
  async function play() {
    if (active || !chapters[index].audio) return;
    const version = generation;
    if (audio.readyState < 3) status.textContent = 'Loading narration…';
    try { await audio.play(); }
    catch (error) { if (version === generation && error.name !== 'AbortError') unavailable(); }
  }
  // Travel to a chapter and begin its clip once the move can be seen, not after a wait.
  function goTo(next, {resume = true, scroll = follow} = {}) {
    const version = generation;
    visitStory(next, {scroll, onSeen: () => { if (resume && version === generation && !document.hidden) play(); }});
  }
  function stop() {
    generation++; audio.pause(); speaking(false); load(0); finishStory();
    status.textContent = active ? 'Tour paused while Ava works' : 'Stopped · ready to restart';
  }
  function setActive(url) {
    const wasActive = active; active = Boolean(url);
    document.querySelectorAll('.guide-task').forEach(link => {
      link.href = url || '/#request'; link.textContent = active ? 'Return to Ava’s task ↗' : 'Give Ava a task ↗';
    });
    if (active) {
      if (!audio.paused) audio.pause();
      generation++; speaking(false); finishStory(); toggle.disabled = true;
      status.textContent = 'Tour paused while Ava works';
      start.textContent = 'Ava is working · return to task';
    } else {
      start.textContent = '▷ Let Ava show you around';
      if (wasActive) { toggle.disabled = !chapters[index].audio; status.textContent = 'Ready to resume'; }
    }
  }
  async function checkActive() {
    try {
      const result = await fetch('/watch/state', {cache:'no-store', signal:AbortSignal.timeout(3000)});
      if (!result.ok) return false;
      const state = await result.json(); setActive(state.run_url); return true;
    } catch { return false; }
  }
  start.disabled = false;
  start.addEventListener('click', async () => {
    sceneOnly = false;
    if (active) { location.assign(document.querySelector('.guide-task').href); return; }
    player.hidden = false;
    if (!await checkActive()) { status.textContent = 'Cannot check Ava’s task · retry when connected'; return; }
    if (active) return;
    if (!audio.getAttribute('src')) load(index);
    if (!chapters[index].audio) { unavailable(); return; }
    goTo(index, {scroll: follow});
  });
  toggle.addEventListener('click', async () => {
    if (!audio.paused) { audio.pause(); return; }
    if (!await checkActive()) { status.textContent = 'Cannot check Ava’s task · retry when connected'; return; }
    if (storyIndex !== index) goTo(index); else play();
  });
  stopButton.addEventListener('click', stop);
  mute.addEventListener('click', () => {
    audio.muted = !audio.muted; mute.setAttribute('aria-pressed', String(audio.muted));
    mute.textContent = audio.muted ? 'Unmute' : 'Mute';
    mute.setAttribute('aria-label', audio.muted ? 'Unmute narration' : 'Mute narration');
  });
  select.addEventListener('change', () => {
    sceneOnly = false;
    const resume = !audio.paused; load(Number(select.value));
    goTo(index, {resume, scroll: true});
  });
  // Scrubbing changes the position within a chapter; it never moves the viewport.
  seek.addEventListener('input', () => { audio.currentTime = Number(seek.value); progress(); });
  audio.addEventListener('playing', () => {
    if (active || document.hidden) { audio.pause(); return; }
    if (storyIndex !== index) visitStory(index);
    storyProgress(); speaking(true); status.textContent = `${index + 1} of ${chapters.length} · ${chapters[index].label}`;
  });
  audio.addEventListener('pause', () => { speaking(false); if (!audio.ended && !active && !mediaFailed) status.textContent = 'Paused · continue when ready'; });
  audio.addEventListener('waiting', () => { speaking(false); if (!mediaFailed) status.textContent = 'Buffering narration…'; });
  audio.addEventListener('error', () => { if (audio.getAttribute('src')) unavailable(); });
  audio.addEventListener('loadedmetadata', progress); audio.addEventListener('timeupdate', progress);
  audio.addEventListener('ended', async () => {
    speaking(false);
    if (sceneOnly) { sceneOnly = false; status.textContent = 'Scene complete · continue the tour from any chapter'; return; }
    if (index < chapters.length - 1) {
      if (!await checkActive()) { status.textContent = 'Tour paused · connection unavailable'; return; }
      if (!active) {
        if (!follow && !followOff && !motion.matches) setFollow(true);
        load(index + 1); goTo(index);
      }
    } else { status.textContent = 'Tour complete · give Ava an outcome'; toggle.textContent = 'Replay chapter'; pose('greet'); }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { audio.pause(); cancelFlight(); } else checkActive();
  });
  window.addEventListener('pagehide', stop);
  document.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
    if (!link.getAttribute('href').startsWith('#')) { audio.pause(); cancelFlight(); }
  }));
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) {
      document.querySelectorAll('.guide-outline a').forEach(link => {
        if (link.hash === `#${entry.target.id}`) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      });
    }
  }, {rootMargin:'-5% 0px -65% 0px'});
  document.querySelectorAll('.guide-section').forEach(section => observer.observe(section));
  setActive(active ? document.querySelector('.guide-task').getAttribute('href') : null);
  let poll;
  window.addEventListener('pageshow', () => {
    clearInterval(poll); checkActive();
    poll = setInterval(() => { if (!document.hidden) checkActive(); }, 4000);
  });
  window.addEventListener('pagehide', () => clearInterval(poll));

  // ---- the page around the tour ------------------------------------------------------
  // Everything below is presentation of recorded evidence: reveals, the replayed browser
  // frames, the loop's sticky stage list, Ava following the reader, and the Tribunal scene.
  // None of it starts audio; only the tour and "Play the scene" do, on an explicit click.
  const still = motion.matches;
  document.documentElement.classList.add('gx-js');

  const reveal = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) { entry.target.classList.add('in'); reveal.unobserve(entry.target); }
  }, {rootMargin: '0px 0px -12% 0px'});
  document.querySelectorAll('[data-beat]').forEach(node => reveal.observe(node));

  // Numbers count up once, from zero to the recorded value.
  const counted = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      counted.unobserve(entry.target);
      const node = entry.target, end = Number(node.dataset.count);
      if (still || !Number.isFinite(end)) continue;
      const began = performance.now();
      const tick = now => {
        const t = Math.min(1, (now - began) / 1100);
        node.textContent = String(Math.round(end * (1 - (1 - t) ** 3)));
        if (t < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }
  }, {threshold: .6});
  document.querySelectorAll('[data-count]').forEach(node => counted.observe(node));

  // The hero replays Ava's own recorded browser frames with their recorded captions.
  const film = document.querySelector('.gx-film');
  if (film) {
    const frames = [...film.querySelectorAll('.gx-frames img')];
    const ticks = [...film.querySelectorAll('.gx-film-ticks i')];
    const caption = document.getElementById('film-caption'), clock = document.getElementById('film-time');
    let at = 0, timer = null, visible = true;
    const showFrame = i => {
      at = i;
      frames.forEach((img, n) => img.classList.toggle('on', n === i));
      ticks.forEach((tick, n) => tick.classList.toggle('on', n <= i));
      caption.textContent = frames[i].dataset.caption;
      clock.textContent = `${Math.round(Number(frames[i].dataset.t))} s into the run`;
    };
    const run = () => {
      clearTimeout(timer);
      if (still || !visible || document.hidden) return;
      timer = setTimeout(() => { showFrame((at + 1) % frames.length); run(); }, at === frames.length - 1 ? 3600 : 1900);
    };
    new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; run(); }, {threshold: .25}).observe(film);
    document.addEventListener('visibilitychange', run);
    ticks.forEach((tick, n) => tick.addEventListener('click', () => { showFrame(n); run(); }));
    showFrame(still ? frames.length - 1 : 0);
  }

  // Native Google: the same recorded run, its tab strip following the frame on screen.
  const tabbed = document.querySelector('.gx-tabbed');
  if (tabbed) {
    const shots = [...tabbed.querySelectorAll('.gx-native-frames img')];
    const tabs = [...tabbed.querySelectorAll('.gx-tab')];
    const line = document.getElementById('native-caption');
    let at = 0, timer = null, seen = false;
    const showShot = i => {
      at = i;
      shots.forEach((img, n) => img.classList.toggle('on', n === i));
      tabs.forEach(tab => tab.classList.toggle('on', tab.dataset.app === shots[i].dataset.app));
      line.textContent = shots[i].dataset.caption;
    };
    const cycle = () => {
      clearTimeout(timer);
      if (still || !seen || document.hidden) return;
      timer = setTimeout(() => { showShot((at + 1) % shots.length); cycle(); }, 2600);
    };
    new IntersectionObserver(([entry]) => { seen = entry.isIntersecting; cycle(); }, {threshold: .3}).observe(tabbed);
    tabs.forEach(tab => tab.addEventListener('click', () => {
      const i = shots.findIndex(img => img.dataset.app === tab.dataset.app);
      if (i >= 0) { showShot(i); cycle(); }
    }));
    showShot(0);
  }

  // The loop: the stage list follows whichever recorded artifact is in the middle.
  const steps = [...document.querySelectorAll('.gx-step')];
  const stepNav = [...document.querySelectorAll('.gx-steps-nav li')];
  const stepping = new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) {
      const n = entry.target.dataset.step;
      steps.forEach(step => step.classList.toggle('on', step === entry.target));
      stepNav.forEach(item => item.classList.toggle('on', item.dataset.step === n));
    }
  }, {rootMargin: '-45% 0px -45% 0px'});
  steps.forEach(step => stepping.observe(step));

  // The Tribunal scene: one state per dialogue line, driven by the voiced clip's cues or,
  // without audio, by a reading clock. Loki's pose and Ava's come from the script.
  const stage = document.getElementById('scene');
  const loki = document.getElementById('scene-loki');
  const lines = stage ? [...stage.querySelectorAll('.gx-bubble')] : [];
  const count = document.getElementById('scene-count');
  const tribunalIndex = chapters.findIndex(c => c.dialogue);
  let reading = null;
  const scene = {
    show(n) {
      if (!stage) return;
      const line = lines[n];
      // Ava may land after her first line began: her pose is applied on every update.
      if (line && traveler.parentElement?.closest('#scene')) pose(line.dataset.pose || 'idle');
      if (Number(stage.dataset.line) === n) return;
      stage.dataset.line = String(n);
      const latest = {};
      lines.forEach((item, i) => { if (i <= n) latest[item.classList.contains('from-loki') ? 'loki' : 'ava'] = i; });
      lines.forEach((item, i) => {
        item.classList.toggle('now', i === n);
        item.classList.toggle('shown', Object.values(latest).includes(i));
      });
      if (count) count.textContent = `${n + 1} / ${lines.length}`;
      if (!line) return;
      if (loki) loki.dataset.pose = line.dataset.loki || 'idle';
    },
    read() {  // the text version: about 2.6 words a second, plus a breath between lines
      clearTimeout(reading);
      let n = 0;
      const next = () => {
        scene.show(n);
        const words = lines[n].textContent.split(/\s+/).length;
        n += 1;
        if (n < lines.length) reading = setTimeout(next, 900 + words * 385);
      };
      next();
    },
    stop() { clearTimeout(reading); },
  };
  if (stage) {
    if (still) { stage.classList.add('static'); scene.show(lines.length - 1); }
    let played = false;
    new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !played && !still && player.hidden) { played = true; scene.read(); }
    }, {threshold: .45}).observe(stage);
    document.getElementById('scene-play').addEventListener('click', async () => {
      scene.stop();
      const chapter = chapters[tribunalIndex];
      if (tribunalIndex < 0 || !chapter.audio) {
        if (!still) visitStory(tribunalIndex >= 0 ? tribunalIndex : 0, {scroll: true});
        scene.read();
        return;
      }
      player.hidden = false;
      if (!await checkActive()) { status.textContent = 'Cannot check Ava’s task · retry when connected'; return; }
      if (active) return;
      sceneOnly = !touring();
      load(tribunalIndex);
      stage.dataset.line = '-1';
      goTo(tribunalIndex, {scroll: true});
    });
  }

  // Without the tour, Ava still keeps the reader company: she hops to the chapter in view.
  // The tour owns her as soon as it starts; reduced motion leaves her in the hero.
  const sections = chapters.map(c => document.getElementById(c.id));
  let browseTimer = null;
  const browsing = new IntersectionObserver(entries => {
    if (still || !player.hidden) return;
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const next = sections.indexOf(entry.target);
      clearTimeout(browseTimer);
      browseTimer = setTimeout(() => {
        if (!player.hidden || next === storyIndex) return;
        if (next <= 0) finishStory();
        else visitStory(next, {scroll: false});
      }, 260);
    }
  }, {rootMargin: '-40% 0px -50% 0px'});
  sections.forEach(section => section && browsing.observe(section));
})();
