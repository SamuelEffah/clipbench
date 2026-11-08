// Find sounds online: the search button in the Music panel opens this over the workspace. Results come through the
// server (/api/soundbank), play as a preview straight from the site, and + saves a sound into the audio library.
// Depends on app.js (api, $, toast, esc) and audio.js (refreshAudio) and panels.js (paintMusic).
const sbState = {query: "", page: 1, total: 0, sounds: [], busy: false, playing: "", saving: new Set(), saved: new Set()};
const sbPreview = new Audio();
sbPreview.addEventListener("ended", () => { sbState.playing = ""; paintSounds(); });

const sbSoundUrl = file => `https://soundbuttonsworld.com/api/upload/download?id=${encodeURIComponent(file)}`;

function sbRow(s) {
  const row = document.createElement("div");
  row.className = "sbrow";
  const playing = sbState.playing === s.file, saving = sbState.saving.has(s.file), saved = sbState.saved.has(s.file);
  row.innerHTML = `<button class="ico" data-act="play" aria-label="${playing ? "Stop" : "Preview"} ${esc(s.name)}"><svg class="i"><use href="#${playing ? "pause" : "play"}"/></svg></button>` +
    `<span class="sbname" title="${esc(s.name)}">${esc(s.name)}</span>` +
    `<button class="ico" data-act="add" aria-pressed="${saved}" ${saving || saved ? "disabled" : ""} aria-label="${saved ? "Added" : "Add"} ${esc(s.name)} to your sounds" title="${saved ? "In your sounds" : saving ? "Saving" : "Add to your sounds"}"><svg class="i"><use href="#${saved ? "c-check" : "plus"}"/></svg></button>`;
  row.querySelector('[data-act="play"]').onclick = () => previewSound(s);
  row.querySelector('[data-act="add"]').onclick = () => saveSound(s);
  return row;
}

let sbRows = new Map(), sbMore = null;
function paintSounds() {
  const list = $("sbList");
  const more = sbState.sounds.length < sbState.total;
  $("sbCount").textContent = sbState.total ? `${sbState.total.toLocaleString()} sounds` : "";
  if (!sbState.sounds.length) {
    sbRows.clear();
    sbMore = null;
    list.innerHTML = `<p class="hint">${sbState.busy ? "Loading sounds" : sbState.query ? "No sounds match that search." : "No sounds to show."}</p>`;
    return;
  }
  const next = new Map();
  const rows = sbState.sounds.map(s => {
    const key = JSON.stringify([s.name, sbState.playing === s.file, sbState.saving.has(s.file), sbState.saved.has(s.file)]);
    const old = sbRows.get(s.file);
    const entry = old && old.key === key ? old : {key, row: sbRow(s)};
    next.set(s.file, entry);
    return entry.row;
  });
  sbRows = next;
  if (more) {
    const b = Object.assign(sbMore || (sbMore = document.createElement("button")), {className: "sbmore", textContent: sbState.busy ? "Loading" : "Show more", disabled: sbState.busy});
    b.onclick = () => loadSounds(sbState.page + 1);
    rows.push(b);
  }
  if (list.children.length !== rows.length || rows.some((row, i) => list.children[i] !== row)) list.replaceChildren(...rows);
}

let sbPending = null, sbLoading = null, sbSearchVersion = 0;
function loadSounds(page) {
  const request = {page, query: sbState.query, version: sbSearchVersion};
  sbPending = request;
  if (page === 1) sbState.sounds = [];
  sbState.busy = true;
  paintSounds();
  if (sbLoading) return sbLoading;
  sbLoading = (async () => {
    try {
      while (sbPending) {
        const {page, query, version} = sbPending;
        sbPending = null;
        try {
          const out = await api(`/api/soundbank?q=${encodeURIComponent(query)}&page=${page}`);
          if (version !== sbSearchVersion) continue;
          sbState.page = page;
          sbState.total = out.total;
          sbState.sounds = page === 1 ? out.sounds : [...sbState.sounds, ...out.sounds];
        } catch (err) {
          if (version === sbSearchVersion) toast(err.message);
        }
      }
    } finally {
      sbState.busy = false;
      sbLoading = null;
      paintSounds();
    }
  })();
  return sbLoading;
}

function previewSound(s) {
  const stopping = sbState.playing === s.file;
  sbPreview.pause();
  sbState.playing = stopping ? "" : s.file;
  if (!stopping) {
    sbPreview.src = sbSoundUrl(s.file);
    sbPreview.play().catch(() => { sbState.playing = ""; toast("That sound wouldn't play"); paintSounds(); });
  }
  paintSounds();
}

async function saveSound(s) {
  sbState.saving = new Set([...sbState.saving, s.file]);
  paintSounds();
  try {
    await api("/api/soundbank/import", "POST", {file: s.file, name: s.name});
    sbState.saved = new Set([...sbState.saved, s.file]);
    await refreshAudio();
    paintMusic();
    toast(`${s.name} added to your sounds`);
  } catch (err) {
    toast(err.message);
  } finally {
    sbState.saving = new Set([...sbState.saving].filter(f => f !== s.file));
    paintSounds();
  }
}

function closeSounds() {
  sbPreview.pause();
  sbState.playing = "";
  $("soundDlg").close();
}

// The finder replaces the Music panel in place, including its full height.
function anchorToPanel() {
  const r = $("railPop").getBoundingClientRect(), dlg = $("soundDlg");
  Object.assign(dlg.style, {margin: "0", position: "fixed", zIndex: "9", top: `${r.top}px`, left: `${r.left}px`, width: `${r.width}px`, height: `${r.height}px`, maxHeight: "none"});
}
function resizeSoundFinder() {
  if ($("soundDlg").open) anchorToPanel();
}
new ResizeObserver(resizeSoundFinder).observe($("railPop"));
window.addEventListener("resize", resizeSoundFinder);

$("musicFind").onclick = () => {
  $("soundDlg").show();
  anchorToPanel();
  $("sbQuery").focus();
  if (!sbState.sounds.length) loadSounds(1);
};
$("sbClose").onclick = closeSounds;
$("soundDlg").addEventListener("keydown", e => { if (e.key === "Escape") closeSounds(); });
$("soundDlg").addEventListener("close", () => { sbPreview.pause(); sbState.playing = ""; });
$("sbForm").onsubmit = e => {
  e.preventDefault();
  sbState.query = $("sbQuery").value.trim();
  sbSearchVersion++;
  loadSounds(1);
};
