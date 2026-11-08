// Short mode: the preview with its size and layout pickers, the clip bank, the lane timeline and the clip details.
// Shares globals with app.js (state, render, changed, the field builders). In Short mode state.project.clips is the
// timeline and state.project.other is the clip bank; in Clip mode they swap. See canon() and orient() in app.js.

const CLIP_MIME = "application/x-clip";
const LANE_NAMES = {top: "Lane 1", bottom: "Lane 2", third: "Lane 3", fourth: "Lane 4"};
const TL_SECONDS = 60;
const stlBody = $("stlBody");
const inShort = () => state.mode === "short";
const timelineOf = () => (inShort() ? state.project.clips : state.project.other || []);
const bankOf = () => (inShort() ? state.project.other || [] : state.project.clips);

function newTimelineItem(c, lane = "top") {
  const bottom = lane !== "top";
  const fill = bottom || splitOn();
  return {src: c.src, in: c.in, out: c.out, note: c.note || "", thumb: c.thumb || "", caption: "", speed: 1,
    volume: c.volume !== undefined ? c.volume : 0, fit: fill ? "fill" : "fit", pan: 0.5, effect: "none", ramp: "none", freeze: 0, lane};
}

function setTimeline(next) {
  state.project = inShort() ? {...state.project, clips: next} : {...state.project, other: next};
}

// Where in the whole timeline a clip dropped at slot k of a lane belongs: before that lane's k-th clip, or after its last.
function laneInsertAt(list, lane, k) {
  if (k === Infinity) {
    for (let i = list.length - 1; i >= 0; i--) if (i in list && laneOf(list[i]) === lane) return i + 1;
    return list.length;
  }
  if (Number.isInteger(k) && k >= 0) {
    let slot = 0, last = -1;
    for (let i = 0; i < list.length; i++) {
      if (!(i in list) || laneOf(list[i]) !== lane) continue;
      if (slot++ === k) return i;
      last = i;
    }
    return last < 0 ? list.length : last + 1;
  }
  const inLane = list.flatMap((c, i) => (laneOf(c) === lane ? [i] : []));
  if (k < inLane.length) return inLane[k];
  return inLane.length ? inLane[inLane.length - 1] + 1 : list.length;
}

function insertClip(clip, lane, k = Infinity) {
  const list = timelineOf();
  const at = laneInsertAt(list, lane, k);
  setTimeline([...list.slice(0, at), newTimelineItem(clip, lane), ...list.slice(at)]);
  if (lane === "top") setTimeout(() => captionFromSubtitles(clip), 0);
  return at;
}

function addToShort(clip, lane = "top") {
  const at = insertClip(clip, lane);
  if (inShort()) state.sel = at;
  changed();
  toast(inShort() ? "Added to the timeline" : "Added to the Short");
}

// k counts the lane's clips without the one being moved, as slotFromX does while it is dragged.
function moveClip(from, lane, k) {
  const list = timelineOf();
  const moving = list[from];
  if (!moving) return;
  const rest = list.filter((_, i) => i !== from);
  const at = laneInsertAt(rest, lane, k);
  const shifted = {...moving, lane, ...(laneOf(moving) !== lane && lane !== "top" ? {volume: 0} : {})};
  setTimeline([...rest.slice(0, at), shifted, ...rest.slice(at)]);
  state.sel = at;
}

function pickClip(i) {
  picked.clear();
  state.sel = i;
  state.audioSel = null;
  setTab("details");
  render();
}

function restartPreviewAt(i) {
  if (!inShort() || !preview.on) return;
  buildSegs();
  startPreviewAt(Math.min(Math.max(i, 0), state.project.clips.length - 1));
}

function dropOnLane(e, lane) {
  e.preventDefault();
  const k = slotFromX(e, lane);
  dragPx = 0;
  clearSlots();
  const dropped = e.dataTransfer.getData(CLIP_MIME);
  if (laneLocked(lane)) return lockedToast();
  if (!dropped) return;
  try {
    const at = insertClip(JSON.parse(dropped), lane, k);
    state.sel = at;
    changed();
    restartPreviewAt(at);
  } catch {
    toast("Couldn't add that clip");
  }
}

const laneTrack = lane => stlBody.querySelector(`.stl-track[data-lane="${lane}"]`);

function slotFromX(e, lane, blocks = [...laneTrack(lane).querySelectorAll(".stl-clip:not(.dragging)")]) {
  const slot = blocks.findIndex(b => {
    const r = b.getBoundingClientRect();
    return e.clientX < r.left + r.width / 2;
  });
  return slot < 0 ? blocks.length : slot;
}

// Width in pixels of the clip being dragged, so the others can open a gap of that size.
let dragPx = 0, stlPps = 0, stlBasePps = 0, tlZoom = 1;

function clearMarks() {
  stlBody.querySelectorAll(".slot-before,.slot-end,.over").forEach(el => el.classList.remove("slot-before", "slot-end", "over"));
}

function clearSlots() {
  clearMarks();
  stlBody.classList.remove("making-room");
  stlBody.querySelectorAll(".stl-clip").forEach(b => { b.style.transform = ""; });
}

// Slide the clips at and after the slot along to open a gap the size of the dragged clip. A clip dragged within its own
// lane closes the gap it left behind and slides into the new one.
function makeRoom(track, blocks, ghost, k) {
  const w = dragPx, local = ghost && ghost.parentElement === track;
  const ghostLeft = local ? ghost.offsetLeft : 0;
  let origin = null;
  if (local) {
    origin = 0;
    for (const b of track.querySelectorAll(".stl-clip")) if (b !== ghost && b.offsetLeft < ghostLeft) origin++;
  }
  const shift = j => (j >= k ? w : 0) - (origin !== null && j >= origin ? w : 0);
  let ghostOffset = 0;
  if (local) {
    const last = blocks[blocks.length - 1];
    const at = k < blocks.length ? blocks[k].offsetLeft + shift(k) - w : last ? last.offsetLeft + last.offsetWidth + shift(blocks.length - 1) : 0;
    ghostOffset = at - ghostLeft;
  }
  stlBody.classList.add("making-room");
  stlBody.querySelectorAll(".stl-clip:not(.dragging)").forEach(b => { if (!track.contains(b)) setPlaybackValue(b.style, "transform", ""); });
  blocks.forEach((b, j) => { const dx = shift(j); setPlaybackValue(b.style, "transform", dx ? `translateX(${dx}px)` : ""); });
  if (local) setPlaybackValue(ghost.style, "transform", `translateX(${ghostOffset}px)`);
}

function showSlot(e, lane) {
  clearMarks();
  const track = laneTrack(lane);
  track.classList.add("over");
  const blocks = [...track.querySelectorAll(".stl-clip:not(.dragging)")];
  const k = slotFromX(e, lane, blocks);
  if (dragPx) makeRoom(track, blocks, stlBody.querySelector(".stl-clip.dragging"), k);
  else if (k < blocks.length) blocks[k].classList.add("slot-before");
  else track.classList.add("slot-end");
}

