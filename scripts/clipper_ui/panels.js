// The Short station's tool panels: the rail popovers for Clips, Edit, Transitions, B-roll and Music. Depends on app.js and short.js.

const sameCut = (a, b) => a.src === b.src && Math.abs(a.in - b.in) < 0.05 && Math.abs(a.out - b.out) < 0.05;
const usedIndex = c => state.project.clips.findIndex(t => sameCut(c, t));
const laneIndex = c => Math.max(0, LANES.indexOf(laneOf(c)));

// One clip in the bank. A round button puts it in the Short, or takes it out again.
function bankRow(c, where, used = usedIndex(c), laneOrder) {
  const t = used >= 0 ? state.project.clips[used] : null;
  const lane = t ? laneIndex(t) : -1;
  const broll = where === "broll", shown = broll ? lane > 0 : lane >= 0;
  const row = document.createElement("div");
  row.className = `crow${used >= 0 && used === state.sel ? " sel" : ""}`;
  row.draggable = true;
  const order = shown ? laneOrder ?? state.project.clips.filter(x => laneOf(x) === laneOf(t)).indexOf(t) + 1 : 0;
  const tag = shown ? `<span class="ord num${lane > 0 ? " b" : ""}">${lane > 0 ? `${lane + 1}.` : ""}${order}</span>` : "";
  const v = byPath(c.src), label = c.caption || "";
  const what = broll ? "another lane" : "the Short";
  row.innerHTML = `<div class="pic">${c.thumb ? `<img alt="" src="${c.thumb}">` : ""}${tag}<span class="dur num">${outLen(c).toFixed(1)}s</span></div>` +
    `<div class="cap"><p${label ? "" : ' class="none"'}>${label ? esc(label) : "No caption yet"}</p><small class="num">${v ? esc(v.name.replace(/\.[^.]+$/, "")) : "Missing video"} at ${mmss(c.in)}</small></div>` +
    `<button class="pick" aria-pressed="${shown}" aria-label="${shown ? `Take out of ${what}` : `Add to ${what}`}" title="${shown ? `In ${what}. Click to take it out.` : `Add to ${what}`}"><svg class="i"><use href="#${shown ? "c-check" : "plus"}"/></svg></button>`;
  row.querySelector(".pick").onclick = e => { e.stopPropagation(); togglePick(c, broll); };
  row.onclick = () => { if (used >= 0) { state.sel = used; state.audioSel = null; render(); restartPreviewAt(used); } };
  row.ondragstart = e => {
    e.dataTransfer.setData(CLIP_MIME, JSON.stringify({src: c.src, in: c.in, out: c.out, note: c.note || "", thumb: c.thumb || ""}));
    e.dataTransfer.effectAllowed = "copy";
    dragPx = outLen(c) * stlPps;
  };
  row.ondragend = () => { dragPx = 0; clearSlots(); };
  return row;
}

// Add a bank clip to a lane, or take it out. B-roll goes to the emptiest other lane, opening a second lane when there is only one.
function togglePick(c, broll) {
  const at = usedIndex(c);
  if (at >= 0 && (!broll || laneIndex(state.project.clips[at]) > 0)) {
    removeFromTimeline(at);
    return;
  }
  if (at >= 0) removeClip(at);
  let lane = 0;
  if (broll) {
    let k = laneCount();
    if (k === 1) {
      state.project = {...state.project, template: "split"};
      k = 2;
    }
    const counts = LANES.slice(1, k).map(l => state.project.clips.filter(x => laneOf(x) === l).length);
    lane = 1 + counts.indexOf(Math.min(...counts));
  }
  addToShort(c, LANES[lane]);
  restartPreviewAt(state.sel);
}

function paintBank(panel) {
  const findUsed = momentFinder(state.project.clips);
  if (panel !== "broll") {
    const bank = bankOf(), usedByBank = bank.map(findUsed);
    const orders = [], counts = new Map(), firstOrder = new Map();
    state.project.clips.forEach(c => {
      const lane = laneOf(c), order = (counts.get(lane) || 0) + 1;
      counts.set(lane, order);
      if (!firstOrder.has(c)) firstOrder.set(c, order);
      orders.push(firstOrder.get(c));
    });
    const used = usedByBank.filter(i => i >= 0).length;
    $("bankCount").textContent = `${used} of ${bank.length} used`;
    const empty = '<p class="hint note">No clips yet. Cut some in the Clips station and they show up here.</p>';
    $("bankRows").replaceChildren(...(bank.length ? bank.map((c, i) => bankRow(c, "clips", usedByBank[i], orders[usedByBank[i]])) : []));
    if (!bank.length) $("bankRows").innerHTML = empty;
  }
  if (panel !== "clips") {
    const footage = state.library.filter(v => v.broll && v.duration > 0);
    $("brollRows").replaceChildren(...footage.map(v => brollRow(v, findUsed(brollClip(v)))));
    if (!footage.length) $("brollRows").innerHTML = '<p class="hint note">No B-roll yet. Use + to add videos.</p>';
  }
}

