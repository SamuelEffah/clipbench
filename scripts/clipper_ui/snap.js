// Snapping, markers and the keys for moving around the Short. Depends on short.js, selection.js, zoom.js, audio.js.
let snapOn = true;
let snapLine = null;
const SNAP_REACH_PX = 8;

const markersOf = () => state.project.markers || [];

// Every time a drag can land on: the start, the 60s limit, the playhead, markers, and the edges of clips and sounds.
function snapTargets({skipClips = new Set(), skipAudio = "", noHead = false, starts = clipStarts(state.project.clips)} = {}) {
  const clips = state.project.clips;
  const times = [0, SHORT_LIMIT, ...markersOf()];
  if (!noHead) times.push(preview.elapsed || 0);
  clips.forEach((c, i) => { if (!skipClips.has(i)) times.push(starts[i], starts[i] + outLen(c)); });
  audioOf().forEach(a => { if (a.id !== skipAudio) times.push(a.start, a.start + a.dur); });
  return times;
}

// The nearest target to any of `times`, within a few pixels: how far to shift, and where it lands. Alt turns snapping off for the drag.
function snapNear(times, options = {}, bypass = false) {
  if (!snapOn || bypass || !stlPps) return null;
  const reach = SNAP_REACH_PX / stlPps, targets = snapTargets(options);
  let best = null;
  for (const t of times) for (const g of targets) {
    const d = g - t;
    if (Math.abs(d) <= reach && (!best || Math.abs(d) < Math.abs(best.delta))) best = {delta: d, at: g};
  }
  return best;
}

function showSnapLine(at) {
  const track = timeTrack(stlBody);
  if (!track) return;
  if (!snapLine || !snapLine.isConnected) { snapLine = Object.assign(document.createElement("i"), {className: "stl-snapline"}); stlBody.append(snapLine); }
  snapLine.style.left = `${track.offsetLeft + at * stlPps}px`;
}

function hideSnapLine() {
  if (snapLine) snapLine.remove();
  snapLine = null;
}

const laterInLane = (gi, from = gi) => {
  const clips = state.project.clips, skip = new Set(), start = Math.max(0, Math.ceil(from)), end = clips.length;
  if (Number.isNaN(start) || start >= end) return skip;
  const lane = laneOf(clips[gi]);
  for (let i = start; i < end; i++) {
    if (i in clips && laneOf(clips[i]) === lane) skip.add(i);
  }
  return skip;
};

// Trimming: the end that moves is pulled onto a nearby edge. Skipped for clips with a speed ramp or hold, whose length is not a plain stretch.
function snapTrim(next, c0, gi, side, v, bypass) {
  if (rampOf(c0) !== "none" || freezeOf(c0) > 0) return next;
  if (!snapOn || bypass || !stlPps) { hideSnapLine(); return next; }
  const starts = clipStarts(state.project.clips), end = starts[gi] + outLen(next);
  const hit = snapNear([end], {skipClips: laterInLane(gi), starts}, bypass);
  if (!hit) { hideSnapLine(); return next; }
  const speed = speedOf(c0), delta = hit.delta * speed;
  const fixed = side === "l" ? {...next, in: Math.min(Math.max(0, next.in - delta), next.out - MIN_CLIP)}
    : {...next, out: Math.max(Math.min(v ? v.duration : Infinity, next.out + delta), next.in + MIN_CLIP)};
  showSnapLine(hit.at);
  return fixed;
}

// Scrubbing the playhead snaps to clip edges and markers.
function snapScrubTime(t, e) {
  const hit = snapNear([t], {noHead: true}, e.altKey);
  if (!hit) { hideSnapLine(); return t; }
  showSnapLine(hit.at);
  return hit.at;
}

// ----- Markers -----

function setMarkers(list) {
  state.project = {...state.project, markers: [...new Set(list.map(t => Number(Math.max(0, t).toFixed(2))))].sort((a, b) => a - b)};
  changed();
}

function addMarker() {
  const t = preview.elapsed || 0;
  if (markersOf().some(m => Math.abs(m - t) < 0.05)) return toast("There is a marker here already");
  setMarkers([...markersOf(), t]);
  toast(`Marker at ${t.toFixed(1)}s`);
}

function paintMarkers(ruler, span) {
  markersOf().forEach((t, n) => {
    const flag = document.createElement("button");
    flag.className = "rmark";
    flag.style.left = `${(t / span * 100).toFixed(3)}%`;
    flag.title = `Marker at ${t.toFixed(1)}s. Click to jump, drag to move, double-click to remove`;
    flag.setAttribute("aria-label", `Marker at ${t.toFixed(1)} seconds`);
    flag.onpointerdown = e => dragMarker(e, flag, n, span);
    flag.ondblclick = e => { e.stopPropagation(); setMarkers(markersOf().filter((_, i) => i !== n)); };
    ruler.append(flag);
  });
}