const clipPeaks = new Map();
function peaksOfVideo(v) {
  if (!clipPeaks.has(v.id)) clipPeaks.set(v.id, api(`/api/wave/${v.id}`).catch(() => { clipPeaks.delete(v.id); return null; }));
  return clipPeaks.get(v.id);
}

// The sound this clip plays, as bars along its block, scaled by the clip's volume so a muted clip reads flat.
async function drawClipWave(canvas, c, v) {
  if (!canvas.isConnected) return;
  const wave = await peaksOfVideo(v);
  if (!wave || !wave.peaks.length || !canvas.isConnected) return;
  const w = canvas.clientWidth, h = canvas.clientHeight, ratio = window.devicePixelRatio || 1;
  if (!w || !h) return;
  const g = prepareWaveCanvas(canvas, w, h, ratio);
  g.fillStyle = "rgba(232,224,210,.78)";
  const step = 3, mid = h / 2, gain = volumeOf(c) === 0 ? 0 : Math.min(1, volumeOf(c));
  for (let x = 0; x < w; x += step) {
    const t0 = c.in + (x / w) * (c.out - c.in), t1 = c.in + (Math.min(w, x + step) / w) * (c.out - c.in);
    const from = Math.floor(t0 * wave.per_sec), to = Math.max(from + 1, Math.ceil(t1 * wave.per_sec));
    let peak = 0;
    if (gain !== 0) for (let i = from; i < to && i < wave.peaks.length; i++) peak = Math.max(peak, wave.peaks[i]);
    const pos = (x / w) * (c.out - c.in), len = c.out - c.in;
    const rise = c.fadeIn ? Math.min(1, pos / c.fadeIn) : 1, fall = c.fadeOut ? Math.min(1, (len - pos) / c.fadeOut) : 1;
    const bar = Math.max(1.5, (peak / 255) * gain * rise * fall * (h - 2));
    g.fillRect(x, mid - bar / 2, step - 1, bar);
  }
}

function clipBlock(c, gi, left, width, dim) {
  const v = byPath(c.src);
  const key = [gi, left, width, dim, gi === state.sel, picked.has(gi), laneLocked(laneOf(c)),
    v, v?.name, c.src, c.thumb, c.note, outLen(c)];
  const cache = clipBlock.cache ||= new WeakMap(), previous = cache.get(c) || clipBlock.previous?.get(c);
  if (previous && key.every((value, i) => value === previous.key[i])) {
    cache.set(c, previous);
    return previous.node;
  }
  const b = document.createElement("div");
  b.className = "stl-clip" + (gi === state.sel ? " sel" : "") + (picked.has(gi) ? " multi" : "") + (dim ? " beyond" : "");
  b.style.left = `${left}px`;
  b.style.width = `${Math.max(width, 28)}px`;
  b.style.backgroundImage = c.thumb ? `url(${JSON.stringify(c.thumb)})` : "";
  b.tabIndex = 0;
  b.classList.toggle("locked", laneLocked(laneOf(c)));
  b.dataset.gi = gi;
  b.title = `${v ? v.name.replace(/\.[^.]+$/, "") : "Missing video"}, ${outLen(c).toFixed(1)}s`;
  b.innerHTML = `${c.thumb ? `<img alt="" src="${c.thumb}">` : ""}<b class="stl-name">${esc(c.note || clipName(c))}</b><span class="stl-len num">${outLen(c).toFixed(1)}s</span>` +
    '<i class="th l" title="Drag to trim the start. Shift-drag to roll the cut with the clip before"></i><i class="th r" title="Drag to trim the end. Shift-drag to roll the cut with the clip after"></i>';
  for (const side of ["l", "r"]) {
    const h = b.querySelector(`.th.${side}`);
    if (h) {
      h.draggable = false;
      h.onpointerdown = ev => trimOnTimeline(ev, gi, side, b);
      h.onclick = ev => ev.stopPropagation();
    }
  }
  b.addEventListener("pointerdown", e => {
    if (e.altKey && !e.button && !e.target.closest(".stl-del, .th") && !blockedByLock(gi)) return slipOnTimeline(e, gi, b);
    if (!razor) startLaneDrag(e, gi, b);
  });
  b.onclick = e => {
    if (b.dataset.moved) return void delete b.dataset.moved;
    if (razor) return razorCut(gi, b, e);
    if (e.shiftKey || e.metaKey || e.ctrlKey) return pickMore(gi, e);
    pickClip(gi);
    restartPreviewAt(isTop(c) ? gi : preview.idx);
  };
  b.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickClip(gi); } };
  b.ondragover = e => { if (isEffectDrag(e)) { e.preventDefault(); b.classList.add("fx-over"); } };
  b.ondragleave = () => b.classList.remove("fx-over");
  b.ondrop = e => {
    if (!isEffectDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    b.classList.remove("fx-over");
    document.body.classList.remove("tdrag");
    if (!isTransitionDrag(e)) return dropEffect(e, gi);
    const r = b.getBoundingClientRect();
    dropEffect(e, e.clientX < r.left + r.width / 2 ? gi : nextInLane(gi));
  };
  cache.set(c, {key, node: b});
  return b;
}

// A seam is the join between two clips: a diamond when it has a transition, an invisible drop target until you drag one.
function seamButton(c, gi, x, first = firstInLane(gi)) {
  const on = transitionOf(c) !== "none";
  const b = document.createElement("button");
  b.className = `stl-seam${on ? " on" : ""}${first ? " intro" : ""}`;
  b.style.left = `${x}px`;
  const into = first ? "from black into" : "into";
  b.setAttribute("aria-label", on ? `${TRANSITION_NAMES[transitionOf(c)]} ${into} clip ${gi + 1}` : `Add a transition ${into} clip ${gi + 1}`);
  b.title = on ? `${TRANSITION_NAMES[transitionOf(c)]}, ${tlenOf(c).toFixed(1)}s. Click to change` : first ? "Drop a transition here to start the Short with it" : "Drop a transition here";
  b.innerHTML = "<i></i>";
  b.onclick = e => { e.stopPropagation(); pickClip(gi); railShow("transitions"); };
  b.ondragover = e => { if (isTransitionDrag(e)) { e.preventDefault(); b.classList.add("fx-over"); } };
  b.ondragleave = () => b.classList.remove("fx-over");
  b.ondrop = e => {
    if (!isTransitionDrag(e)) return;
    e.preventDefault();
    e.stopPropagation();
    b.classList.remove("fx-over");
    document.body.classList.remove("tdrag");
    dropEffect(e, gi);
  };
  return b;
}

function nextInLane(gi) {
  const clips = state.project.clips, start = Math.max(0, Math.floor(gi) + 1);
  if (Number.isNaN(start) || start >= clips.length) return -1;
  const lane = laneOf(clips[gi]);
  for (let i = start; i < clips.length; i++) if (laneOf(clips[i]) === lane) return i;
  return -1;
}

function removeFromTimeline(i) {
  if (!state.project.clips[i] || blockedByLock(i)) return;
  removeClip(i);
  restartPreviewAt(Math.min(i, state.project.clips.length - 1));
}

function laneTotal(lane, list) {
  let sum = 0, prev, prevLen;
  for (const c of list) {
    if (laneOf(c) !== lane) continue;
    const len = outLen(c);
    sum = sum + len - seamOverlap(prev, c, prevLen, len);
    prev = c;
    prevLen = len;
  }
  return sum;
}