// B-roll is footage, not a cut clip: a whole video, up to BROLL_MAX seconds of it, that goes on another lane.
const BROLL_MAX = 10;
const brollClip = v => ({...savedMoment(v, ""), out: Math.min(v.duration, BROLL_MAX)});

function brollRow(v, used) {
  const c = brollClip(v);
  used ??= usedIndex(c);
  const shown = used >= 0 && laneIndex(state.project.clips[used]) > 0;
  const row = document.createElement("div");
  row.className = "crow";
  row.draggable = true;
  row.title = "Click + to add it to another lane, or drag it onto a lane";
  row.innerHTML = `<div class="pic">${c.thumb ? `<img alt="" src="${c.thumb}">` : ""}<span class="dur num">${outLen(c).toFixed(1)}s</span></div>` +
    `<div class="cap"><p>${esc(v.name.replace(/\.[^.]+$/, ""))}</p><small class="num">${mmss(v.duration)} in all</small></div>` +
    `<button class="pick" aria-pressed="${shown}" aria-label="${shown ? "Take out of another lane" : "Add to another lane"}" title="${shown ? "In another lane. Click to take it out." : "Add to another lane"}"><svg class="i"><use href="#${shown ? "c-check" : "plus"}"/></svg></button>`;
  row.querySelector(".pick").onclick = e => { e.stopPropagation(); togglePick(c, true); };
  row.ondragstart = e => {
    e.dataTransfer.setData(CLIP_MIME, JSON.stringify({src: c.src, in: c.in, out: c.out, note: "", thumb: c.thumb}));
    e.dataTransfer.effectAllowed = "copy";
    dragPx = outLen(c) * stlPps;
  };
  row.ondragend = () => { dragPx = 0; clearSlots(); };
  return row;
}

// ----- Transitions -----

const TRANSITION_TILES = [["none", "Cut"], ...TRANSITIONS];
const TA = "#4c5f9a", TB = "#b0577c", TAB = `linear-gradient(90deg,${TA} 50%,${TB} 50%)`;
const TILE_LOOK = {
  none: TAB,
  flash: `radial-gradient(circle at 50% 50%,#fff 0,#fff0 62%),${TAB}`,
  dip: `linear-gradient(90deg,${TA} 0,#000 50%,${TB} 100%)`,
  swipe_left: `linear-gradient(100deg,${TA} 40%,#fff6 50%,${TB} 60%)`,
  swipe_up: `linear-gradient(180deg,${TA} 40%,#fff6 50%,${TB} 60%)`,
  zoom: `radial-gradient(circle at 50% 50%,${TB} 0 28%,${TA} 29%)`,
  zoom_in: `radial-gradient(circle at 50% 50%,${TB} 0 18%,${TA} 19% 46%,${TB} 47% 70%,${TA} 71%)`,
  zoom_out: `radial-gradient(circle at 50% 50%,${TA} 0 30%,${TB} 31%)`,
  zoom_punch: `repeating-radial-gradient(circle at 50% 50%,${TB} 0 5px,${TA} 5px 10px)`,
  whip: `repeating-linear-gradient(90deg,#ffffff30 0 2px,#0000 2px 7px),linear-gradient(90deg,${TA},${TB})`,
  pixelize: `conic-gradient(${TA} 25%,${TB} 0 50%,${TA} 0 75%,${TB} 0) 0 0/14px 14px`,
  iris: `radial-gradient(circle at 50% 50%,${TB} 0 48%,${TA} 49%)`,
  streak: `linear-gradient(90deg,${TA} 0,#ffffff80 50%,${TB} 100%)`,
  clock: `conic-gradient(${TB} 0 38%,${TA} 0)`,
  glitch: `repeating-linear-gradient(0deg,${TA} 0 7px,${TB} 7px 10px)`,
};

