(() => {
  const el = id => document.getElementById(id);
  const action = el('home-action'), label = el('home-action-text');
  const status = el('home-status'), setup = el('home-setup');
  let state = null, timer = 0, generation = 0, connecting = false, started = 0, checking = null;

  async function api(path, method = 'GET') {
    const response = await fetch(path, {method, headers: method === 'POST' ? {'Content-Type': 'application/json'} : {}, ...(method === 'POST' ? {body: '{}'} : {})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not reach the app. Try again.');
    return data;
  }
  function message(text = '') { status.textContent = text; status.hidden = !text; }
  function paint() {
    const connected = !!state?.connected;
    el('home-title').textContent = connected ? 'You’re ready.' : 'Connect your YouTube';
    label.textContent = connected ? 'Open editor' : connecting ? 'Connecting…' : 'Connect YouTube';
    action.disabled = connecting;
    el('home-skip').hidden = connected;
    el('home-disconnect').hidden = !connected;
    el('home-cancel').hidden = !connecting;
  }
  function stop() {
    generation++;
    connecting = false;
    clearTimeout(timer);
    el('home-signin').hidden = true;
    paint();
  }
  function pollLater(id) {
    clearTimeout(timer);
    if (connecting && id === generation && !document.hidden) timer = setTimeout(() => poll(id), 1500);
  }
  async function poll(id) {
    if (!connecting || id !== generation || document.hidden) return;
    if (Date.now() - started >= 180000) {
      stop(); message('Sign-in timed out. You can try again or continue to the editor.'); return;
    }
    try {
      const next = await api('/api/youtube');
      if (!connecting || id !== generation) return;
      state = next;
      if (state.connected) { stop(); message('YouTube connected.'); return; }
    } catch (error) {
      if (id !== generation) return;
      message('Could not check the connection. Retrying…');
    }
    pollLater(id);
  }
  async function refresh() {
    if (checking) return checking;
    const id = generation;
    checking = (async () => {
      try {
        const next = await api('/api/youtube');
        if (id !== generation) return;
        state = next; message();
      } catch (error) { if (id === generation) message(error.message); }
      finally { if (id === generation) paint(); }
    })();
    try { await checking; } finally { checking = null; }
  }
  action.addEventListener('click', async () => {
    if (state?.connected) { if (window.openHomeProjectIfEmpty?.()) return; location.assign('/editor'); return; }
    if (!state) { await refresh(); if (!state) return; }
    if (!state.configured) { el('home-setup-status').textContent = ''; setup.showModal(); return; }
    // Open synchronously from the click so asynchronous API work does not trigger a popup block.
    const popup = window.open('about:blank', '_blank');
    if (popup) popup.opener = null;
    connecting = true; const id = ++generation; started = Date.now(); paint(); message();
    try {
      const {url} = await api('/api/youtube/connect', 'POST');
      if (id !== generation) { popup?.close(); return; }
      const target = new URL(url);
      if (target.origin !== 'https://accounts.google.com') throw new Error('The app returned an invalid sign-in link.');
      if (popup && !popup.closed) popup.location.href = target.href;
      const link = el('home-signin'); link.href = target.href; link.hidden = false;
      message('Finish signing in with Google in the other tab.'); pollLater(id);
    } catch (error) {
      popup?.close();
      if (id === generation) { stop(); message(error.message); }
    }
  });
  el('home-cancel').addEventListener('click', () => { stop(); message(); });
  el('home-disconnect').addEventListener('click', async () => {
    const button = el('home-disconnect'); button.disabled = true;
    try { await api('/api/youtube/disconnect', 'POST'); state = null; stop(); await refresh(); }
    catch (error) { message(error.message); }
    finally { button.disabled = false; }
  });
  el('home-setup-close').addEventListener('click', () => setup.close());
  el('home-recheck').addEventListener('click', async () => {
    const button = el('home-recheck'); button.disabled = true;
    try {
      await refresh();
      if (state?.configured) setup.close();
      else el('home-setup-status').textContent = state?.message || 'Could not check setup. Try again.';
    } finally { button.disabled = false; }
  });
  document.addEventListener('visibilitychange', () => {
    clearTimeout(timer);
    if (!document.hidden) {
      if (connecting) poll(generation);
      else refresh();
    }
  });
  window.addEventListener('pagehide', stop);
  refresh();
})();