// Rendering needs every lane's length; collect them together instead of rescanning for each lane.
function laneTotals(list, lanes) {
  const sums = new Map(), previous = new Map(), wanted = lanes && new Set(lanes);
  for (const c of list) {
    const lane = laneOf(c);
    if (wanted && !wanted.has(lane)) continue;
    const len = outLen(c);
    sums.set(lane, (sums.get(lane) ?? 0) + len - seamOverlap(previous.get(lane), c, undefined, len));
    previous.set(lane, c);
  }
  return sums;
}

// How far apart the numbers and the small ticks fall, so the ruler stays readable at every zoom: [numbers, ticks] in seconds.
const RULER_STEPS = [[0.5, 0.1], [1, 0.2], [2, 0.5], [5, 1], [10, 2], [15, 5], [30, 5], [60, 10]];
const rulerStep = pps => RULER_STEPS.find(([label]) => label * pps >= 56) || RULER_STEPS[RULER_STEPS.length - 1];

// The ruler: numbers and ticks that follow the zoom, markers, and a flag where the Short ends.
function shortRuler(span, topLen) {
  const ruler = document.createElement("div");
  ruler.className = "sruler num";
  ruler.onpointerdown = startScrub;
  const at = t => `${(t / span * 100).toFixed(3)}%`;
  const ok = topLen <= SHORT_LIMIT;
  const [labelStep, tickStep] = rulerStep(stlPps), per = Math.round(labelStep / tickStep);
  let html = "";
  for (let n = 0; n * tickStep <= span + 1e-6; n++) {
    const t = n * tickStep, major = n % per === 0;
    html += `<i class="rtick${major ? " m" : ""}" style="left:${at(t)}"></i>`;
    if (major) html += `<span class="lb${t === 0 ? " f" : ""}" style="left:${at(t)}">${+t.toFixed(1)}${Math.abs(t - span) < 1e-6 ? "s" : ""}</span>`;
  }
  if (topLen > 0) html += `<b class="rend${ok ? " ok" : ""}" style="left:${at(Math.min(topLen, span))}" title="Length of the Short">${topLen.toFixed(1)}s</b>`;
  ruler.innerHTML = html;
  paintMarkers(ruler, span);
  return ruler;
}

// Drag the end of the selected clip to trim it. Dragging the left end moves its in point, the right end its out point.
// Everything on the timeline that moves when clip gi changes length, measured once when a trim starts: the clips after it
// in its lane and their sound, which shift by the change, and its own sound and the caption over it, which grow with it.
function rippleLane(gi, lane) {
  const clips = state.project.clips, inLane = i => laneOf(clips[i]) === lane, after = i => i > gi && inLane(i);
  const blocks = [...stlBody.querySelectorAll(".stl-clip")].filter(b => after(Number(b.dataset.gi)));
  const sounds = [...stlBody.querySelectorAll(".stl-snd")];
  const chips = lane === "top" ? [...stlBody.querySelectorAll(".stl-cap")] : [];
  const own = [...sounds.filter(s => Number(s.dataset.gi) === gi), ...chips.filter(ch => Number(ch.dataset.head) <= gi && gi <= Number(ch.dataset.last))]
    .map(el => ({el, width: parseFloat(el.style.width) || 0}));
  const shifted = [...blocks, ...sounds.filter(s => after(Number(s.dataset.gi))), ...chips.filter(ch => Number(ch.dataset.head) > gi)];
  return {
    apply(dx) {
      for (const el of shifted) el.style.transform = dx ? `translateX(${dx}px)` : "";
      for (const {el, width} of own) el.style.width = `${Math.max(28, width + dx)}px`;
    },
    clear() { for (const el of shifted) el.style.transform = ""; },
  };
}

function trimOnTimeline(e, gi, side, block) {
  if (blockedByLock(gi)) return;
  if (e.shiftKey && rollOnTimeline(e, gi, side, block)) return;
  e.preventDefault();
  e.stopPropagation();
  const c0 = state.project.clips[gi], v = byPath(c0.src), speed = speedOf(c0), x0 = e.clientX, width0 = outLen(c0) * stlPps;
  // A lane is a chain, so the clip keeps its left edge on either trim and the lane after it follows the change live.
  const ripple = rippleLane(gi, laneOf(c0));
  let next = c0;
  block.setPointerCapture(e.pointerId);
  stlBody.classList.add("trimming");
  const move = ev => {
    const dt = (ev.clientX - x0) / stlPps * speed;
    next = side === "l" ? {...c0, in: Math.min(Math.max(0, c0.in + dt), c0.out - MIN_CLIP)}
      : {...c0, out: Math.max(Math.min(v ? v.duration : Infinity, c0.out + dt), c0.in + MIN_CLIP)};
    next = snapTrim(next, c0, gi, side, v, ev.altKey);
    const width = outLen(next) * stlPps;
    block.style.width = `${Math.max(width, 28)}px`;
    ripple.apply(width - width0);
  };
  const up = () => {
    block.removeEventListener("pointermove", move);
    block.removeEventListener("pointerup", up);
    block.removeEventListener("pointercancel", up);
    hideSnapLine();
    stlBody.classList.remove("trimming");
    ripple.clear();
    if (next === c0) return;
    setClipField(gi, {in: next.in, out: next.out});
    restartPreviewAt(gi);
  };
  block.addEventListener("pointermove", move);
  block.addEventListener("pointerup", up);
  block.addEventListener("pointercancel", up);
}

function laneRow(lane, list, pps, topLen) {
  const row = document.createElement("div");
  row.className = "stl-lane";
  const track = document.createElement("div");
  track.className = "stl-track";
  track.dataset.lane = lane;
  let at = 0, prev = null, prevLen;
  const seams = [];
  list.forEach((c, gi) => {
    if (laneOf(c) !== lane) return;
    const len = outLen(c), overlap = seamOverlap(prev, c, prevLen, len);
    at -= overlap;
    const block = clipBlock(c, gi, at * pps, len * pps, lane !== "top" && at >= topLen - 0.01);
    Object.assign(block.dataset, {t0: at, t1: at + len, lane});
    track.appendChild(block);
    if (prev) seams.push(seamButton(c, gi, (at + overlap / 2) * pps, false));
    else seams.push(seamButton(c, gi, Math.max(14, introLength(c) / 2 * pps), true));
    at += len;
    prev = c;
    prevLen = len;
  });
  track.append(...seams);
  track.classList.toggle("hole", lane !== "top" && !track.querySelector(".stl-clip"));
  track.classList.toggle("lane-muted", laneMuted(lane) || laneDimmedBySolo(lane));
  track.classList.toggle("lane-locked", laneLocked(lane));
  track.ondragover = e => {
    if (e.dataTransfer.types.includes(CLIP_MIME)) {
      e.preventDefault();
      showSlot(e, lane);
    }
  };
  track.ondragleave = e => { if (!track.contains(e.relatedTarget)) clearSlots(); };
  track.ondrop = e => dropOnLane(e, lane);
  row.append(track);
  return row;
}