function paintTransitions() {
  const i = state.sel, c = state.project.clips[i];
  let at = -1;
  if (c) {
    const lane = laneOf(c);
    let position = 0;
    state.project.clips.some(x => {
      if (laneOf(x) !== lane) return false;
      if (x === c) { at = position; return true; }
      position++;
      return false;
    });
  }
  const first = !c || at <= 0;
  $("trNote").textContent = !c ? "Select a clip on the timeline first." : first ? "Start of the clip. It fades in from black. Click a transition to apply it." : `Between clip ${at} and clip ${at + 1}.`;
  $("trGrid").replaceChildren(...TRANSITION_TILES.map(([id, label]) => {
    const b = document.createElement("button");
    b.className = "tt";
    b.disabled = !c;
    b.setAttribute("aria-pressed", c ? transitionOf(c) === id : false);
    b.innerHTML = `<i class="tv" style="background:${TILE_LOOK[id]}"></i><span>${label}</span>`;
    b.onclick = () => { setClipField(i, {transition: id}); toast(id === "none" ? "Hard cut" : first ? `${label} from black into the clip` : `${label} into the clip`); };
    return b;
  }));
  $("trLen").replaceChildren(...(c && transitionOf(c) !== "none"
    ? [zoomSlider(i, "Duration", "tlen", 0.1, 1.5, 0.05, tlenOf(c), v => `${v.toFixed(2).replace(/0$/, "")}s`)] : []));
}

// ----- Music -----

const isSong = f => f.kind === "song";
const songItem = f => audioOf().find(a => a.file === f.id);
let musicRows = new Map();

function paintMusic() {
  const files = audioFiles;
  const list = $("musicList");
  if (!files.length) {
    musicRows.clear();
    list.innerHTML = '<p class="hint note">No music yet. Use + to add songs or sound effects.</p>';
  } else {
    const usedFiles = new Set(audioOf().map(a => a.file)), names = new Set(files.map(f => f.name));
    const next = new Map();
    const rows = files.map(f => {
      const on = usedFiles.has(f.id);
      const key = JSON.stringify([f.name, f.kind, f.duration, on, canRemoveVocals(f, names), voxBusy.has(f.id)]);
      const old = musicRows.get(f.id);
      if (old && old.file === f && old.key === key) {
        next.set(f.id, old);
        return old.row;
      }
      const b = document.createElement("button");
      b.className = `mtrack${on ? " on" : ""}`;
      b.draggable = true;
      b.title = "Click to add, or drag onto the timeline";
      b.ondragstart = e => startSoundDrag(e, f);
      b.ondragend = endSoundDrag;
      b.innerHTML = `<span class="wv"><svg class="i"><use href="#${isSong(f) ? "i-music" : "vol"}"/></svg></span><span><b>${esc(f.name)}</b><small class="num">${secs(f.duration)}${on ? (isSong(f) ? ", under the whole Short" : ", at the playhead") : ""}${voxBusy.has(f.id) ? ", taking the singing out" : ""}</small></span>${on ? '<svg class="i ck"><use href="#c-check"/></svg>' : ""}`;
      b.onclick = () => {
        const item = songItem(f);
        if (item) return removeAudio(item.id);
        addAudio(f, isSong(f) ? 0 : Math.round((preview.elapsed || 0) * 10) / 10);
      };
      const row = document.createElement("div");
      row.className = "mrow";
      row.append(b, musicMenu(f, names));
      next.set(f.id, {file: f, key, row});
      return row;
    });
    musicRows = next;
    if (list.children.length !== rows.length || rows.some((row, i) => list.children[i] !== row)) list.replaceChildren(...rows);
  }
}
$("musicAdd").onclick = () => $("srcPick").click();

// The Look panel edits the same project fields as the Settings tab, so the two always agree.
const LOOK_FIELDS = [["lookBlur", "blurBg", p => Boolean(p.blurBg)], ["lookWm", "watermark", p => p.watermark !== false], ["lookNorm", "normalize", p => Boolean(p.normalize)]];
function paintLook() {
  for (const [id, , read] of LOOK_FIELDS) $(id).checked = read(state.project);
}
for (const [id, field] of LOOK_FIELDS) {
  $(id).onchange = e => { state.project = {...state.project, [field]: e.target.checked}; paintLook(); renderShortOptions(); changed(); };
}

