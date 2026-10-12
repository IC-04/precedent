(() => {
  const mind = document.querySelector('.mind');
  if (mind?.dataset.validating === 'yes') {
    const initial = document.querySelector('.mind-detail')?.textContent;
    const check = async () => {
      if (document.hidden) return;
      try {
        const response = await fetch(location.href, {cache: 'no-store'});
        if (!response.ok) return;
        const page = new DOMParser().parseFromString(await response.text(), 'text/html');
        if (page.querySelector('.mind-detail')?.textContent !== initial) location.reload();
      } catch (_) { /* Keep the readable last state if the console is temporarily offline. */ }
    };
    setInterval(check, 6000);
  }
})();