// One clip's sound on its track, edited like a standard editor: a level line across the clip, dots at its ends to fade, and a readout while you drag.
const SND_NS = "http://www.w3.org/2000/svg";
let sndTip = null;
function showSndTip(x, y, text) {
  if (!sndTip) { sndTip = Object.assign(document.createElement("div"), {className: "snd-tip num"}); document.body.append(sndTip); }
  sndTip.textContent = text;
  Object.assign(sndTip.style, {left: `${x}px`, top: `${y}px`, display: "block"});
}
const hideSndTip = () => { if (sndTip) sndTip.style.display = "none"; };

function soundBlock(c, gi, at, pps, v) {
  const busy = voiceWorking.has(voiceKey(c));
  const key = [gi, at, pps, v, gi === state.sel || picked.has(gi), busy, laneCount(),
    window.devicePixelRatio || 1, clipPeaks.get(v.id), outLen(c), c.in, c.out, c.volume, c.fadeIn, c.fadeOut, c.voice];
  const cache = soundBlock.cache ||= new WeakMap(), previous = cache.get(c) || soundBlock.previous?.get(c);
  if (previous && key.every((value, i) => value === previous.key[i])) {
    cache.set(c, previous);
    const pending = previous.node._deferredPaint;
    if (pending && !pending.done) requestAnimationFrame(() => paintWhenVisible(previous.node, pending.paint));
    return previous.node;
  }
  const box = document.createElement("div");
  box.className = "stl-snd" + (gi === state.sel || picked.has(gi) ? " sel" : "");
  box.dataset.gi = gi;
  Object.assign(box.style, {left: `${at * pps}px`, width: `${Math.max(outLen(c) * pps, 28)}px`});
  const canvas = document.createElement("canvas");
  canvas.className = "stl-wave";
  box.classList.toggle("busy", busy);
  if (c.voice) box.classList.add("voice");
  if (busy) box.append(Object.assign(document.createElement("span"), {className: "snd-busy", textContent: `Isolating voice, ${voiceEstimate(c)}`}));
  const svg = document.createElementNS(SND_NS, "svg");
  svg.setAttribute("class", "snd-env");
  const unity = document.createElement("i");
  unity.className = "snd-unity";
  const slope = document.createElementNS(SND_NS, "polyline");
  svg.append(slope);
  const line = document.createElement("i");
  line.className = "snd-vol";
  line.title = "Drag up or down for this clip's sound. Double-click for 100%.";
  const dots = ["fadeIn", "fadeOut"].map(key => {
    const d = document.createElement("i");
    d.className = `snd-fade ${key === "fadeIn" ? "l" : "r"}`;
    d.title = key === "fadeIn" ? "Drag to fade in. Double-click to clear." : "Drag to fade out. Double-click to clear.";
    return d;
  });
  const paint = cur => {
    const h = box.clientHeight || 44, w = box.clientWidth || 28, vol = volumeOf(cur);
    const y = (1 - Math.min(vol, MAX_VOLUME) / MAX_VOLUME) * h;
    const fi = Math.min(cur.fadeIn || 0, outLen(cur) / 2) * pps, fo = Math.min(cur.fadeOut || 0, outLen(cur) / 2) * pps;
    slope.setAttribute("points", `${fi ? `0,${h} ` : ""}${fi},${y} ${w - fo},${y}${fo ? ` ${w},${h}` : ""}`);
    unity.style.top = `${(1 - 1 / MAX_VOLUME) * h}px`;
    Object.assign(line.style, {top: `${y}px`, left: `${fi}px`, right: `${fo}px`});
    line.classList.toggle("off", vol === 0);
    dots[0].style.cssText = `left:${fi}px;top:${y}px`;
    dots[1].style.cssText = `right:${fo}px;top:${y}px`;
  };
  const edit = (patch, redraw) => {
    const cur = {...state.project.clips[gi], ...patch};
    state.project = {...state.project, clips: state.project.clips.map((x, n) => (n === gi ? cur : x))};
    if (redraw) drawClipWave(canvas, cur, v);
    paint(cur);
    return cur;
  };
  const drag = (e, move, tip) => {
    e.preventDefault();
    e.stopPropagation();
    const el = e.currentTarget, rect = box.getBoundingClientRect();
    el.setPointerCapture(e.pointerId);
    box.classList.add("editing");
    const onMove = ev => { move(ev, rect); showSndTip(ev.clientX + 14, ev.clientY - 30, tip(state.project.clips[gi])); };
    const onUp = () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      box.classList.remove("editing");
      hideSndTip();
      changed();
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    onMove(e);
  };
  line.onclick = e => e.stopPropagation();
  line.ondblclick = () => setClipField(gi, {volume: 1});
  line.onpointerdown = e => drag(e, (ev, rect) => {
    let volume = (1 - Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height))) * MAX_VOLUME;
    if (Math.abs(volume - 1) < 0.07) volume = 1;
    volume = clampVolume(volume);
    if (volume === volumeOf(state.project.clips[gi])) return;
    const cur = edit({volume}, true);
    if (gi === state.sel) applyLiveSound(cur);
  }, cur => (volumeOf(cur) === 0 ? "Muted" : percent(volumeOf(cur))));
  dots.forEach((d, n) => {
    const key = n ? "fadeOut" : "fadeIn";
    d.onclick = e => e.stopPropagation();
    d.ondblclick = () => setClipField(gi, {[key]: 0});
    d.onpointerdown = e => drag(e, (ev, rect) => {
      const dx = n ? rect.right - ev.clientX : ev.clientX - rect.left;
      const secs = Math.min(3, outLen(state.project.clips[gi]) / 2, Math.max(0, Math.round(dx / pps * 10) / 10));
      edit({[key]: Number(secs.toFixed(1))});
    }, cur => `${n ? "Fade out" : "Fade in"} ${secs(cur[key] || 0)}`);
  });
  box.onclick = () => pickClip(gi);
  box.append(canvas, unity, svg, line, ...dots);
  requestAnimationFrame(() => paintWhenVisible(box, async () => { paint(c); await drawClipWave(canvas, c, v); }));
  cache.set(c, {key, node: box});
  return box;
}

// The top-lane clip playing at x on the timeline, if any.
function topClipAt(x, track) {
  const t = (x - track.getBoundingClientRect().left) / stlPps;
  const block = [...stlBody.querySelectorAll(".stl-clip")].find(b => b.dataset.lane === "top" && t >= Number(b.dataset.t0) && t < Number(b.dataset.t1));
  return block ? Number(block.dataset.gi) : -1;
}

// Move a caption to another clip by dragging its chip there. The clip it lands on gives its caption back, so nothing is lost.
const CAP_DRAG_MIN = 4;
function dragCaption(e, from, chip, track) {
  if (e.button !== 0 || blockedByLock(from)) return;
  const x0 = e.clientX;
  let dragging = false;
  const move = ev => {
    if (!dragging && Math.abs(ev.clientX - x0) < CAP_DRAG_MIN) return;
    dragging = true;
    chip.classList.add("dragging");
    chip.style.transform = `translateX(${ev.clientX - x0}px)`;
  };
  const up = ev => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    window.removeEventListener("pointercancel", up);
    if (!dragging) return;
    chip.dataset.moved = "1";
    chip.classList.remove("dragging");
    chip.style.transform = "";
    const to = ev.type === "pointerup" ? topClipAt(ev.clientX, track) : -1;
    if (to >= 0 && to !== from) swapCaptions(from, to);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", up);
}

