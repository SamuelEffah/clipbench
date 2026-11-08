// AI reframe: find the face in a clip and set its crop so the face sits in frame.
// Depends on app.js (state, changed, api, toast, fitOf, zoomOf, laneOf, laneBoxes, laneCount, splitOn, mirror, LANES) and selection.js (picked).
const REFRAME = {faceShare: 0.36, faceY: 0.42, maxZoom: 3, minZoom: 1.05};
const reframeBusy = new Set();
const clamp01 = v => Math.min(1, Math.max(0, v));

// The size in pixels of the picture this clip is drawn into: its lane when the layout has lanes, otherwise the whole frame.
function cellOf(clip) {
  const k = splitOn() ? laneCount() : 1;
  const [, , bw, bh] = laneBoxes(k)[Math.min(k - 1, Math.max(0, LANES.indexOf(laneOf(clip))))];
  const [cw, ch] = canvasOf();
  return [cw * bw, ch * bh];
}

// How a clip's picture sits in its cell, as paintClip draws it before any zoom: the picture's size and where it starts.
function pictureIn(clip, size, cell, pan) {
  const [vw, vh] = size, [W, H] = cell, fill = fitOf(clip) === "fill";
  const r = (fill ? Math.max : Math.min)(W / vw, H / vh);
  const w = vw * r, h = vh * r;
  return {W, H, w, h, fill, x: fill ? (W - w) * pan : (W - w) / 2, y: fill ? (H - h) * pan : (H - h) / 2};
}

// Where to point a zoomed crop (zx, zy) so the face lands at the middle of the cell, a little above centre.
function focusOn(pic, zoom, face) {
  const fx = pic.x + face.x * pic.w, fy = pic.y + face.y * pic.h;
  return [clamp01((fx - pic.W / (2 * zoom)) / (pic.W - pic.W / zoom)), clamp01((fy - (REFRAME.faceY * pic.H) / zoom) / (pic.H - pic.H / zoom))];
}

// The framing fields that put a face (fractions of the source frame) in view of a clip, mirroring how paintClip draws it.
// With a track (smoothed face positions over time) it also returns the keyframes that follow the face at that zoom.
function reframeFor(clip, face, size, cell, track = []) {
  const flat = pictureIn(clip, size, cell, 0.5);
  const seen = Math.max((face.w * flat.w) / flat.W, (face.h * flat.h) / flat.H);
  const raw = REFRAME.faceShare / seen;
  const zoom = raw < REFRAME.minZoom ? 1 : Number(Math.min(REFRAME.maxZoom, raw).toFixed(2));
  const pan = flat.fill ? clamp01(Math.abs(flat.W - flat.w) >= Math.abs(flat.H - flat.h) ? (flat.W / 2 - face.x * flat.w) / (flat.W - flat.w || 1) : (flat.H / 2 - face.y * flat.h) / (flat.H - flat.h || 1)) : 0.5;
  const out = {pan: Number(pan.toFixed(3)), zoom, zx: 0.5, zy: 0.5, track: []};
  if (zoom === 1) return out;
  const pic = pictureIn(clip, size, cell, pan);
  [out.zx, out.zy] = focusOn(pic, zoom, face).map(v => Number(v.toFixed(3)));
  out.track = track.map(s => [s.t, ...focusOn(pic, zoom, s).map(v => Number(v.toFixed(3)))]);
  return out;
}

async function reframeOne(i, speaker = false) {
  const clip = state.project.clips[i];
  const found = await api(speaker ? "/api/speaker" : "/api/reframe", "POST", {src: clip.src, in: clip.in, out: clip.out});
  if (!found.found) return null;
  return reframeFor(clip, found.face, [found.width, found.height], cellOf(clip), found.track);
}