// Refresh the open tool after timeline edits; closed tools refresh when opened.
function paintShortPanels() {
  switch (railOpen) {
    case "clips": case "broll": paintBank(railOpen); break;
    case "transitions": paintTransitions(); break;
    case "text": paintText(); break;
    case "music": paintMusic(); break;
    case "look": paintLook(); break;
  }
  paintShortsBadge();
}

// B-roll is only what is added here, so cut sources and clips never show up in the panel.
$("brollAdd").onclick = () => $("brollPick").click();
$("brollPick").onchange = async e => {
  const videos = Array.from(e.target.files).filter(isVideoFile);
  e.target.value = "";
  if (!videos.length) return toast("Add video files (mp4, mov, m4v, mkv, webm, avi)");
  if (dropZone.busy) return toast("Wait for the current upload to finish");
  dropZone.busy = true;
  try {
    for (const [i, file] of videos.entries()) {
      const tag = videos.length > 1 ? ` (${i + 1} of ${videos.length})` : "";
      showUpload(`Uploading ${file.name}${tag}`, 0);
      await uploadVideo(file, pct => showUpload(`Uploading ${file.name}${tag}, ${pct}%`, pct), true);
    }
    await refreshLibrary();
    paintBank();
    toast(`${videos.length} B-roll clip${videos.length === 1 ? "" : "s"} added`);
  } catch (err) {
    await refreshLibrary();
    paintBank();
    toast(err.message);
  } finally {
    dropZone.busy = false;
    showUpload(null);
  }
};

// Browser-local recipes contain presentation settings only, never media or words.
const SHORT_PRESET_FIELDS = ["layout", "format", "template", "capSize", "blurBg", "watermark", "normalize", "fade"];
const SHORT_PRESET_CAP_FIELDS = ["capLook", "capMode", "capHi", "capX", "capY", "capScale", "capRot"];
function readShortPresets() {
  try { const items = JSON.parse(localStorage.getItem("clipbench.shortPresets") || "[]"); return Array.isArray(items) ? items.filter(p => p && typeof p.name === "string" && p.settings && p.caption).slice(0, 50) : []; }
  catch { return []; }
}
function presetFields(object, fields) { return Object.fromEntries(fields.map(k => [k, object[k] ?? null])); }
function captureShortPreset(name) {
  const clips = timelineOf(), clip = clips.find(c => isTop(c) && c.caption) || clips.find(isTop) || {};
  return {name, settings: presetFields({...state.project, watermark: state.project.watermark !== false}, SHORT_PRESET_FIELDS), caption: presetFields(clip, SHORT_PRESET_CAP_FIELDS)};
}
function paintShortPresets(selected = $("shortPresetList").value) {
  const items = readShortPresets(), list = $("shortPresetList");
  list.replaceChildren(new Option("Choose a preset", ""), ...items.map(p => new Option(p.name, p.name)));
  if (items.some(p => p.name === selected)) list.value = selected;
  $("shortPresetDelete").disabled = !items.some(p => p.name === list.value);
}
function writeShortPresets(items, selected) {
  try { localStorage.setItem("clipbench.shortPresets", JSON.stringify(items)); paintShortPresets(selected); return true; }
  catch { toast("Couldn't save presets in this browser"); return false; }
}
$("shortPresetSave").onclick = e => {
  if (e) e.preventDefault();
  const name = $("shortPresetName").value.trim();
  if (!name) return $("shortPresetName").focus();
  const items = readShortPresets(), exists = items.some(p => p.name === name);
  if (!exists && items.length >= 50) return toast("Delete a preset before saving another");
  if (writeShortPresets([...items.filter(p => p.name !== name), captureShortPreset(name)], name)) { $("shortPresetDialog").close(); toast("Preset saved"); }
};
$("shortPresetList").onchange = () => {
  const p = readShortPresets().find(p => p.name === $("shortPresetList").value);
  if (!p) return;
  const key = inShort() ? "clips" : "other";
  state.project = {...state.project, ...presetFields(p.settings, SHORT_PRESET_FIELDS), [key]: (state.project[key] || []).map(c => isTop(c) ? {...c, ...presetFields(p.caption, SHORT_PRESET_CAP_FIELDS)} : c)};
  $("shortPresetDelete").disabled = false;
  changed();
  toast("Preset applied to this Short");
};
$("shortPresetDelete").onclick = () => {
  if (writeShortPresets(readShortPresets().filter(p => p.name !== $("shortPresetList").value), "")) $("shortPresetDialog").close();
};
$("shortPresetNew").onclick = () => { $("shortPresetName").value = ""; $("shortPresetDialog").showModal(); $("shortPresetName").focus(); };
$("shortPresetClose").onclick = () => $("shortPresetDialog").close();
$("shortPresetForm").onsubmit = e => { e.preventDefault(); $("shortPresetSave").onclick(); };
paintShortPresets();