function swapCaptions(a, b) {
  const clips = state.project.clips;
  if (blockedByLock(b)) return;
  if (isSynced(clips[a]) || isSynced(clips[b])) return toast("A caption timed to speech stays with its clip");
  state.project = {...state.project, clips: clips.map((c, n) => (n === a ? {...c, caption: clips[b].caption || ""} : n === b ? {...c, caption: clips[a].caption || ""} : c))};
  changed();
  pickClip(b);
  toast("Caption moved");
}

// The captions of the top lane, on a track of their own above its clips. A caption covers its clip and the clips after it
// that have none of their own (see captionOf), so a chip is as long as that run.
function captionRuns(list) {
  const runs = [];
  let carrying = false;
  list.forEach((c, gi) => {
    if (!isTop(c)) return;
    if (c.caption) {
      runs.push({head: gi, last: gi, text: c.caption});
      carrying = !isSynced(c);
    } else if (c.capStop) carrying = false;
    else if (carrying) runs[runs.length - 1].last = gi;
  });
  return runs;
}

function textRow(list, pps) {
  const row = document.createElement("div");
  row.className = "stl-lane";
  const track = document.createElement("div");
  track.className = "stl-track cliptext";
  const start = {}, end = {};
  let at = 0, prev = null;
  list.forEach((c, gi) => {
    if (!isTop(c)) return;
    at -= seamOverlap(prev, c);
    start[gi] = at;
    at += outLen(c);
    end[gi] = at;
    prev = c;
  });
  for (const run of captionRuns(list)) {
    const chip = document.createElement("div");
    let selected = false;
    for (let n = run.head; n <= run.last; n++) {
      if (isTop(list[n]) && (n === state.sel || picked.has(n))) { selected = true; break; }
    }
    chip.className = "stl-cap" + (selected ? " sel" : "");
    chip.append(Object.assign(document.createElement("span"), {textContent: run.text}), Object.assign(document.createElement("i"), {className: "cap-r", title: "Drag to make the caption cover more or fewer clips"}));
    chip.title = `Caption: ${run.text}`;
    Object.assign(chip.dataset, {head: run.head, last: run.last});
    Object.assign(chip.style, {left: `${start[run.head] * pps}px`, width: `${Math.max((end[run.last] - start[run.head]) * pps, 28)}px`});
    chip.onclick = () => { if (chip.dataset.moved) return void delete chip.dataset.moved; pickClip(run.head); restartPreviewAt(run.head); };
    chip.onpointerdown = e => (e.target.classList.contains("cap-r") ? resizeCaption(e, run, chip, track) : dragCaption(e, run.head, chip, track));
    track.appendChild(chip);
  }
  row.hidden = !track.children.length;
  row.append(track);
  return row;
}

// Drag the end of a caption to the clip it should reach. A clip with a caption of its own ends it, and one after the end is
// marked to stop the caption carrying on into it.
function resizeCaption(e, run, chip, track) {
  const list = state.project.clips, order = list.map((_, n) => n).filter(n => isTop(list[n]));
  if (e.button !== 0 || order.slice(order.indexOf(run.head), order.indexOf(run.last) + 1).some(blockedByLock)) return;
  e.preventDefault();
  e.stopPropagation();
  const left = chip.getBoundingClientRect().left;
  const move = ev => { chip.style.width = `${Math.max(28, ev.clientX - left)}px`; };
  const up = ev => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    window.removeEventListener("pointercancel", up);
    chip.dataset.moved = "1";
    const hit = ev.type === "pointerup" ? topClipAt(ev.clientX, track) : -2;
    if (hit === -2) return render();
    const hp = order.indexOf(run.head), lp = order.indexOf(run.last);
    let ep = Math.max(hp, hit < 0 ? order.length - 1 : order.indexOf(hit));
    for (let k = hp + 1; k <= ep; k++) if (list[order[k]].caption) { ep = k - 1; break; }
    if (ep === lp) return render();
    const patch = {};
    for (let k = hp + 1; k <= ep; k++) patch[order[k]] = {capStop: false};
    if (ep < lp) patch[order[ep + 1]] = {capStop: true};
    state.project = {...state.project, clips: list.map((c, n) => (patch[n] ? {...c, ...patch[n]} : c))};
    changed();
    toast(`Caption covers ${ep - hp + 1} clip${ep === hp ? "" : "s"}`);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", up);
}

// The sound of a lane, on a track of its own right under its clips, each clip's part lined up with its block.
function soundRow(lane, list, pps) {
  const row = document.createElement("div");
  row.className = "stl-lane";
  const track = document.createElement("div");
  track.className = "stl-track clipsound";
  if (soundCollapsed(lane)) {
    row.hidden = true;
    row.append(track);
    return row;
  }
  let at = 0, prev = null, prevLen;
  list.forEach((c, c0) => {
    if (laneOf(c) !== lane) return;
    const len = outLen(c);
    at -= seamOverlap(prev, c, prevLen, len);
    const v = byPath(c.src);
    if (v) track.appendChild(soundBlock(c, c0, at, pps, v));
    at += len;
    prev = c;
    prevLen = len;
  });
  row.hidden = !track.children.length;
  row.append(track);
  return row;
}

function renderShortTl() {
  // Undo snapshots may retain clip objects; keep DOM nodes only for this render.
  for (const block of [clipBlock, soundBlock]) {
    block.previous = block.cache;
    block.cache = new WeakMap();
  }
  syncPicked();
  const list = state.project.clips, lanes = LANES.slice(0, laneCount());
  const lengths = laneTotals(list, lanes), topLen = lengths.get("top") ?? 0;
  const longest = Math.max(topLen, ...lanes.map(l => lengths.get(l) ?? 0));
  const span = Math.max(TL_SECONDS, Math.ceil(longest / 10) * 10);
  stlBasePps = Math.max(1, (stlBody.clientWidth - 28) / span);
  const pps = stlBasePps * tlZoom, keepScroll = stlBody.scrollLeft;
  stlPps = pps;
  stlBody.style.setProperty("--tlw", `${span * pps}px`);
  stlBody.classList.toggle("many", lanes.length > 2);
  stlBody.replaceChildren(shortRuler(span, topLen), ...lanes.flatMap(lane => [...(lane === "top" ? [textRow(list, pps)] : []), laneRow(lane, list, pps, topLen), soundRow(lane, list, pps)]), audioLane(pps, span, topLen));
  clipBlock.previous = soundBlock.previous = null;
  stlBody.scrollLeft = keepScroll;
  if (typeof paintWhenVisible === "function") paintWhenVisible.prune?.();
  paintLaneHeads(lanes);
  paintPlayhead();
}