// Reframe these clips on their faces as one undo step. Clips with no face are left alone.
async function reframeClips(indices, tracking, speaker = false) {
  const todo = indices.filter(i => !reframeBusy.has(i));
  if (!todo.length) return;
  todo.forEach(i => reframeBusy.add(i));
  toast(speaker ? "Finding who is talking" : todo.length > 1 ? `Finding faces in ${todo.length} clips` : "Finding the face");
  const patches = new Map();
  const failed = [];
  for (const i of todo) {
    try {
      const patch = await reframeOne(i, speaker);
      if (patch) patches.set(i, tracking === undefined ? patch : {...patch, tracking: tracking && patch.track.length > 1});
    } catch (err) {
      failed.push(err.message);
    }
  }
  todo.forEach(i => reframeBusy.delete(i));
  if (patches.size) {
    state.project = {...state.project, clips: state.project.clips.map((c, n) => (patches.has(n) ? {...c, ...patches.get(n)} : c))};
    changed(false, `reframe:${Date.now()}`);
  }
  const flat = [...patches.values()].filter(p => tracking && !p.tracking).length;
  const missed = todo.length - patches.size - failed.length;
  if (failed.length) toast(failed[0]);
  else if (!patches.size) toast(speaker ? "Could not tell who is talking in this clip" : todo.length > 1 ? "No face found in those clips" : "No face found in this clip");
  else if (flat) toast(flat === patches.size ? "The face already fills the frame, so there is nothing to track" : `Tracking ${patches.size - flat}, the face fills the frame in ${flat}`);
  else toast(missed ? `Reframed ${patches.size}, no speaker in ${missed}` : patches.size > 1 ? `Reframed ${patches.size} clips` : speaker ? "Following the speaker" : "Reframed on the face");
}

// Reframing from clip i takes the whole selection along when clip i is part of it.
const reframeTargets = i => (picked.has(i) && picked.size > 1 ? [...picked].sort((a, b) => a - b) : [i]);

const hasTrack = c => Boolean(c && c.track && c.track.length > 1);
const trackingOn = c => Boolean(c && c.tracking && hasTrack(c));

function setTracking(ids, on) {
  const selected = new Set(ids);
  state.project = {...state.project, clips: state.project.clips.map((c, n) => (selected.has(n) ? {...c, tracking: on} : c))};
  changed(false, `tracking:${Date.now()}`);
  toast(on ? "Tracking on" : "Tracking off");
}

// Switch the crop between following the face and staying put. A clip that has never been tracked is analysed first.
function toggleTracking(i) {
  const ids = reframeTargets(i), clips = state.project.clips, on = !trackingOn(clips[i]);
  if (!on) return setTracking(ids, false);
  const ready = ids.filter(n => hasTrack(clips[n])), need = ids.filter(n => !hasTrack(clips[n]));
  if (ready.length) setTracking(ready, true);
  if (need.length) reframeClips(need, true);
}

// The crop centre (zx, zy) of a clip that follows its face, at a source time. Null when the clip is not tracked.
function trackedFocus(clip, t) {
  if (!trackingOn(clip)) return null;
  const keys = clip.track;
  if (t <= keys[0][0]) return [keys[0][1], keys[0][2]];
  // Tracks arrive sorted by time. Find the first key at or after t, including
  // the first of any duplicate timestamps, just as the forward scan did.
  let lo = 1, hi = keys.length;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    if (t <= keys[mid][0]) hi = mid;
    else lo = mid + 1;
  }
  if (lo < keys.length) {
    const [t0, x0, y0] = keys[lo - 1], [t1, x1, y1] = keys[lo], f = t1 > t0 ? (t - t0) / (t1 - t0) : 1;
    return [x0 + (x1 - x0) * f, y0 + (y1 - y0) * f];
  }
  const last = keys[keys.length - 1];
  return [last[1], last[2]];
}

function reframeRow(i) {
  const box = document.createElement("div");
  box.className = "reframe-row";
  const btn = document.createElement("button");
  btn.className = "mini";
  btn.textContent = picked.has(i) && picked.size > 1 ? `Reframe ${picked.size} clips on the face` : "Reframe on the face";
  btn.title = "Find the face in this clip and crop to it";
  btn.onclick = () => reframeClips(reframeTargets(i), trackingOn(state.project.clips[i]) ? true : undefined);
  const follow = document.createElement("label");
  follow.className = "mini-check";
  follow.title = "Move the crop with the face instead of holding one position";
  const check = Object.assign(document.createElement("input"), {type: "checkbox", checked: trackingOn(state.project.clips[i])});
  check.onchange = () => toggleTracking(i);
  follow.append(check, " Track the face");
  const talker = document.createElement("button");
  talker.className = "mini";
  talker.textContent = picked.has(i) && picked.size > 1 ? `Follow the speaker in ${picked.size} clips` : "Follow the speaker";
  talker.title = "Keep the crop on whoever is talking, and move to the next person when they take over";
  talker.onclick = () => reframeClips(reframeTargets(i), true, true);
  box.append(btn, follow, talker);
  return box;
}
