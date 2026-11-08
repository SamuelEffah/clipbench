// Songs and sound effects: the audio library, the audio lane on the Short timeline, and the preview mix.
const AUDIO_MIME = "application/x-audio";
const MIN_SOUND = 0.1;
const isAudioFile = f => /\.(mp3|wav|m4a|aac|ogg|flac|aiff?)$/i.test(f.name);
const hasAudioDrag = e => Array.from(e.dataTransfer.types || []).includes(AUDIO_MIME);
const AUDIO_KIND_NAMES = {sfx: "Effect", song: "Song"};

let audioFiles = [];
let audioScale = {pps: 40};
let draggingSound = null;
const audioOf = () => state.project.audio || [];
const audioInfo = id => audioFiles.find(f => f.id === id);
const secs = s => `${s.toFixed(1)}s`;
const newAudioId = () => `a${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

async function refreshAudio() {
  try {
    audioFiles = await api("/api/audio");
  } catch {
    audioFiles = [];
  }
  renderAudioLib();
}

// ----- Library -----

const libPlayer = new Audio();
let libPlaying = "";
libPlayer.addEventListener("ended", () => { libPlaying = ""; renderAudioLib(); });

function toggleLibPlay(file) {
  if (libPlaying === file.id) {
    libPlayer.pause();
    libPlaying = "";
  } else {
    libPlayer.src = `/audio-file/${file.id}`;
    libPlaying = file.id;
    libPlayer.play().catch(err => {
      // Switching to another sound aborts this one, which is not a failure.
      if (err.name === "AbortError" || libPlaying !== file.id) return;
      libPlaying = "";
      renderAudioLib();
      toast("Couldn't play that file");
    });
  }
  renderAudioLib();
}

function startSoundDrag(e, f) {
  e.dataTransfer.setData(AUDIO_MIME, f.id);
  e.dataTransfer.effectAllowed = "copy";
  draggingSound = f;
  document.body.classList.add("sdrag");
}

function audioRow(f) {
  const row = document.createElement("div");
  row.className = "audrow";
  row.draggable = true;
  const on = libPlaying === f.id;
  row.innerHTML = `<button class="audplay" aria-label="${on ? "Stop" : "Play"} ${esc(f.name)}" title="${on ? "Stop" : "Play"}"><svg class="i"><use href="#${on ? "pause" : "play"}"/></svg></button>` +
    `<div class="audmeta"><b title="${esc(f.name)}">${esc(f.name)}</b><small class="num">${secs(f.duration)}</small></div>` +
    `<button class="audadd" aria-label="Add ${esc(f.name)} to the Short" title="Add at the playhead"><svg class="i"><use href="#plus"/></svg></button>`;
  row.ondragstart = e => startSoundDrag(e, f);
  row.ondragend = () => endSoundDrag();
  row.querySelector(".audplay").onclick = () => toggleLibPlay(f);
  row.querySelector(".audadd").onclick = () => addAudio(f, Math.round((preview.elapsed || 0) * 10) / 10);
  return row;
}

// Songs and effects as folding sections, the same as the Details panel.
let audioLibRows = new Map(), audioLibGroups = new Map(), audioLibHint = null;
function renderAudioLib() {
  const groups = [["Songs", "song", "No songs yet. Add an mp3 or put files in the audio folder."], ["Effects", "sfx", "No sound effects yet. Short sounds, up to 10 seconds, land here."]];
  const next = new Map();
  const boxes = groups.map(([title, kind, empty]) => {
    const files = audioFiles.filter(f => f.kind === kind);
    const rows = files.map(f => {
      const key = JSON.stringify([f.name, f.duration, libPlaying === f.id]);
      const old = audioLibRows.get(f.id);
      const entry = old && old.file === f && old.key === key ? old : {file: f, key, row: audioRow(f)};
      next.set(f.id, entry);
      return entry.row;
    });
    let group = audioLibGroups.get(kind);
    if (!group) {
      const placeholder = Object.assign(document.createElement("p"), {className: "hint", textContent: empty});
      const box = section(title, rows.length ? rows : [placeholder], String(files.length));
      group = {box, placeholder, body: box.querySelector(".dsec-b"), count: box.querySelector(".dsec-note")};
      audioLibGroups.set(kind, group);
    }
    if (!rows.length) rows.push(group.placeholder);
    if (group.body.children.length !== rows.length || rows.some((row, i) => group.body.children[i] !== row)) group.body.replaceChildren(...rows);
    group.count.textContent = String(files.length);
    return group.box;
  });
  audioLibRows = next;
  if (!audioFiles.length) {
    if (!audioLibHint) audioLibHint = Object.assign(document.createElement("p"), {className: "hint fxhint",
      textContent: "Drag a sound onto the timeline, or press + to add it at the playhead. Add files with + above, or drop them here."});
    boxes.unshift(audioLibHint);
  }
  const list = $("audList");
  if (list.children.length !== boxes.length || boxes.some((box, i) => list.children[i] !== box)) list.replaceChildren(...boxes);
}

function uploadAudio(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/upload-audio?name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = e => e.lengthComputable && onProgress(Math.round(e.loaded / e.total * 100));
    xhr.onerror = () => reject(new Error("The upload failed"));
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (err) { /* keep the empty object */ }
      xhr.status === 200 ? resolve(data) : reject(new Error(data.error || xhr.statusText));
    };
    xhr.send(file);
  });
}

let audioBusy = false;
async function addAudioFiles(files) {
  const sounds = files.filter(isAudioFile);
  if (!sounds.length) return toast("Drop audio files (mp3, wav, m4a, aac, ogg, flac)");
  if (audioBusy) return toast("Wait for the current upload to finish");
  audioBusy = true;
  try {
    for (const [i, file] of sounds.entries()) {
      const tag = sounds.length > 1 ? ` (${i + 1} of ${sounds.length})` : "";
      showUpload(`Uploading ${file.name}${tag}`, 0);
      await uploadAudio(file, pct => showUpload(`Uploading ${file.name}${tag}, ${pct}%`, pct));
    }
    await refreshAudio();
    toast(`${sounds.length} sound${sounds.length === 1 ? "" : "s"} added`);
  } catch (err) {
    await refreshAudio();
    toast(err.message);
  } finally {
    audioBusy = false;
    showUpload(null);
  }
}

// ----- Timeline items -----

function setAudio(id, patch, key) {
  state.project = {...state.project, audio: audioOf().map(a => (a.id === id ? {...a, ...patch} : a))};
  changed(true, key);
}

function addAudio(file, start) {
  const top = laneTotal("top", state.project.clips);
  const room = top - start;
  const dur = file.kind === "sfx" ? file.duration : Math.max(1, Math.min(file.duration, room > 1 ? room : file.duration));
  const item = {id: newAudioId(), file: file.id, label: file.name, kind: file.kind, total: file.duration, start: Math.max(0, Number(start.toFixed(2))),
                in: 0, dur: Number(dur.toFixed(2)), volume: 1, fadeIn: 0, fadeOut: file.kind === "song" ? 1 : 0};
  state.project = {...state.project, audio: [...audioOf(), item]};
  state.audioSel = item.id;
  changed();
  setTab("details");
  toast(`${file.name} added at ${secs(item.start)}`);
}

function removeAudio(id) {
  state.project = {...state.project, audio: audioOf().filter(a => a.id !== id)};
  if (state.audioSel === id) state.audioSel = null;
  changed();
}

function selectAudio(id) {
  state.audioSel = id;
  setTab("details");
  render();
}

const removeSelected = () => (audioOf().some(a => a.id === state.audioSel) ? removeAudio(state.audioSel) : chosen().length > 1 ? removeChosen() : removeFromTimeline(state.sel));

function audioRows(items) {
  const ends = [], place = new Map();
  [...items].sort((a, b) => a.start - b.start).forEach(a => {
    let r = ends.findIndex(end => end <= a.start + 0.001);
    if (r < 0) { r = ends.length; ends.push(0); }
    ends[r] = a.start + a.dur;
    place.set(a.id, r);
  });
  return {count: Math.max(1, ends.length), place};
}

const ROW_H = 30;

// ----- Waveforms -----

const audioPeaks = new Map();
async function peaksFor(id) {
  if (!audioPeaks.has(id)) {
    audioPeaks.set(id, api(`/api/audio-wave/${id}`).catch(() => {
      audioPeaks.delete(id);
      return {per_sec: 50, peaks: []};
    }));
  }
  return audioPeaks.get(id);
}

// Draw the part of the sound this block plays, as mirrored bars scaled by its volume and fades so the shape shows what you will hear.
async function drawSoundWave(block, a) {
  const canvas = block.querySelector(".aud-wave");
  if (!canvas || !canvas.isConnected) return;
  const wave = await peaksFor(a.file);
  if (!canvas || !canvas.isConnected || !wave.peaks.length) return;
  const pps = audioScale.pps, ratio = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(a.dur * pps)), h = canvas.clientHeight || 28;
  const g = prepareWaveCanvas(canvas, w, h, ratio);
  g.fillStyle = "rgba(74,222,128,.55)";
  const step = 2, mid = h / 2;
  for (let x = 0; x < w; x += step) {
    const t0 = a.in + x / pps, t1 = a.in + Math.min(w, x + step) / pps;
    const from = Math.floor(t0 * wave.per_sec), to = Math.max(from + 1, Math.ceil(t1 * wave.per_sec));
    const gain = soundGain(a, a.start + x / pps, true);
    let peak = 0;
    if (gain !== 0) for (let i = from; i < to && i < wave.peaks.length; i++) peak = Math.max(peak, wave.peaks[i]);
    const amp = Math.min(1, peak / 255 * gain);
    const bar = Math.max(1, amp * (h - 2));
    g.fillRect(x, mid - bar / 2, step - 0.6, bar);
  }
}

// Drag a block to move it, or its ends to trim it. The DOM is updated while dragging and rebuilt when you let go.
function dragAudio(e, block, a, mode) {
  e.preventDefault();
  e.stopPropagation();
  block.setPointerCapture(e.pointerId);
  const x0 = e.clientX, pps = audioScale.pps, snap = v => Math.round(v * 20) / 20;
  let latest = a, moved = false;
  const onMove = ev => {
    const dt = (ev.clientX - x0) / pps;
    if (Math.abs(ev.clientX - x0) > 3) moved = true;
    let patch;
    if (mode === "move") patch = {start: Math.max(0, snap(a.start + dt))};
    else if (mode === "right") patch = {dur: Math.min(a.total - a.in, Math.max(MIN_SOUND, snap(a.dur + dt)))};
    else {
      const delta = Math.min(a.dur - MIN_SOUND, Math.max(-Math.min(a.in, a.start), snap(dt)));
      patch = {start: Number((a.start + delta).toFixed(2)), in: Number((a.in + delta).toFixed(2)), dur: Number((a.dur - delta).toFixed(2))};
    }
    patch = snapSound(a, mode, patch, ev.altKey);
    latest = {...a, ...patch};
    block.style.left = `${latest.start * pps}px`;
    block.style.width = `${Math.max(latest.dur * pps, 14)}px`;
    block.querySelector(".aud-len").textContent = secs(latest.dur);
    drawSoundWave(block, latest);
  };
  const onUp = () => {
    block.removeEventListener("pointermove", onMove);
    block.removeEventListener("pointerup", onUp);
    block.removeEventListener("pointercancel", onUp);
    hideSnapLine();
    if (!moved) return selectAudio(a.id);
    state.audioSel = a.id;
    setAudio(a.id, {start: latest.start, in: latest.in, dur: latest.dur}, "");
    setTab("details");
    render();
  };
  block.addEventListener("pointermove", onMove);
  block.addEventListener("pointerup", onUp);
  block.addEventListener("pointercancel", onUp);
}

function audioBlock(a, row, pps) {
  const b = document.createElement("div");
  b.className = `stl-audio ${a.kind}${a.id === state.audioSel ? " sel" : ""}${a.dur * pps < 70 ? " narrow" : ""}`;
  Object.assign(b.style, {left: `${a.start * pps}px`, width: `${Math.max(a.dur * pps, 14)}px`, top: `${row * (ROW_H + 4)}px`});
  b.tabIndex = 0;
  b.title = `${a.label}, ${secs(a.dur)} from ${secs(a.start)}`;
  b.dataset.id = a.id;
  Object.assign(b.dataset, {t0: a.start, t1: a.start + a.dur});
  b.innerHTML = `<canvas class="aud-wave" aria-hidden="true"></canvas><i class="h l" aria-hidden="true"></i><span class="aud-name">${esc(a.label)}</span><span class="aud-len num">${secs(a.dur)}</span><i class="h r" aria-hidden="true"></i>`;
  b.onpointerdown = e => {
    dragAudio(e, b, a, e.target.classList.contains("l") ? "left" : e.target.classList.contains("r") ? "right" : "move");
  };
  b.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectAudio(a.id); } };
  const paintLevel = addLevelEditor(b, a, pps);
  requestAnimationFrame(() => paintWhenVisible(b, async () => { paintLevel(a); await drawSoundWave(b, a); }));
  return b;
}

// The level of a sound on the timeline, edited like a clip's sound: a line across the block to drag up or down, and dots at its
// ends to fade. Double-click the line for 100% or a dot to clear its fade. Returns what repaints the line for a changed sound.
function addLevelEditor(block, a, pps) {
  const svg = document.createElementNS(SND_NS, "svg");
  svg.setAttribute("class", "snd-env");
  const slope = document.createElementNS(SND_NS, "polyline");
  svg.append(slope);
  const unity = Object.assign(document.createElement("i"), {className: "snd-unity"});
  const line = Object.assign(document.createElement("i"), {className: "snd-vol", title: "Drag up or down for the level at the start. Double-click for 100%."});
  const rise = Object.assign(document.createElement("i"), {className: "snd-vol end", title: "Drag up or down for the level it rises or falls to by the end. Double-click to keep it steady."});
  const dots = ["fadeIn", "fadeOut"].map(key => Object.assign(document.createElement("i"), {
    className: `snd-fade ${key === "fadeIn" ? "l" : "r"}`,
    title: key === "fadeIn" ? "Drag to fade in. Double-click to clear." : "Drag to fade out. Double-click to clear."}));
  const current = () => audioOf().find(x => x.id === a.id) || a;
  const paint = cur => {
    const h = block.clientHeight || ROW_H, w = block.clientWidth || 28, y = (1 - Math.min(cur.volume, MAX_VOLUME) / MAX_VOLUME) * h;
    const y2 = (1 - Math.min(endLevel(cur), MAX_VOLUME) / MAX_VOLUME) * h;
    const fi = Math.min(cur.fadeIn || 0, cur.dur / 2) * pps, fo = Math.min(cur.fadeOut || 0, cur.dur / 2) * pps;
    slope.setAttribute("points", `${fi ? `0,${h} ` : ""}${fi},${y} ${w - fo},${y2}${fo ? ` ${w},${h}` : ""}`);
    unity.style.top = `${(1 - 1 / MAX_VOLUME) * h}px`;
    Object.assign(line.style, {top: `${y}px`, left: `${fi}px`, right: "50%"});
    Object.assign(rise.style, {top: `${y2}px`, left: "50%", right: `${fo}px`});
    line.classList.toggle("off", cur.volume === 0);
    rise.classList.toggle("off", endLevel(cur) === 0);
    dots[0].style.cssText = `left:${fi}px;top:${y}px`;
    dots[1].style.cssText = `right:${fo}px;top:${y2}px`;
  };
  const edit = patch => {
    const cur = {...current(), ...patch};
    state.project = {...state.project, audio: audioOf().map(x => (x.id === a.id ? cur : x))};
    drawSoundWave(block, cur);
    paint(cur);
  };
  const drag = (e, move, tip) => {
    e.preventDefault();
    e.stopPropagation();
    const el = e.currentTarget, rect = block.getBoundingClientRect();
    el.setPointerCapture(e.pointerId);
    block.classList.add("editing");
    const onMove = ev => { move(ev, rect); showSndTip(ev.clientX + 14, ev.clientY - 30, tip(current())); };
    const onUp = () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      block.classList.remove("editing");
      hideSndTip();
      state.audioSel = a.id;
      changed();
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    onMove(e);
  };
  line.onclick = e => e.stopPropagation();
  line.ondblclick = e => { e.stopPropagation(); setAudio(a.id, {volume: 1}, ""); render(); };
  line.onpointerdown = e => drag(e, (ev, rect) => {
    let volume = (1 - Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height))) * MAX_VOLUME;
    if (Math.abs(volume - 1) < 0.07) volume = 1;
    volume = clampVolume(volume);
    if (volume !== current().volume) edit({volume});
  }, cur => (cur.volume === 0 ? "Muted" : `${Math.round(cur.volume * 100)}%`));
  const levelAt = (ev, rect) => clampVolume((1 - Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height))) * MAX_VOLUME);
  rise.onclick = e => e.stopPropagation();
  rise.ondblclick = e => { e.stopPropagation(); setAudio(a.id, {volumeEnd: null}, ""); render(); };
  rise.onpointerdown = e => drag(e, (ev, rect) => {
    let level = levelAt(ev, rect);
    if (Math.abs(level - current().volume) < 0.05) level = current().volume;
    if (level !== endLevel(current())) edit({volumeEnd: level});
  }, cur => `Ends at ${endLevel(cur) === 0 ? "muted" : `${Math.round(endLevel(cur) * 100)}%`}`);
  dots.forEach((d, n) => {
    const key = n ? "fadeOut" : "fadeIn";
    d.onclick = e => e.stopPropagation();
    d.ondblclick = e => { e.stopPropagation(); setAudio(a.id, {[key]: 0}, ""); render(); };
    d.onpointerdown = e => drag(e, (ev, rect) => {
      const dx = n ? rect.right - ev.clientX : ev.clientX - rect.left;
      edit({[key]: Number(Math.min(5, current().dur / 2, Math.max(0, Math.round(dx / pps * 10) / 10)).toFixed(1))});
    }, cur => `${n ? "Fade out" : "Fade in"} ${secs(cur[key] || 0)}`);
  });
  block.append(svg, unity, line, rise, ...dots);
  return paint;
}

// The audio lane under the clips: one row per overlapping sound, so effects can sit on top of a song.
function audioLane(pps, span, topLen) {
  audioScale = {pps};
  const items = audioOf(), {count, place} = audioRows(items);
  const rowEl = document.createElement("div");
  rowEl.className = "stl-lane";
  const track = document.createElement("div");
  track.className = "stl-track audio";
  track.style.height = `${count * ROW_H + (count - 1) * 4}px`;
  items.forEach(a => track.appendChild(audioBlock(a, place.get(a.id), pps)));
  rowEl.append(track);
  return rowEl;
}

// A line across the timeline that follows the preview, so a sound can be lined up with what you see.
// ----- Scrubbing the Short -----

let scrub = null;

// The source time that is `pos` seconds into a clip as the Short plays it, allowing for speed changes.
function sourceAt(clip, pos) {
  if (pos >= movingLen(clip)) return clip.out;
  let lo = clip.in, hi = clip.out;
  for (let n = 0; n < 24; n++) {
    const mid = (lo + hi) / 2;
    if (outTimeAt(clip, mid) < pos) lo = mid; else hi = mid;
  }
  return hi;
}

function seekShort(T) {
  const clips = state.project.clips;
  let idx = -1, at = 0, start = 0, prev = null;
  clips.forEach((c, n) => {
    if (!isTop(c)) return;
    at -= seamOverlap(prev, c);
    if (at <= T + 0.0001) { idx = n; start = at; }
    at += outLen(c);
    prev = c;
  });
  if (idx < 0) return;
  const clip = clips[idx], pos = Math.max(0, T - start);
  const src = sourceAt(clip, Math.min(pos, movingLen(clip)));
  if (idx === preview.idx && !preview.done) {
    // A hold in progress is over once you scrub; it starts again when the clip reaches its end.
    if (state.clipStop && state.clipStop.holding) state.clipStop = {...state.clipStop, holding: 0};
    video.currentTime = Math.max(0, src - baseOf(video));
  } else startPreviewAt(idx, src);
  preview.elapsed = T;
}

// The row whose left edge is time 0. The caption and sound-in-clip rows are hidden when empty, and a hidden row reports 0.
function timeTrack(body = $("stlBody")) {
  return body.querySelector(".stl-track:not(.cliptext):not(.clipsound):not(.audio)");
}

function scrubTime(e) {
  const track = timeTrack();
  if (!track) return 0;
  const top = laneTotal("top", state.project.clips);
  return Math.min(Math.max(0, (e.clientX - track.getBoundingClientRect().left) / audioScale.pps), Math.max(0, top - 0.02));
}

// Grab the playhead, or press on the ruler, and drag to move through the Short.
function startScrub(e) {
  if (!preview.on || e.button) return;
  e.preventDefault();
  const resume = !video.paused && !preview.hold;
  scrub = {t: scrubTime(e)};
  preview.hold = !resume;
  document.body.classList.add("scrubbing");
  const move = ev => {
    const t = snapScrubTime(scrubTime(ev), ev);
    if (Math.abs(t - scrub.t) < 0.01 && ev !== e) return;
    scrub.t = t;
    seekShort(t);
    paintPlayhead();
  };
  const stop = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
    window.removeEventListener("pointercancel", stop);
    document.body.classList.remove("scrubbing");
    hideSnapLine();
    scrub = null;
    preview.hold = !resume;
    if (!resume) video.pause();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop);
  window.addEventListener("pointercancel", stop);
  move(e);
}

function paintPlayhead() {
  const body = $("stlBody"), track = timeTrack(body);
  let head = body.querySelector(".stl-playhead");
  if (!track || !preview.on) {
    body.querySelectorAll("[data-t0]").forEach(el => el.style.removeProperty("--played"));
    return head && head.remove();
  }
  // What the playhead has passed dims, so you can see at a glance what is still to come.
  const now = scrub ? scrub.t : preview.elapsed || 0;
  if (!head) {
    head = document.createElement("i");
    head.className = "stl-playhead";
    head.onpointerdown = startScrub;
    head.innerHTML = '<span class="ph-time num"></span>';
    body.appendChild(head);
  }
  const x = track.offsetLeft + now * audioScale.pps, y = track.offsetTop - 6;
  // Timeline rebuilds replace the head, so a new head also invalidates this time.
  if (head._playedAt !== now) {
    if (!head._playedBlocks) head._playedBlocks = Array.from(body.querySelectorAll("[data-t0]"), el => {
      const start = Number(el.dataset.t0);
      return {el, start, duration: Math.max(0.001, Number(el.dataset.t1) - start)};
    });
    for (const block of head._playedBlocks) {
      const done = (now - block.start) / block.duration;
      const value = done <= 0 ? "0.0%" : done >= 1 ? "100.0%" : `${(done * 100).toFixed(1)}%`;
      if (block.value !== value) {
        if (block.el.style.getPropertyValue("--played") !== value) block.el.style.setProperty("--played", value);
        block.value = value;
      }
    }
    head._playedAt = now;
  }
  setPlaybackValue(head.style, "left", `${x}px`);
  setPlaybackValue(head.style, "top", `${y}px`);
  const m = Math.floor(now / 60), sec = now - m * 60;
  setPlaybackValue(head.firstChild, "textContent", `${m}:${sec.toFixed(1).padStart(4, "0")}`);
  followPlayhead(x);
}

// ----- Details for a selected sound -----

function audioSlider(a, label, key, min, max, step, value, show) {
  const row = document.createElement("label");
  row.className = "zoomrow";
  const name = document.createElement("span");
  name.textContent = label;
  const input = Object.assign(document.createElement("input"), {type: "range", min, max, step, value});
  input.setAttribute("aria-label", `${label} of ${a.label}`);
  const out = document.createElement("output");
  out.className = "num";
  out.textContent = show(value);
  input.oninput = () => {
    const v = Number(input.value);
    out.textContent = show(v);
    setAudio(a.id, {[key]: v}, `aud-${key}:${a.id}`);
    const block = document.querySelector(`.stl-audio[data-id="${a.id}"]`);
    if (block) drawSoundWave(block, audioOf().find(x => x.id === a.id));
    paintPlayhead();
  };
  input.onchange = () => render();
  row.append(name, input, out);
  return row;
}

function audioDetails(a) {
  const head = document.createElement("div");
  head.className = "dhead";
  head.innerHTML = `<div class="pic aud-pic"><svg class="i"><use href="#${a.kind === "song" ? "play" : "plus"}"/></svg></div>` +
    `<div><b>${esc(a.label)}</b><small class="num">${AUDIO_KIND_NAMES[a.kind]}, ${secs(a.dur)} from ${secs(a.start)}</small></div>`;
  const remove = document.createElement("button");
  remove.className = "ico";
  remove.setAttribute("aria-label", "Remove this sound");
  remove.title = "Remove from the Short";
  remove.innerHTML = '<svg class="i"><use href="#trash"/></svg>';
  remove.onclick = () => removeAudio(a.id);
  head.appendChild(remove);
  const pct = v => (v === 0 ? "Muted" : `${Math.round(v * 100)}%`);
  const off = v => (v === 0 ? "Off" : secs(v));
  return [head,
    section("Sound", [audioSlider(a, "Volume", "volume", 0, 1.5, 0.05, a.volume, pct),
                      audioSlider(a, "Rises to", "volumeEnd", 0, 1.5, 0.01, endLevel(a), v => (Math.abs(v - a.volume) < 0.005 ? "Steady" : pct(v))),
                      audioSlider(a, "Fade in", "fadeIn", 0, Math.min(5, a.dur / 2), 0.1, Math.min(a.fadeIn || 0, a.dur / 2), off),
                      audioSlider(a, "Fade out", "fadeOut", 0, Math.min(5, a.dur / 2), 0.1, Math.min(a.fadeOut || 0, a.dur / 2), off)]),
    section("Timing", [audioSlider(a, "Starts at", "start", 0, Math.max(60, a.start + 10), 0.05, a.start, secs)])];
}

// ----- Preview mix -----

const soundPlayers = new Map();
let soundIdList, soundIdCount = -1, soundIds;
let lastPlaying = 0;

// Where a sound's level ends up: the same as it starts unless it slides.
const endLevel = a => (a.volumeEnd === undefined || a.volumeEnd === null ? a.volume : a.volumeEnd);

function soundGain(a, t, uncapped) {
  const fadeIn = Math.min(a.fadeIn || 0, a.dur / 2), fadeOut = Math.min(a.fadeOut || 0, a.dur / 2);
  const rise = fadeIn ? Math.min(1, (t - a.start) / fadeIn) : 1, fall = fadeOut ? Math.min(1, (a.start + a.dur - t) / fadeOut) : 1;
  const level = a.volume + (endLevel(a) - a.volume) * Math.min(1, Math.max(0, (t - a.start) / a.dur));
  const gain = Math.max(0, level * rise * fall);
  return uncapped ? gain : Math.min(1, gain);
}

function stopSounds() {
  soundPlayers.forEach(el => { if (!el.paused) el.pause(); });
}

// Called every frame while the Short previews: play each sound that is due, in step with the timeline.
function syncSounds() {
  const items = audioOf(), t = preview.elapsed || 0;
  if (!video.paused) lastPlaying = performance.now();
  const sinceVideo = performance.now() - lastPlaying;
  // Between two clips the video seeks and the clock stands still; songs ride through that instead of cutting out.
  const switching = preview.on && !preview.done && !preview.live;
  const playing = preview.on && !preview.done && sinceVideo < 400;
  const carried = playing || (switching && sinceVideo < 2500);
  if (soundIdList !== items || soundIdCount !== items.length) {
    soundIdList = items;
    soundIdCount = items.length;
    soundIds = new Set(items.map(a => a.id));
  }
  soundPlayers.forEach((el, id) => { if (!soundIds.has(id)) { el.pause(); soundPlayers.delete(id); } });
  for (const a of items) {
    const due = t >= a.start && t < a.start + a.dur;
    let el = soundPlayers.get(a.id);
    // A zero-to-zero level cannot contribute audio. Keep audible ramps loaded,
    // and retain existing players so unmuting can seek and resume immediately.
    if (a.volume === 0 && endLevel(a) === 0) {
      if (el) {
        setPlaybackValue(el, "volume", 0);
        if (!el.paused) el.pause();
      }
      continue;
    }
    if (!el && t >= a.start - 3 && t < a.start + a.dur) {
      el = new Audio(`/audio-file/${a.file}`);
      el.preload = "auto";
      soundPlayers.set(a.id, el);
    }
    if (!el) continue;
    const song = a.kind === "song";
    if (!((song ? carried : playing) && due)) { if (!el.paused) el.pause(); continue; }
    const want = a.in + (t - a.start);
    if (el.paused || Math.abs(el.currentTime - want) > (song ? 1 : 0.35)) el.currentTime = want;
    setPlaybackValue(el, "volume", soundGain(a, t));
    setPlaybackValue(el, "muted", previewMuted);
    if (el.paused) el.play().catch(() => {});
  }
}

// ----- Voice only in the preview -----

// A voice-only clip is heard from its isolated wav, in step with its picture, while the picture's own sound is muted.
// Called every frame, so it owns the mute of whichever players are on screen: a clip with no voice, or whose voice is
// still being isolated, is heard as it is. A player that is no longer on screen pauses.
const voicePlayers = new Map();
function syncVoices() {
  const active = [];
  if (preview.on && !preview.done) {
    const top = state.project.clips[preview.idx];
    if (top) active.push([video, top]);
    laneVids.forEach((el, n) => { if (lowNow[n] && lowNow[n].clip) active.push([el, lowNow[n].clip]); });
  }
  const used = new Set();
  for (const [el, clip] of active) {
    const url = typeof voiceUrl === "function" ? voiceUrl(clip) : null;
    if (!url) {
      setPlaybackValue(el, "muted", previewMuted || playVolume(clip) === 0);
      continue;
    }
    const key = voiceKey(clip);
    used.add(key);
    let player = voicePlayers.get(key);
    if (!player) {
      player = new Audio(url);
      player.preload = "auto";
      voicePlayers.set(key, player);
    }
    setPlaybackValue(el, "muted", true);
    // The wav starts at the clip's in point, so its time is the source time past that point.
    const want = Math.max(0, tnow(el) - clip.in);
    setPlaybackValue(player, "playbackRate", el.playbackRate);
    setPlaybackValue(player, "volume", Math.min(1, volumeOf(clip)));
    setPlaybackValue(player, "muted", previewMuted || playVolume(clip) === 0);
    if (el.paused) {
      if (!player.paused) player.pause();
      if (Math.abs(player.currentTime - want) > 0.05) player.currentTime = want;
      continue;
    }
    if (Math.abs(player.currentTime - want) > 0.3) player.currentTime = want;
    if (player.paused) player.play().catch(() => {});
  }
  voicePlayers.forEach((player, key) => { if (!used.has(key) && !player.paused) player.pause(); });
}

// ----- Dropping a sound onto the timeline -----

// Anywhere on the timeline takes the drop: the sound lands at that point in time, and a ghost shows where.
function soundStartAt(e) {
  const track = timeTrack();
  if (!track) return 0;
  return Math.max(0, Math.round((e.clientX - track.getBoundingClientRect().left) / audioScale.pps * 20) / 20);
}

function showGhost(start) {
  const track = $("stlBody").querySelector(".stl-track.audio");
  if (!track || !draggingSound) return;
  let ghost = track.querySelector(".stl-ghost");
  if (!ghost) {
    ghost = document.createElement("div");
    ghost.className = "stl-ghost";
    track.appendChild(ghost);
  }
  const dur = draggingSound.kind === "sfx" ? draggingSound.duration : Math.min(draggingSound.duration, 30);
  Object.assign(ghost.style, {left: `${start * audioScale.pps}px`, width: `${Math.max(dur * audioScale.pps, 14)}px`, top: "4px"});
  ghost.textContent = `${draggingSound.name} at ${secs(start)}`;
  track.classList.add("over");
}

function endSoundDrag() {
  draggingSound = null;
  document.body.classList.remove("sdrag");
  $("stlBody").querySelectorAll(".stl-ghost").forEach(g => g.remove());
  $("stlBody").querySelectorAll(".stl-track.over").forEach(t => t.classList.remove("over"));
}

$("stlBody").addEventListener("dragover", e => {
  if (!hasAudioDrag(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
  showGhost(soundStartAt(e));
});
$("stlBody").addEventListener("dragleave", e => {
  if (hasAudioDrag(e) && !$("stlBody").contains(e.relatedTarget)) endSoundDrag();
});
$("stlBody").addEventListener("drop", e => {
  if (!hasAudioDrag(e)) return;
  e.preventDefault();
  const file = audioInfo(e.dataTransfer.getData(AUDIO_MIME)) || draggingSound;
  const start = soundStartAt(e);
  endSoundDrag();
  if (file) addAudio(file, start);
});

// ----- Wiring -----

$("tabAudio").onclick = () => setSideTab("audio");
refreshAudio();