// Split a clip of the Short in two, T seconds along its lane.
function splitClipAt(i, T) {
  const clips = state.project.clips, c = clips[i];
  if (!c || blockedByLock(i)) return;
  if (rampOf(c) !== "none") return toast("Set this clip to Normal speed before splitting it");
  const at = sourceAt(c, Math.min(Math.max(0, T - clipStarts(clips)[i]), movingLen(c)));
  if (at <= c.in + 0.1 || at >= c.out - 0.1) return toast("Move further into the clip to split it");
  const first = {...c, out: at, freeze: 0, fadeOut: 0};
  const second = {...c, in: at, caption: "", fadeIn: 0, transition: "none"};
  if (isSynced(c)) {
    first.caption = spokenText(first);
    second.caption = spokenText(second);
  }
  state.project = {...state.project, clips: [...clips.slice(0, i), first, second, ...clips.slice(i + 1)]};
  state.sel = i + 1;
  picked.clear();
  changed();
  restartPreviewAt(i + 1);
}

// Split the clip under the playhead. The selected clip is used when the playhead is on a lower lane.
function splitInShort() {
  const clips = state.project.clips, T = preview.elapsed || 0, starts = clipStarts(clips);
  const under = clips.findIndex((c, n) => isTop(c) && T >= starts[n] && T < starts[n] + outLen(c));
  const i = clips[state.sel] && !isTop(clips[state.sel]) ? state.sel : under;
  if (i < 0) return toast("Move the playhead onto a clip to split it");
  splitClipAt(i, T);
}

function renderBank() {
  const tray = $("tray");
  tray.innerHTML = "";
  const bank = bankOf();
  if (!bank.length) {
    tray.innerHTML = '<div class="empty tray-empty">No clips yet. Switch to Clip mode to cut some from your videos, or drag from Saved.</div>';
    return;
  }
  for (const i of [...bankSel]) if (i >= bank.length) bankSel.delete(i);
  if (bankSel.size) tray.appendChild(bankBar());
  const previousCache = renderBank.cache || new WeakMap();
  const cache = renderBank.cache = new WeakMap();
  bank.forEach((c, i) => {
    const v = byPath(c.src);
    const key = [i, bankSel.has(i), splitOn(), v, v?.name, c.src, c.in, c.out, c.thumb, c.note, outLen(c)];
    const previous = previousCache.get(c);
    if (previous && key.every((value, n) => value === previous.key[n])) {
      cache.set(c, previous);
      tray.appendChild(previous.node);
      return;
    }
    const d = document.createElement("div");
    d.className = "card bank" + (bankSel.has(i) ? " picked" : "");
    d.draggable = true;
    d.tabIndex = 0;
    const name = clipName(c);
    d.innerHTML = `<div class="pic">${c.thumb ? `<img alt="" src="${c.thumb}">` : ""}<span class="len num">${outLen(c).toFixed(1)}s</span><button class="pick" aria-label="Select this clip" aria-pressed="${bankSel.has(i)}" title="Select (Shift-click for a range)"><svg class="i"><use href="#c-check"/></svg></button></div>` +
      `<div class="cap"><b>${esc(c.note || name)}</b><small class="num">${fmt(c.in)} to ${fmt(c.out)}</small></div>` +
      `<div class="hovbar"><button class="act del use" data-act="top" aria-label="Add to the top lane" title="Add to the ${splitOn() ? "top lane" : "timeline"}"><svg class="i"><use href="#plus"/></svg></button>` +
      (splitOn() ? `<button class="act del use low" data-act="bottom" aria-label="Add to the bottom lane" title="Add to the bottom lane"><svg class="i"><use href="#plus"/></svg></button>` : "") + "</div>";
    d.ondragstart = e => {
      e.dataTransfer.setData(CLIP_MIME, JSON.stringify({src: c.src, in: c.in, out: c.out, note: c.note || "", thumb: c.thumb || ""}));
      e.dataTransfer.effectAllowed = "copy";
      dragPx = outLen(c) * stlPps;
    };
    d.ondragend = () => { dragPx = 0; clearSlots(); };
    d.onclick = e => { if (!e.target.closest(".hovbar")) pickBank(i, e); };
    d.querySelector('[data-act="top"]').onclick = () => { addToShort(c, "top"); restartPreviewAt(state.sel); };
    const low = d.querySelector('[data-act="bottom"]');
    if (low) low.onclick = () => { addToShort(c, "bottom"); };
    cache.set(c, {key, node: d});
    tray.appendChild(d);
  });
}

function numberRow(label, content) {
  const row = document.createElement("div");
  row.className = "drow";
  const name = document.createElement("span");
  name.textContent = label;
  row.append(name, content);
  return row;
}

function speedField(i) {
  const c = state.project.clips[i];
  const menu = document.createElement("select");
  menu.className = "menu";
  menu.setAttribute("aria-label", "Speed");
  for (const s of SPEEDS) menu.add(new Option(s === 1 ? "1x (normal)" : `${s}x`, s, false, speedOf(c) === s));
  menu.onchange = () => setClipField(i, {speed: Number(menu.value)});
  return numberRow("Speed", menu);
}

function volumeField(i) {
  const c = state.project.clips[i];
  return zoomSlider(i, "Volume", "volume", 0, MAX_VOLUME, 0.05, volumeOf(c), v => (v === 0 ? "Muted" : percent(v)));
}

function transitionFields(i) {
  const c = state.project.clips[i];
  const menu = document.createElement("select");
  menu.className = "menu";
  menu.setAttribute("aria-label", "Transition into this clip");
  menu.add(new Option("None (hard cut)", "none", false, transitionOf(c) === "none"));
  for (const [id, label] of TRANSITIONS) menu.add(new Option(label, id, false, transitionOf(c) === id));
  menu.onchange = () => setClipField(i, {transition: menu.value});
  const rows = [numberRow("Style", menu)];
  if (transitionOf(c) !== "none") rows.push(zoomSlider(i, "Duration", "tlen", 0.1, 1.5, 0.05, tlenOf(c), v => `${v.toFixed(2).replace(/0$/, "")}s`));
  return rows;
}

function fadeFields(i) {
  const c = state.project.clips[i];
  const secs = v => (v === 0 ? "Off" : `${v.toFixed(1)}s`);
  return [zoomSlider(i, "Fade in", "fadeIn", 0, 3, 0.1, c.fadeIn || 0, secs), zoomSlider(i, "Fade out", "fadeOut", 0, 3, 0.1, c.fadeOut || 0, secs)];
}

// A titled group of rows that folds away. Which ones are folded is remembered while the page is open.
const folded = new Set();
function section(title, rows, note = "") {
  const box = document.createElement("section");
  box.className = "dsec";
  const head = document.createElement("button");
  head.className = "dsec-h";
  head.textContent = title;
  if (note !== "") {
    const count = document.createElement("small");
    count.className = "dsec-note num";
    count.textContent = note;
    head.appendChild(count);
  }
  const body = document.createElement("div");
  body.className = "dsec-b";
  body.append(...rows);
  const sync = () => {
    head.setAttribute("aria-expanded", !folded.has(title));
    body.hidden = folded.has(title);
  };
  head.onclick = () => { folded.has(title) ? folded.delete(title) : folded.add(title); sync(); };
  sync();
  box.append(head, body);
  return box;
}

