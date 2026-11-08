(async () => {
  const el = id => document.getElementById(id), dialog = el('home-new');
  let hasProject = false, creating = false;
  function openCreate() {
    el('home-setup').close();
    el('home-new-name').value = '';
    el('home-new-error').textContent = '';
    dialog.showModal(); el('home-new-name').focus();
  }
  window.openHomeProjectIfEmpty = () => { if (hasProject) return false; openCreate(); return true; };
  document.querySelectorAll('[data-new-project]').forEach(button => button.addEventListener('click', openCreate));
  const cancel = () => { if (!creating) dialog.close(); };
  el('home-new-close').onclick = el('home-new-cancel').onclick = cancel;
  dialog.addEventListener('cancel', event => { if (creating) event.preventDefault(); });
  el('home-new-form').addEventListener('submit', async event => {
    event.preventDefault(); if (creating) return;
    const name = el('home-new-name').value.trim();
    if (!/^[A-Za-z0-9_-]{1,60}$/.test(name)) {el('home-new-error').textContent='Use letters, numbers, dashes or underscores.';return;}
    creating=true;
    ['home-new-name','home-new-create','home-new-cancel','home-new-close'].forEach(id => el(id).disabled=true);
    el('home-new-error').textContent='';
    try {
      const response=await fetch('/api/project-create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
      const result=await response.json();
      if(!response.ok)throw Error(result.error || 'Could not create the project.');
      try {localStorage.setItem('clipbench.lastProject',result.name);} catch {}
      location.assign('/editor?project='+encodeURIComponent(result.name));
    } catch(error) {
      el('home-new-error').textContent=error.message;
      creating=false;
      ['home-new-name','home-new-create','home-new-cancel','home-new-close'].forEach(id => el(id).disabled=false);
      el('home-new-name').focus();
    }
  });
  const clean = /^[A-Za-z0-9_-]{1,60}$/;
  const fold = text => { const span = document.createElement('span'); span.textContent = text; return span.innerHTML; };
  const ago = at => { const d = new Date(at * 1000); return Number.isFinite(d.getTime()) ? d.toLocaleDateString(undefined, {month: 'short', day: 'numeric'}) : ''; };
  function projectRow(project, first) {
    const row = document.createElement('a');
    row.className = 'home-row' + (first ? ' first' : '');
    row.href = '/editor?project=' + encodeURIComponent(project.name);
    const clips = project.clips === 1 ? '1 clip' : project.clips + ' clips';
    const thumb = typeof project.thumb === 'string' && /^\/(clip-thumb\/[0-9a-f]{64}\.(jpg|png|webp)|video-thumb\/[0-9a-f]{12}\.jpg)$/.test(project.thumb) ? `<img src="${project.thumb}" alt="">` : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h6l2 2h8v12H4z"/></svg>';
    row.innerHTML = `<div class="home-thumb">${thumb}</div><div class="grow"><strong>${fold(project.name)}</strong><small>${clips} · ${ago(project.updated_at)}</small></div>`;
    row.addEventListener('click', () => { try { localStorage.setItem('clipbench.lastProject', project.name); } catch {} });
    return row;
  }
  try {
    const response = await fetch('/api/home-recent');
    if (!response.ok) return;
    const projects = (await response.json()).filter(p => p && clean.test(p.name));
    if (!projects.length) return;
    let list = projects, preferred = '';
    try { preferred = localStorage.getItem('clipbench.lastProject') || ''; } catch {}
    const last = projects.find(p => p.name === preferred);
    if (last) list = [last, ...projects.filter(p => p !== last)];
    hasProject = true;
    el('home-recent').replaceChildren(...list.map((p, i) => projectRow(p, i === 0)));
    el('home-project').hidden = false;
    document.body.classList.add('has-project');
    el('home-skip').hidden = true;
    document.addEventListener('keydown', event => {
      if (event.key === 'Enter' && document.activeElement === document.body && !document.querySelector('dialog[open]')) el('home-recent').firstElementChild.click();
    });
    liveNow();
  } catch { /* Account access and the editor remain available when project lookup fails. */ }

  // Followed streamers who are live: checked one at a time (each is a yt-dlp run) and shown as each answers.
  async function liveNow() {
    let followed;
    try { followed = await (await fetch('/api/streamers')).json(); } catch { return; }
    if (!Array.isArray(followed)) return;
    for (const s of followed) {
      if (document.hidden) break;
      let got;
      try {
        const r = await fetch('/api/streamers/live', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url: s.url})});
        got = await r.json();
      } catch { continue; }
      if (!got || got.live !== true || !/^https:\/\//.test(got.watch || '')) continue;
      const name = s.name.startsWith('UC') && s.url.includes('/channel/') ? 'Channel' : s.name;
      const row = document.createElement('a');
      row.className = 'home-row';
      row.href = '/editor?watch=' + encodeURIComponent(got.watch);
      row.innerHTML = `<div class="home-av" aria-hidden="true">${fold(name.charAt(0).toUpperCase())}</div><div class="grow"><strong>${fold(name)}<span class="home-tag">LIVE</span></strong><small>${fold(got.title || 'Streaming now')}</small></div><span class="home-go">Open stream</span>`;
      el('home-live-rows').append(row);
      el('home-live').hidden = false;
    }
  }
})();
