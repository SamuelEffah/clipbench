(() => {
  const el = id => document.getElementById(id);
  const profiles = [
    {name:'Default', initial:'D', channel:'YouTube channel', state:'Existing connection stays unchanged', projects:[], sample:false},
    {name:'Gaming', initial:'G', channel:'@rinpew Gaming', state:'YouTube · sample connection', sample:true, projects:[{name:'Ranked highlights', clips:8, date:'Today', icon:'R'}, {name:'Stream best moments', clips:12, date:'Yesterday', icon:'S'}, {name:'Weekend session', clips:6, date:'Nov 14', icon:'W'}, {name:'Clutch plays', clips:9, date:'Nov 12', icon:'C'}, {name:'First impressions', clips:4, date:'Nov 10', icon:'F'}, {name:'Community night', clips:7, date:'Nov 8', icon:'N'}]},
    {name:'Podcast', initial:'P', channel:'@rinpew Talks', state:'YouTube · sample connection', sample:true, projects:[{name:'Episode 24 — The creative process', clips:5, date:'Today', icon:'E'}, {name:'Conversations worth keeping', clips:3, date:'Nov 12', icon:'C'}]}
  ];
  let active = profiles[0], mode = 'profile';
  function node(tag, className, text) { const n = document.createElement(tag); n.className = className; if (text !== undefined) n.textContent = text; return n; }
  function paint() {
    el('profile-context').textContent = active.name + ' /'; el('sample-label').hidden = !active.sample;
    el('channel-name').textContent = active.sample ? active.channel : 'Add your channel';
    el('channel-state').textContent = active.sample ? 'Publishing channel' : 'Publish clips directly to YouTube';
    el('connection-status').textContent = active.sample ? 'Connected' : 'Not connected';
    el('connection-status').classList.toggle('is-connected', !!active.sample);
    el('channel-action').textContent = active.sample ? 'Manage connection ↗' : 'Connect YouTube';
    el('channel-action').classList.toggle('needs-connection', !active.sample);
    el('connection-note').textContent = active.sample ? 'Sample connection' : '';
    el('project-count').textContent = active.projects.length; el('empty-projects').hidden = !!active.projects.length;
    el('home-recent').replaceChildren(...active.projects.map(p => {
      const row = node('button', 'home-row'); row.type = 'button'; row.dataset.kind = active.name === 'Podcast' ? 'podcast' : active.name === 'Gaming' ? 'gaming' : 'default';
      const grow = node('span', 'grow'); grow.append(node('strong', '', p.name), node('small', '', `${p.clips} ${p.clips === 1 ? 'clip' : 'clips'} · ${p.date}`));
      const cover = node('span', 'project-cover'); const art = node('span', 'cover-art', p.icon || 'CB'); cover.append(art, node('span', 'cover-format', '9:16'), node('span', 'cover-open', 'Open project ↗')); row.append(cover, grow, node('span', 'project-arrow', '↗'));
      row.onclick = () => { el('preview-status').textContent = `“${p.name}” belongs to ${active.name}. Opening the editor will be wired up in the full feature.`; }; return row;
    }));
    el('profile-options').replaceChildren(...profiles.map(p => {
      const option = node('button', 'profile-option'); option.type = 'button'; option.setAttribute('aria-pressed', String(p === active));
      const grow = node('span', 'grow'); grow.append(node('strong', '', p.name), node('small', '', p.sample ? p.channel : 'Personal workspace'));
      const avatar = node('span', 'profile-avatar', p.sample ? undefined : p.initial);
      avatar.setAttribute('aria-hidden', 'true');
      if (p.sample) {
        avatar.classList.add('platform-avatar');
        const logo = document.querySelector('.youtube-avatar svg').cloneNode(true);
        logo.setAttribute('width', '18'); logo.setAttribute('height', '13');
        avatar.append(logo);
        option.setAttribute('aria-label', p.name + ', YouTube' + (p === active ? ', selected' : ''));
      }
      avatar.dataset.tone = p.name === 'Gaming' ? 'gaming' : p.name === 'Podcast' ? 'podcast' : 'default';
      const detail = node('span', 'option-detail'); detail.append(node('span', 'option-count', `${p.projects.length} ${p.projects.length === 1 ? 'project' : 'projects'}`), node('span', 'check', p === active ? '✓' : ''));
      option.append(avatar, grow, detail);
      option.onclick = () => { active = p; paint(); el('preview-status').textContent = 'Preview only · changes stay in this tab'; [...el('profile-options').children][profiles.indexOf(p)].focus(); }; return option;
    }));
  }
  function openDialog(nextMode) {
    mode = nextMode; const isProfile = mode === 'profile';
    el('dialog-title').textContent = isProfile ? 'Create profile' : 'New project'; el('name-label').textContent = isProfile ? 'Profile name' : 'Project name';
    el('preview-name').value = ''; el('preview-name').placeholder = isProfile ? 'e.g. Gaming' : 'Name your project';
    el('dialog-hint').textContent = isProfile ? 'Give this channel or creative space its own projects.' : `This project will belong to ${active.name}.`;
    el('dialog-submit').textContent = isProfile ? 'Create profile' : 'Create project'; el('preview-dialog').showModal(); el('preview-name').focus();
  }
  el('add-profile').onclick = () => openDialog('profile'); el('new-project').onclick = () => openDialog('project');
  el('dialog-close').onclick = el('dialog-cancel').onclick = () => el('preview-dialog').close();
  el('preview-form').onsubmit = event => {
    event.preventDefault(); const name = el('preview-name').value.trim(); if (!name) {el('preview-name').focus(); return;}
    if (mode === 'profile') { active = {name, initial:Array.from(name)[0].toUpperCase(), channel:'YouTube channel', state:'Not connected', projects:[], sample:false}; profiles.push(active); }
    else active.projects.unshift({name, clips:0, date:'Just now'});
    paint(); el('preview-dialog').close(); el('preview-status').textContent = 'Created in preview only · changes stay in this tab';
  };
  const connections = open => { el('connections-panel').hidden = !open; el('connections-toggle').setAttribute('aria-expanded', String(open)); };
  el('connections-toggle').onclick = () => connections(el('connections-panel').hidden);
  el('connections-close').onclick = () => { connections(false); el('connections-toggle').focus(); };
  document.addEventListener('click', event => { if (!event.target.closest('#connections-panel, #connections-toggle')) connections(false); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !el('connections-panel').hidden) { connections(false); el('connections-toggle').focus(); } });
  el('channel-action').onclick = () => { el('connection-note').textContent = `In the full feature, ${active.name} will have its own YouTube connection and branding settings.`; };
  paint();
  fetch('/api/home-recent').then(r => {if (!r.ok) throw Error(); return r.json();}).then(projects => {
    if (!Array.isArray(projects)) return;
    profiles[0].projects = projects.filter(p => p && typeof p.name === 'string').map(p => ({name:p.name, clips:p.clips || 0, date:new Date(p.updated_at * 1000).toLocaleDateString(undefined, {month:'short', day:'numeric'})})); paint();
  }).catch(() => { el('preview-status').textContent = 'Could not load existing projects. Sample profiles are still available.'; });
})();