function renderDetails() {
  const panel = $("panelDetails");
  const sound = inShort() && state.audioSel ? audioOf().find(a => a.id === state.audioSel) : null;
  if (sound) return panel.replaceChildren(...audioDetails(sound));
  if (inShort() && chosen().length > 1) return panel.replaceChildren(...bulkDetails());
  const i = state.sel, c = inShort() ? state.project.clips[i] : null;
  if (!c) {
    panel.innerHTML = '<div class="empty tray-empty">Click a clip on the timeline to change its zoom, speed, sound and effects here.</div>';
    return;
  }
  const v = byPath(c.src), lane = laneOf(c);
  const head = document.createElement("div");
  head.className = "dhead";
  head.innerHTML = `<div class="pic">${c.thumb ? `<img alt="" src="${c.thumb}">` : ""}</div>` +
    `<div><b>${esc(clipName(c))}</b><small class="num">${splitOn() ? `${esc(laneNameOf(lane))}, ` : ""}${outLen(c).toFixed(1)}s, ${fmt(c.in)} to ${fmt(c.out)}</small></div>`;
  const remove = document.createElement("button");
  remove.className = "ico";
  remove.setAttribute("aria-label", "Remove clip from the timeline");
  remove.title = "Remove from the timeline";
  remove.innerHTML = '<svg class="i"><use href="#trash"/></svg>';
  remove.onclick = () => removeFromTimeline(i);
  head.appendChild(remove);
  const moved = document.createElement("button");
  moved.className = "mini";
  moved.textContent = "Reset caption position, size and look";
  moved.title = "Follow the previous caption again, or sit at the bottom if there is none";
  moved.onclick = () => styleCaption(i, {capX: null, capY: null, capScale: null, capRot: null, capLook: null, capHi: null}, `capreset:${i}`, false);
  const caption = lane === "top" ? [section("Caption", [captionField(i), ...lookRows(i), ...syncRows(i), ...(capMoved(c) || c.capScale != null || c.capRot != null || c.capLook || c.capHi ? [moved] : [])])] : [];
  panel.replaceChildren(head, ...caption,
    section("Framing", [...fitField(i), zoomField(i), reframeRow(i)]),
    section("Speed", [speedField(i)]),
    section(firstInLane(i) ? "Fade in from black" : "Transition in", transitionFields(i)),
    section("Sound and fades", [volumeField(i), ...fadeFields(i)]),
    ...(laneMates(i).length > 1 ? [section("Match", applyRows(i))] : []));
}

// Drag the caption in the preview to put it anywhere in the frame. The point is saved on the clip it belongs to.
const capEl = $("cCap");
let capDrag = null;
// A caption's position, size, turn and look belong to the clip the caption starts on, so it looks the same on every clip it covers.
// Changing them from a clip it carries over to goes to the first clip, and the later clips drop their own values for it.
function captionRunOf(i) {
  const clips = state.project.clips, c = clips[i], fallback = {head: i, last: i};
  if (!c || !isTop(c)) return fallback;
  let head = i, first = c;
  if (!c.caption) {
    if (c.capStop) return fallback;
    head = -1;
    for (let n = i - 1; n >= 0; n--) {
      const previous = clips[n];
      if (!isTop(previous)) continue;
      if (previous.caption) {
        if (isSynced(previous)) return fallback;
        head = n; first = previous; break;
      }
      if (previous.capStop) return fallback;
    }
    if (head < 0) return fallback;
  }
  let last = i;
  if (!isSynced(first)) for (let n = i + 1; n < clips.length; n++) {
    const next = clips[n];
    if (!isTop(next)) continue;
    if (next.caption || next.capStop) break;
    last = n;
  }
  return {head, last, text: first.caption};
}

const firstCaption = () => state.project.clips.findIndex(c => isTop(c) && c.caption);
const capsApart = () => {
  const head = firstCaption();
  return head >= 0 && state.project.clips.some((c, n) => n !== head && isTop(c) && capMoved(c));
};
function captionsToFirstPosition() {
  const head = firstCaption();
  if (head < 0) return;
  state.project = {...state.project, clips: state.project.clips.map((c, n) => (n !== head && isTop(c) ? {...c, capX: null, capY: null} : c))};
  changed(false);
  toast("Every caption follows the first one's position");
}
function styleCaption(i, patch, key, keepDom = true, own = {}) {
  const {head, last} = captionRunOf(i), unset = Object.fromEntries(Object.keys(patch).map(k => [k, null]));
  state.project = {...state.project, clips: state.project.clips.map((c, n) => {
    const mine = n === i ? own : null;
    if (n === head) return {...c, ...patch, ...mine};
    if (n > head && n <= last && isTop(c)) return {...c, ...unset, ...mine};
    return mine ? {...c, ...mine} : c;
  })};
  changed(keepDom, key);
}
function setCaptionPoint(i, x, y) { styleCaption(i, {capX: x, capY: y}, `cappos:${i}`); }
capEl.addEventListener("pointerdown", e => {
  if (!inShort() || !capEl.textContent || !state.project.clips[preview.idx]) return;
  e.preventDefault();
  capEl.setPointerCapture(e.pointerId);
  capDrag = {i: preview.idx};
  capEl.classList.add("dragging");
});
capEl.addEventListener("pointermove", e => {
  if (!capDrag) return;
  const r = $("card1080").getBoundingClientRect();
  const snap = (v, to) => (Math.abs(v - to) < 0.03 ? to : v);
  const x = snap(Math.min(0.95, Math.max(0.05, (e.clientX - r.left) / r.width)), 0.5);
  const y = Math.min(0.98, Math.max(0.02, (e.clientY - r.top) / r.height));
  setCaptionPoint(capDrag.i, Number(x.toFixed(4)), Number(y.toFixed(4)));
  placeCaption(state.project.clips[capDrag.i]);
});
// Corner handles resize the caption, the round handle turns it. Each sets the clip's own value and later captions follow.
const capSel = $("capSel");
let capGesture = null;
// True while the pointer is on the caption or its frame, handles and readout (70 screen px reaches all of them), so only one frame shows: the caption's or the clip's.
function overCaption(e) {
  if (capSel.hidden) return false;
  const r = capSel.getBoundingClientRect(), m = 70;
  return e.clientX >= r.left - m && e.clientX <= r.right + m && e.clientY >= r.top - m && e.clientY <= r.bottom + m;
}
$("card1080").addEventListener("pointermove", e => capSel.classList.toggle("near", overCaption(e)));
$("card1080").addEventListener("pointerleave", () => capSel.classList.remove("near"));
function setCaptionStyle(i, patch, key) {
  styleCaption(i, patch, key);
  placeCaption(state.project.clips[i]);
}
function pivotOnScreen() {
  const card = $("card1080").getBoundingClientRect(), k = card.width / canvasOf()[0];
  const down = capSel.style.transformOrigin.startsWith("50% 100%");
  return {x: card.left + (capSel.offsetLeft + capSel.offsetWidth / 2) * k, y: card.top + (capSel.offsetTop + capSel.offsetHeight * (down ? 1 : 0.5)) * k};
}
function startGesture(e, kind) {
  const i = preview.idx, clip = state.project.clips[i];
  if (!inShort() || !clip) return;
  e.preventDefault();
  e.stopPropagation();
  const pivot = pivotOnScreen(), st = capStyleOf(clip);
  capGesture = {kind, i, pivot, dist: Math.hypot(e.clientX - pivot.x, e.clientY - pivot.y) || 1, scale: st.scale};
  e.currentTarget.setPointerCapture(e.pointerId);
  capSel.classList.add("active");
}
function moveGesture(e) {
  if (!capGesture) return;
  const {kind, i, pivot} = capGesture;
  if (kind === "scale") {
    const raw = capGesture.scale * Math.hypot(e.clientX - pivot.x, e.clientY - pivot.y) / capGesture.dist;
    const scale = Math.abs(raw - 1) < 0.04 ? 1 : Math.min(3, Math.max(0.3, raw));
    setCaptionStyle(i, {capScale: Number(scale.toFixed(2))}, `capscale:${i}`);
  } else {
    let deg = Math.atan2(e.clientY - pivot.y, e.clientX - pivot.x) * 180 / Math.PI + 90;
    deg = ((deg + 540) % 360) - 180;
    const snapped = [0, 45, 90, -45, -90, 180, -180].find(s => Math.abs(deg - s) < 3);
    setCaptionStyle(i, {capRot: Math.round(snapped !== undefined ? snapped : deg)}, `caprot:${i}`);
  }
}
const endGesture = () => {
  if (!capGesture) return;
  capGesture = null;
  capSel.classList.remove("active");
  render();
};
capSel.querySelectorAll(".ch").forEach(h => { h.onpointerdown = e => startGesture(e, "scale"); });
$("capRot").onpointerdown = e => startGesture(e, "rotate");
capSel.addEventListener("pointermove", moveGesture);
capSel.addEventListener("pointerup", endGesture);
capSel.addEventListener("pointercancel", endGesture);
new ResizeObserver(() => syncCapSel()).observe(capEl);

