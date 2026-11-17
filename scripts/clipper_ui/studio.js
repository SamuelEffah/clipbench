(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const LAST_PROFILE = 'clipbench.profile';
  let profiles = [], active = null, generation = 0, mode = 'profile', moving = null, submitting = false;
  let account = null, connecting = null, pollTimer = 0, requestId = 0;
  const node = (tag, cls, text) => { const n = document.createElement(tag); n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
  const remember = (key, value) => { try { localStorage.setItem(key, value); } catch {} };
  const api = async (path, method = 'GET', body) => {
    const response = await fetch(path, {method, headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Error(data.error || 'Could not reach Clipbench. Try again.');
    return data;
  };
  const profileQuery = id => '?profile=' + encodeURIComponent(id);
  const connectionNote = text => { el('connection-note').textContent = text; el('settings-connection-note').textContent = text; };
  const status = text => { el('studio-status').textContent = text; };
  const logo = () => { const svg = document.querySelector('.youtube-avatar svg').cloneNode(true); svg.setAttribute('width','18'); svg.setAttribute('height','13'); return svg; };
  function paintProfiles() {
    el('profile-options').replaceChildren(...profiles.map(profile => {
      const button = node('button', 'profile-option'); button.type = 'button';
      button.setAttribute('aria-current', profile.id === active?.id ? 'true' : 'false');
      button.setAttribute('aria-label', profile.name + (profile.connected ? ', YouTube' : ''));
      const avatar = node('span', 'profile-avatar', profile.connected ? undefined : Array.from(profile.name)[0].toUpperCase());
      avatar.setAttribute('aria-hidden','true'); if (profile.connected) { avatar.classList.add('platform-avatar'); avatar.append(logo()); }
      button.append(avatar, node('span','profile-name',profile.name), node('span','profile-check',profile.id === active?.id ? '✓' : ''));
      button.onclick = () => selectProfile(profile.id);
      const row = node('div','profile-row');
      const settings = node('button','profile-row-settings'); settings.type = 'button';
      settings.setAttribute('aria-label',`Settings for ${profile.name}`); settings.title = `Settings for ${profile.name}`;
      settings.append(el('profile-settings').querySelector('svg').cloneNode(true));
      settings.onclick = async () => { await selectProfile(profile.id); if (active?.id === profile.id) el('profile-settings').click(); };
      row.append(button,settings); return row;
    }));
    el('add-profile').disabled = !active;
    el('profile-settings').disabled = !active;
    el('new-project').disabled = !active;
    el('connections-toggle').disabled = !active;
  }
  let projectList = [];
  const PROJECT_SORT = 'clipbench.projectSort';
  const savedSort = read(PROJECT_SORT);
  if (['recent', 'name-asc', 'name-desc', 'clips'].includes(savedSort)) el('project-sort').value = savedSort;
  function sortProjects(projects, sort) {
    const name = (a, b) => a.name.localeCompare(b.name, undefined, {numeric:true, sensitivity:'base'});
    return [...projects].sort((a, b) => {
      if (sort === 'name-asc') return name(a, b);
      if (sort === 'name-desc') return name(b, a);
      if (sort === 'clips') return (Number(b.clips) || 0) - (Number(a.clips) || 0) || name(a, b);
      return (Number(b.updated_at) || 0) - (Number(a.updated_at) || 0) || name(a, b);
    });
  }
  const sortLabels = {recent:'Last edited', 'name-asc':'Name A–Z', 'name-desc':'Name Z–A', clips:'Most clips'};
  const sortItems = () => [...el('project-sort-menu').querySelectorAll('[data-project-sort]')];
  function paintProjectSort() {
    const value = el('project-sort').value;
    el('project-sort-label').textContent = sortLabels[value] || sortLabels.recent;
    el('project-sort').setAttribute('aria-label', 'Sort projects: ' + (sortLabels[value] || sortLabels.recent));
    sortItems().forEach(button => button.setAttribute('aria-checked', String(button.dataset.projectSort === value)));
  }
  function showProjectSort(open, focus = false) {
    el('project-sort-menu').hidden = !open;
    el('project-sort').setAttribute('aria-expanded', String(open));
    if (open && focus) (sortItems().find(button => button.getAttribute('aria-checked') === 'true') || sortItems()[0]).focus();
  }
  el('project-sort').onclick = () => showProjectSort(el('project-sort-menu').hidden, true);
  el('project-sort').onkeydown = event => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); showProjectSort(true, true); }
  };
  sortItems().forEach(button => { button.onclick = () => {
    el('project-sort').value = button.dataset.projectSort;
    el('project-sort').onchange();
    showProjectSort(false);
    el('project-sort').focus();
  }; });
  el('project-sort-menu').onkeydown = event => {
    const buttons = sortItems(), at = buttons.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); showProjectSort(false); el('project-sort').focus(); }
    else if (event.key === 'Tab') showProjectSort(false);
    else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (at + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next].focus();
    }
  };
  document.addEventListener('click', event => { if (!event.target.closest('.project-sort-control')) showProjectSort(false); });
  paintProjectSort();
  el('project-sort').onchange = () => {
    remember(PROJECT_SORT, el('project-sort').value);
    paintProjectSort();
    closeProjectMenus();
    paintProjects(projectList);
  };
  function paintProjects(projects) {
    projectList = projects;
    el('project-sort').disabled = !projects.length;
    el('empty-projects').hidden = projects.length > 0;
    el('home-recent').replaceChildren(...sortProjects(projects, el('project-sort').value).map(project => {
      const card = node('article','home-row');
      const link = node('a','project-open'); link.href = '/editor?project=' + encodeURIComponent(project.name);
      link.onclick = () => remember('clipbench.lastProject', project.name);
      const cover = node('span','project-cover');
      const fallback = () => {
        cover.classList.add('cover-unavailable');
        const icon = node('span','cover-fallback');
        icon.innerHTML = '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/></svg>';
        cover.prepend(icon);
      };
      if (typeof project.thumb === 'string' && /^\/(clip-thumb\/[0-9a-f]{64}\.(jpg|png|webp)|video-thumb\/[0-9a-f]{12}\.jpg)$/.test(project.thumb)) {
        const img = document.createElement('img'); img.src = project.thumb; img.alt = ''; img.loading = 'lazy';
        img.onerror = () => { img.remove(); fallback(); };
        cover.append(img);
      } else fallback();
      const empty = project.clips === 0 && project.sources === 0;
      if (empty) {
        card.classList.add('empty-project');
        cover.replaceChildren();
        const add = node('a','project-add-videos'); add.href = link.href + '&add=1';
        add.setAttribute('aria-label',`Add videos to ${project.name}`);
        add.append(node('strong','','Add videos'),node('small','','Start your first clip'));
        add.onclick = () => remember('clipbench.lastProject',project.name);
        cover.append(add);
      } else cover.append(node('span','cover-open','Open project ↗'));
      const copy = node('span','project-copy');
      const date = new Date(project.updated_at * 1000).toLocaleDateString(undefined,{month:'short',day:'numeric'});
      copy.append(node('strong','',project.name),node('small','',`${project.clips} ${project.clips === 1 ? 'clip' : 'clips'} · ${date}`));
      if (empty) { card.append(cover); link.append(copy); } else link.append(cover,copy);
      card.append(link);
      const actions = node('div','project-actions');
      const toggle = node('button','project-menu-toggle','•••'); toggle.type = 'button';
      toggle.setAttribute('aria-label',`Actions for ${project.name}`); toggle.setAttribute('aria-expanded','false');
      const menu = node('div','project-menu'); menu.hidden = true;
      for (const [action,label] of [['rename','Rename'],['duplicate','Duplicate'],['move','Move to profile'],['delete','Delete project']]) {
        const button = node('button',action === 'delete' ? 'danger-text' : '',label); button.type = 'button';
        button.onclick = () => { menu.hidden = true; toggle.setAttribute('aria-expanded','false'); openDialog(action,project.name); };
        menu.append(button);
      }
      toggle.onclick = () => { const open = menu.hidden; closeProjectMenus(); menu.hidden = !open; toggle.setAttribute('aria-expanded',String(open)); };
      actions.append(toggle,menu); card.append(actions); return card;
    }));
  }
  function paintAccount() {
    const connected = !!account?.connected;
    const channel = account?.channel || {};
    el('channel-name').textContent = connected ? channel.handle || channel.name || 'YouTube channel' : 'Add your channel';
    el('channel-state').textContent = connected ? 'Publishing channel' : 'Publish clips directly to YouTube';
    el('connection-status').textContent = connected ? 'Connected' : 'Not connected';
    el('connection-status').classList.toggle('is-connected',connected);
    el('channel-action').textContent = connecting ? 'Connecting…' : connected ? 'Open YouTube Studio ↗' : 'Connect YouTube';
    el('channel-action').disabled = !!connecting || !account;
    el('channel-action').classList.toggle('needs-connection',!connected);
    el('disconnect-channel').hidden = !connected;
    el('cancel-signin').hidden = !connecting;
    settingsAccount();
    el('settings-cancel-signin').hidden = !connecting;
    document.querySelector('.settings-connect-feedback').classList.toggle('is-waiting',!!connecting);
  }
  function stopConnect() {
    connecting = null; clearTimeout(pollTimer); requestId++;
    el('signin-link').hidden = true; el('settings-signin-link').hidden = true; paintAccount();
  }
  async function refreshAccount(id = active?.id, token = generation) {
    const next = await api('/api/youtube' + profileQuery(id));
    if (id !== active?.id || token !== generation) return null;
    account = next; const profile = profiles.find(p => p.id === id);
    profile.connected = !!next.connected; profile.channel = next.channel || {};
    paintProfiles(); paintAccount(); settingsAccount(); return next;
  }
  async function selectProfile(id) {
    const next = profiles.find(p => p.id === id); if (!next) return;
    stopConnect(); generation++; const token = generation; active = next; account = null;
    remember(LAST_PROFILE,id); el('profile-context').textContent = next.name;
    connectionNote(''); el('connections-panel').hidden = true;
    el('connections-toggle').setAttribute('aria-expanded','false');
    status('Loading projects…'); el('retry-load').hidden = true;
    el('empty-projects').hidden = true; el('home-recent').replaceChildren();
    projectList = []; el('project-sort').disabled = true; showProjectSort(false);
    paintProfiles(); paintAccount();
    await Promise.all([
      api('/api/home-recent?all=1&profile=' + encodeURIComponent(id)).then(projects => { if (token === generation) { active.projects = projects.length; paintProjects(projects); status(''); } }).catch(error => { if (token === generation) { status(error.message); el('retry-load').hidden = false; } }),
      refreshAccount(id,token).catch(error => { if (token === generation) { connectionNote(error.message); el('channel-action').disabled = false; el('channel-action').textContent = 'Try again'; } })
    ]);
  }
  async function load() {
    el('retry-load').hidden = true; status('Loading profiles…');
    try {
      profiles = await api('/api/profiles');
      if (!profiles.length) throw Error('No profiles found. Restart Clipbench and try again.');
      await selectProfile(profiles.some(p => p.id === read(LAST_PROFILE)) ? read(LAST_PROFILE) : profiles[0].id);
    } catch (error) { status(error.message); el('retry-load').hidden = false; }
  }
  el('retry-load').onclick = () => active ? selectProfile(active.id) : load();
  function closeProjectMenus() {
    document.querySelectorAll('.project-menu').forEach(menu => menu.hidden = true);
    document.querySelectorAll('.project-menu-toggle').forEach(button => button.setAttribute('aria-expanded','false'));
  }
  document.addEventListener('click',event => { if (!event.target.closest('.project-actions')) closeProjectMenus(); });
  document.addEventListener('keydown',event => { if (event.key === 'Escape') closeProjectMenus(); });
  function openDialog(nextMode, project = null) {
    if (!active) return;
    mode = nextMode; moving = project;
    const isProfile = mode === 'profile', isMove = mode === 'move', isDelete = mode === 'delete';
    const titles = {profile:'Create profile',project:'New project',move:'Move project',rename:'Rename project',duplicate:'Duplicate project',delete:'Delete project?'};
    el('dialog-title').textContent = titles[mode];
    el('name-label').textContent = isMove ? 'Destination profile' : isProfile ? 'Profile name' : 'Project name';
    el('name-label').hidden = isDelete;
    el('name-label').htmlFor = isMove ? 'move-profile' : 'studio-name';
    el('studio-name').hidden = isMove || isDelete; el('studio-name').required = !isMove && !isDelete;
    el('studio-name').value = mode === 'rename' ? project : mode === 'duplicate' ? project.slice(0,55) + '-copy' : '';
    el('studio-name').placeholder = isProfile ? 'e.g. Gaming' : 'Name your project';
    el('move-profile').hidden = !isMove;
    el('move-profile').replaceChildren(...profiles.map(p => { const option = node('option','',p.name); option.value = p.id; option.selected = p.id === active.id; return option; }));
    el('dialog-error').textContent = '';
    el('dialog-hint').textContent = isDelete ? `“${project}” and its edits and saved clips will be deleted permanently. Original media files stay on disk.` : isMove ? `Move “${project}” and its edits to another profile.` : isProfile ? 'A separate space for your projects and publishing channel.' : mode === 'duplicate' ? `Make an independent copy of “${project}” in ${active.name}.` : 'Use letters, numbers, dashes or underscores (up to 60 characters).';
    el('dialog-submit').textContent = {profile:'Create profile',project:'Create project',move:'Move project',rename:'Save name',duplicate:'Duplicate project',delete:'Delete project'}[mode];
    el('dialog-submit').classList.toggle('danger',isDelete);
    el('studio-dialog').showModal();
    (isDelete ? el('dialog-cancel') : isMove ? el('move-profile') : el('studio-name')).focus();
    if (mode === 'rename' || mode === 'duplicate') el('studio-name').select();
  }
  el('add-profile').onclick = () => openDialog('profile'); el('new-project').onclick = () => openDialog('project');
  el('dialog-close').onclick = el('dialog-cancel').onclick = () => { if (!submitting) el('studio-dialog').close(); };
  el('studio-dialog').addEventListener('cancel',event => { if (submitting) event.preventDefault(); });
  el('studio-form').onsubmit = async event => {
    event.preventDefault(); if (submitting || !active) return;
    const name = el('studio-name').value.trim();
    if (!['move','delete'].includes(mode) && !name) { el('dialog-error').textContent = 'Enter a name.'; return; }
    if (['project','rename','duplicate'].includes(mode) && !/^[A-Za-z0-9_-]{1,60}$/.test(name)) { el('dialog-error').textContent = 'Use letters, numbers, dashes or underscores (up to 60 characters).'; return; }
    submitting = true; el('dialog-submit').disabled = true; el('dialog-error').textContent = '';
    try {
      if (mode === 'profile') {
        const profile = await api('/api/profiles','POST',{name}); profiles.push({...profile,connected:false,projects:0});
        el('studio-dialog').close(); await selectProfile(profile.id);
      } else if (['rename','duplicate','delete'].includes(mode)) {
        await api('/api/project-' + mode,'POST',mode === 'delete' ? {name:moving} : {from:moving,to:name});
        if (read('clipbench.lastProject') === moving && mode !== 'duplicate') {
          remember('clipbench.lastProject',mode === 'rename' ? name : '');
        }
        el('studio-dialog').close(); await selectProfile(active.id);
        status(mode === 'rename' ? 'Project renamed.' : mode === 'duplicate' ? 'Project duplicated.' : 'Project deleted.');
      } else if (mode === 'move') {
        await api('/api/project-profile','POST',{name:moving,profile:el('move-profile').value}); el('studio-dialog').close(); await selectProfile(active.id);
      } else {
        const project = await api('/api/project-create','POST',{name,profile:active.id});
        remember('clipbench.lastProject',project.name); location.assign('/editor?project='+encodeURIComponent(project.name));
      }
    } catch (error) { el('dialog-error').textContent = error.message; }
    finally { submitting = false; el('dialog-submit').disabled = false; }
  };
  let settingsBusy = false;
  function settingsAccount() {
    el('settings-channel-state').textContent = account?.connected ? account.channel?.handle || account.channel?.name || 'Connected' : 'No channel connected';
    el('settings-channel-action').textContent = connecting ? 'Connecting…' : account?.connected ? 'Manage' : 'Connect';
    el('settings-channel-action').disabled = !!connecting || !account;
  }
  el('profile-settings').onclick = () => {
    if (!active) return;
    el('profile-settings-title').textContent = active.name + ' settings';
    el('profile-name').value = active.name;
    const defaults = {format:'9:16',capSize:50,normalize:false,watermark:true,...active.defaults};
    el('default-format').value = defaults.format;
    el('default-caption-size').value = defaults.capSize;
    el('default-normalize').checked = defaults.normalize;
    el('default-watermark').checked = defaults.watermark;
    settingsAccount(); el('settings-error').textContent = '';
    el('delete-profile-confirm').hidden = true; el('settings-save-actions').hidden = false;
    el('delete-profile').disabled = active.id === 'default' || active.projects > 0;
    el('delete-profile-hint').textContent = active.id === 'default' ? 'Default is your permanent starting profile.' : active.projects > 0 ? 'Move or delete all projects before deleting this profile.' : 'Only empty profiles can be deleted.';
    el('profile-dialog').showModal(); el('profile-name').focus();
  };
  el('settings-close').onclick = el('settings-cancel').onclick = () => { if (!settingsBusy) el('profile-dialog').close(); };
  el('profile-dialog').addEventListener('cancel',event => { if (settingsBusy) event.preventDefault(); });
  el('settings-channel-action').onclick = event => {
    event.stopPropagation();
    if (account?.connected) { el('profile-dialog').close(); connections(true); el('channel-action').focus(); }
    else el('channel-action').click();
  };
  el('profile-form').onsubmit = async event => {
    event.preventDefault(); if (settingsBusy || !el('delete-profile-confirm').hidden) return;
    const name = el('profile-name').value.trim();
    const defaults = {format:el('default-format').value,capSize:Number(el('default-caption-size').value),normalize:el('default-normalize').checked,watermark:el('default-watermark').checked};
    settingsBusy = true; el('save-profile-settings').disabled = true; el('settings-error').textContent = '';
    try {
      await api('/api/profile-settings','POST',{id:active.id,name,defaults});
      active.name = name; active.defaults = defaults;
      el('profile-context').textContent = name; paintProfiles(); el('profile-dialog').close(); status('Profile settings saved.');
    } catch (error) { el('settings-error').textContent = error.message; }
    finally { settingsBusy = false; el('save-profile-settings').disabled = false; }
  };
  el('delete-profile').onclick = () => {
    el('delete-profile-message').textContent = `Delete “${active.name}”? Its settings and saved YouTube connection will be removed. Your YouTube channel stays intact.`;
    el('delete-profile-confirm').hidden = false; el('settings-save-actions').hidden = true; el('keep-profile').focus();
  };
  el('keep-profile').onclick = () => { el('delete-profile-confirm').hidden = true; el('settings-save-actions').hidden = false; };
  el('confirm-delete-profile').onclick = async () => {
    if (settingsBusy) return;
    settingsBusy = true; el('confirm-delete-profile').disabled = true;
    try {
      await api('/api/profile-delete','POST',{id:active.id});
      stopConnect(); profiles = profiles.filter(p => p.id !== active.id);
      el('profile-dialog').close(); await selectProfile('default'); status('Profile deleted.');
    } catch (error) { el('settings-error').textContent = error.message; }
    finally { settingsBusy = false; el('confirm-delete-profile').disabled = false; }
  };
  const connections = open => { el('connections-panel').hidden = !open; el('connections-toggle').setAttribute('aria-expanded',String(open)); };
  el('connections-toggle').onclick = () => connections(el('connections-panel').hidden);
  el('connections-close').onclick = () => { connections(false); el('connections-toggle').focus(); };
  document.addEventListener('click',event => { if (!event.target.closest('#connections-panel, #connections-toggle')) connections(false); });
  document.addEventListener('keydown',event => { if (event.key === 'Escape' && !el('connections-panel').hidden) { connections(false); el('connections-toggle').focus(); } });
  function pollLater() { clearTimeout(pollTimer); if (connecting && !document.hidden) pollTimer = setTimeout(poll,1500); }
  async function poll() {
    if (!connecting || document.hidden) return;
    const current = connecting;
    if (Date.now() - current.started > 180000) { stopConnect(); connectionNote('Sign-in timed out. Try again.'); return; }
    try {
      const next = await refreshAccount(current.profile,current.generation);
      if (connecting !== current) return;
      if (next?.connected) { stopConnect(); connectionNote('YouTube connected.'); return; }
    } catch (error) { if (connecting === current) connectionNote('Could not check sign-in. Retrying…'); }
    if (connecting === current) pollLater();
  }
  el('channel-action').onclick = async () => {
    if (!account) { try { await refreshAccount(); } catch (error) { connectionNote(error.message); } return; }
    if (account.connected) { window.open('https://studio.youtube.com','_blank','noopener,noreferrer'); return; }
    if (!account.configured) { el('setup-message').textContent = account.message || ''; el('youtube-setup').showModal(); return; }
    const popup = window.open('about:blank','_blank'); if (popup) popup.opener = null;
    const profile = active.id, token = generation, id = ++requestId;
    connecting = {profile,generation:token,started:Date.now()}; paintAccount();
    try {
      const {url} = await api('/api/youtube/connect'+profileQuery(profile),'POST',{});
      if (id !== requestId || token !== generation) { popup?.close(); return; }
      const target = new URL(url); if (target.origin !== 'https://accounts.google.com') throw Error('Invalid sign-in link.');
      if (popup && !popup.closed) popup.location.href = target.href;
      el('signin-link').href = target.href; el('signin-link').hidden = false;
      el('settings-signin-link').href = target.href; el('settings-signin-link').hidden = false;
      connectionNote('Finish signing in with Google.'); pollLater();
    } catch (error) { popup?.close(); if (id === requestId) { stopConnect(); connectionNote(error.message); } }
  };
  el('cancel-signin').onclick = () => { stopConnect(); connectionNote(''); };
  el('settings-cancel-signin').onclick = () => el('cancel-signin').click();
  el('disconnect-channel').onclick = async () => {
    const profile = active.id, token = generation; el('disconnect-channel').disabled = true;
    try { await api('/api/youtube/disconnect'+profileQuery(profile),'POST',{}); if (token === generation) { await refreshAccount(profile,token); connectionNote(''); } }
    catch (error) { if (token === generation) connectionNote(error.message); }
    finally { el('disconnect-channel').disabled = false; }
  };
  el('setup-close').onclick = () => el('youtube-setup').close();
  el('setup-recheck').onclick = async () => { try { const next = await refreshAccount(); if (next?.configured) el('youtube-setup').close(); else el('setup-message').textContent = next?.message || 'Setup is not ready yet.'; } catch (error) { el('setup-message').textContent = error.message; } };
  document.addEventListener('visibilitychange',() => { clearTimeout(pollTimer); if (!document.hidden) { if (connecting) poll(); else if (active) refreshAccount().catch(() => {}); } });
  window.addEventListener('pagehide',() => { clearTimeout(pollTimer); });
  paintProfiles(); load();
})();