function dragMarker(e, flag, n, span) {
  e.preventDefault();
  e.stopPropagation();
  const track = timeTrack(stlBody), original = markersOf()[n];
  let t = original, moved = false;
  flag.setPointerCapture(e.pointerId);
  const move = ev => {
    if (Math.abs(ev.clientX - e.clientX) > 3) moved = true;
    if (!moved) return;
    t = Math.min(span, Math.max(0, (ev.clientX - track.getBoundingClientRect().left) / stlPps));
    const hit = snapNear([t], {noHead: true}, ev.altKey);
    t = hit ? hit.at : Math.round(t * 20) / 20;
    flag.style.left = `${(t / span * 100).toFixed(3)}%`;
    if (hit) showSnapLine(hit.at); else hideSnapLine();
  };
  const up = () => {
    flag.removeEventListener("pointermove", move);
    flag.removeEventListener("pointerup", up);
    flag.removeEventListener("pointercancel", up);
    hideSnapLine();
    if (!moved) return seekShort(original);
    setMarkers(markersOf().map((m, i) => (i === n ? t : m)));
  };
  flag.addEventListener("pointermove", move);
  flag.addEventListener("pointerup", up);
  flag.addEventListener("pointercancel", up);
}

// ----- Moving around -----

const shortEnd = () => Math.max(0, laneTotal("top", state.project.clips) - 0.05);

// Where the playhead can jump to: the start and end of each top lane clip, and the markers.
function cutPoints() {
  const clips = state.project.clips, starts = clipStarts(clips), pts = [...markersOf()];
  clips.forEach((c, i) => { if (isTop(c)) pts.push(starts[i], starts[i] + outLen(c)); });
  return [...new Set(pts.map(t => Number(t.toFixed(3))))].sort((a, b) => a - b);
}

function jumpCut(dir) {
  const now = preview.elapsed || 0, pts = cutPoints();
  const to = dir < 0 ? [...pts].reverse().find(t => t < now - 0.05) : pts.find(t => t > now + 0.05);
  seekShort(Math.min(to ?? (dir < 0 ? 0 : shortEnd()), shortEnd()));
}

function toggleSnap() {
  snapOn = !snapOn;
  toast(snapOn ? "Snapping on" : "Snapping off");
}

document.addEventListener("keydown", e => {
  if (!inShort() || typing(e) || document.querySelector("dialog[open]") || e.metaKey || e.ctrlKey || e.altKey) return;
  const now = preview.elapsed || 0, key = e.shiftKey && /^[a-z]$/.test(e.key) ? e.key.toUpperCase() : e.key;
  if (shuttleActive() && key !== "j" && key !== "l") stopShuttle();
  const run = {
    j: () => shuttleKey(-1), l: () => shuttleKey(1), k: shuttleStop,
    J: () => seekShort(Math.max(0, now - 2)), L: () => seekShort(Math.min(shortEnd(), now + 2)),
    Home: () => seekShort(0), End: () => seekShort(shortEnd()), "[": () => jumpCut(-1), "]": () => jumpCut(1),
    "=": () => setZoom(tlZoom * 1.5), "+": () => setZoom(tlZoom * 1.5), "-": () => setZoom(tlZoom / 1.5),
    "0": fitAll, "\\": fitSelection, n: toggleSnap,
  };
  const act = key === "M" ? addMarker : run[key] || (key.length === 1 ? run[key.toLowerCase()] : null);
  if (!act) return;
  e.preventDefault();
  e.stopImmediatePropagation();
  act();
}, true);

// A sound block being moved or trimmed lands on nearby edges.
function snapSound(a, mode, patch, bypass) {
  const opts = {skipAudio: a.id};
  const start = patch.start ?? a.start, dur = patch.dur ?? a.dur;
  const hit = snapNear(mode === "move" ? [start, start + dur] : mode === "right" ? [start + dur] : [start], opts, bypass);
  if (!hit) { hideSnapLine(); return patch; }
  showSnapLine(hit.at);
  const d = hit.delta;
  if (mode === "move") return {...patch, start: Math.max(0, Number((start + d).toFixed(2)))};
  if (mode === "right") return {...patch, dur: Math.min(a.total - a.in, Math.max(MIN_SOUND, Number((dur + d).toFixed(2))))};
  const room = Math.min(a.dur - MIN_SOUND, Math.max(-Math.min(a.in, a.start), d));
  return {start: Number((a.start + room).toFixed(2)), in: Number((a.in + room).toFixed(2)), dur: Number((a.dur - room).toFixed(2))};
}