const endCapDrag = () => {
  if (!capDrag) return;
  capDrag = null;
  capEl.classList.remove("dragging");
  render();
};
capEl.addEventListener("pointerup", endCapDrag);
capEl.addEventListener("pointercancel", endCapDrag);

function fitPhone() {
  if (!inShort() || $("theater").hidden) return;
  const host = $("theater"), [W, H] = canvasOf();
  // 64px above for the project and switch; below, 14px, the size and layout bar (37px), and 14px more.
  const room = {w: host.clientWidth - 48, h: Math.min(820, host.clientHeight - (64 + 14 + 37 + 14))};
  if (room.w < 80 || room.h < 80) return;
  const scale = Math.min(room.w / W, room.h / H);
  Object.assign(phoneEl.style, {width: `${Math.floor(W * scale)}px`, height: `${Math.floor(H * scale)}px`, flex: "none"});
}

function showShortPreview() {
  preview.on = true;
  $("theater").hidden = false;
  layoutCard();
  buildSegs();
  fitPhone();
  if (nextTop(-1) < state.project.clips.length) startPreviewAt(nextTop(-1));
}

// The preview plays from its own pair of players, so the source monitor keeps the video you were working on.
const previewVideos = [makeSpareVideo(), makeSpareVideo()];
watchPlayers(previewVideos);
let monitorPlayers = null;
function usePreviewPlayers(on) {
  if (on && !monitorPlayers) {
    monitorPlayers = {videos, video};
    monitorPlayers.videos.forEach(el => el.pause());
    videos = previewVideos;
    video = previewVideos[0];
    previewVideos[0].classList.remove("off");
    previewVideos[1].classList.add("off");
    previewVideos.forEach(el => { el.muted = previewMuted; });
  } else if (!on && monitorPlayers) {
    for (const el of previewVideos) {
      el.pause();
      el.removeAttribute("src");
      el.dataset.id = "";
      el.dataset.base = "0";
      el.dataset.pre = "";
      el.classList.add("off");
    }
    videos = monitorPlayers.videos;
    video = monitorPlayers.video;
    monitorPlayers = null;
  }
}

function warmCuts() {
  for (const c of [...state.project.clips, ...(state.project.other || [])]) requestCut(c);
}

function setMode(mode) {
  if (mode === state.mode) return;
  if (streaming()) leaveLive();
  if (preview.on) closePreview();
  if (mode === "clip") usePreviewPlayers(false);
  const next = orient(canon(), mode);
  clearBankSel();
  state.mode = mode;
  state.project = next;
  state.sel = next.clips.length ? 0 : -1;
  resetHistory();
  document.body.dataset.mode = mode;
  setSideTab(mode === "short" ? "fx" : "media");
  setTab(mode === "short" && state.sel >= 0 ? "details" : "clip");
  render();
  if (mode === "short") {
    usePreviewPlayers(true);
    warmCuts();
    showShortPreview();
  }
}

function renderShortMode() {
  const short = inShort();
  document.body.dataset.mode = state.mode;
  $("modeClip").setAttribute("aria-selected", !short);
  $("modeShort").setAttribute("aria-selected", short);
  $("shortTl").hidden = !short;
  if (typeof railSync === "function") railSync(short);
  $(short ? "histShort" : "histClip").append($("undoBtn"), $("redoBtn"));
  document.querySelector(".timeline:not(.shorttl)").hidden = short;
  $("tabClip").textContent = short ? "Clip bank" : "Clips";
  $("tabDetails").hidden = !short;
  $("tabAudio").hidden = !short;
  $("tabShort").hidden = !short;
  if (!short) {
    if (currentTab === "details" || currentTab === "short") setTab("clip");
    return;
  }
  renderShortTl();
  if (preview.on) { buildSegs(); fitPhone(); }
}

$("modeClip").onclick = () => setMode("clip");
$("modeShort").onclick = () => setMode("short");
$("tabDetails").onclick = () => setTab("details");
document.querySelectorAll("#formatSeg button").forEach(b => {
  b.onclick = () => { state.project = {...state.project, format: b.dataset.format}; changed(); };
});
document.querySelectorAll("#templateSeg button").forEach(b => {
  b.onclick = () => {
    state.project = {...state.project, template: b.dataset.template};
    changed();
    if (preview.on) startPreviewAt(nextTop(-1));
  };
});
new ResizeObserver(fitPhone).observe($("theater"));
new ResizeObserver(() => { if (inShort()) renderShortTl(); }).observe(stlBody);

// Mutes only what you hear while previewing. The clips' own sound levels are untouched and still render.
function setPreviewMuted(muted) {
  previewMuted = muted;
  const b = $("thMute");
  b.setAttribute("aria-pressed", previewMuted);
  b.setAttribute("aria-label", previewMuted ? "Turn the preview sound on" : "Mute preview");
  b.title = previewMuted ? "Muted. Click for sound" : "Mute the preview";
  b.querySelector("use").setAttribute("href", previewMuted ? "#mute" : "#vol");
  const own = state.project.clips[preview.idx];
  const silent = own ? playVolume(own) === 0 : false;
  for (const el of [...videos, ...laneVids]) el.muted = previewMuted || (!laneVids.includes(el) && silent);
}
$("thMute").onclick = () => setPreviewMuted(!previewMuted);