// Per-clip grading opens in the same space as the Music finder.
const clipProps = document.createElement("dialog");
clipProps.id = "clipProps";
clipProps.setAttribute("aria-label", "Clip properties");
clipProps.innerHTML = '<header><b>Clip properties</b><button aria-label="Close clip properties">×</button></header><div class="grade-heading">Looks</div><div id="gradeLooks"></div><div class="grade-heading"><span>Adjust</span><button id="gradeReset">Reset</button></div><div id="gradeControls"></div>';
document.body.append(clipProps);
let gradeClip = null;
const GRADE_LOOKS = {
  Warm:{temperature:.35,tint:.05,saturation:1.08},
  Cool:{temperature:-.3,saturation:.95},
  Cinematic:{contrast:1.28,saturation:.82,vibrance:.3,temperature:-.25,tint:-.05,shadows:-.06,highlights:-.1},
  Punchy:{contrast:1.2,saturation:1.15,vibrance:.25},
  "B&W":{saturation:0,contrast:1.12},
  Faded:{contrast:.8,saturation:.85,shadows:.2,highlights:-.1}
};
function positionClipProps() {
  if (!clipProps.open) return;
  const r = $("railPop").getBoundingClientRect();
  Object.assign(clipProps.style, {top:`${r.top}px`,left:`${r.left}px`,width:`${r.width}px`,height:`${r.height}px`});
}
function updateGrade(patch) {
  const idx=state.project.clips.indexOf(gradeClip);
  if(idx<0) {clipProps.close();return false;}
  setClipField(idx,patch);
  gradeClip=state.project.clips[idx];
  return true;
}
function paintGrade() {
  $("gradeControls").replaceChildren();
  for(const [key,label] of [["exposure","Exposure"],["brightness","Brightness"],["contrast","Contrast"],["saturation","Saturation"],["vibrance","Vibrance"],["temperature","Temperature"],["tint","Tint"],["shadows","Shadows"],["highlights","Highlights"]]) {
    const row=document.createElement("label"), base=gradeDefaults[key];
    row.innerHTML=`<span>${label}</span><input type="number" step="0.01" min="${key==='exposure'?-2:-1}" max="${key==='exposure'?2:1}" aria-label="${label}">`;
    const input=row.querySelector("input");input.value=Number(((gradeClip[key] ?? base)-base).toFixed(2));
    input.oninput=()=>{if(input.value.trim()==="" || !input.validity.valid)return; if(updateGrade({[key]:Number(input.value)+base})) paintGradeLooks();};
    input.onblur=()=>{input.value=Number(((gradeClip[key] ?? base)-base).toFixed(2));};
    $("gradeControls").append(row);
  }
  paintGradeLooks();
}
function paintGradeLooks() {
  $("gradeLooks").replaceChildren();
  for(const [name,look] of Object.entries(GRADE_LOOKS)) {
    const btn=document.createElement("button");btn.textContent=name;
    btn.setAttribute("aria-pressed",String(Object.entries({...gradeDefaults,...look}).every(([k,v])=>Math.abs((gradeClip[k] ?? gradeDefaults[k])-v)<.001)));
    btn.onclick=()=>{if(updateGrade({...gradeDefaults,...look}))paintGrade();};
    $("gradeLooks").append(btn);
  }
}
function openClipProperties(i) {
  if (blockedByLock(i)) return;
  gradeClip=state.project.clips[i];
  railShow("look");paintGrade();
  if(!clipProps.open)clipProps.show();
  positionClipProps();
}
clipProps.querySelector("header button").onclick = () => clipProps.close();
$("gradeReset").onclick=()=>{if(updateGrade({...gradeDefaults}))paintGrade();};
window.addEventListener("resize", positionClipProps);
$("stlBody").addEventListener("dblclick", e => {
  const block = e.target.closest(".stl-clip");
  if (block && !e.target.closest(".th")) { e.preventDefault(); openClipProperties(Number(block.dataset.gi)); }
});
