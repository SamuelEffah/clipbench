// Reframe dialog: a still of the clip, a box drawn on it, and Apply sets the clip's crop to that box.
// Depends on app.js (state, changed, toast, byPath, fitOf, zoomOf, render) and reframe.js (cellOf, reframeOne, clamp01).
const BOX_MIN = 0.06;

// What a fill crop shows before any zoom, as fractions of the source frame: one side is always the whole frame.
function viewOf(size, cell) {
  const [vw, vh] = size, [W, H] = cell, r = Math.max(W / vw, H / vh);
  return {fw: Math.min(1, W / (vw * r)), fh: Math.min(1, H / (vh * r))};
}

// The box (x, y, w, h as fractions of the frame) a clip's framing fields currently show.
function boxFromFields(clip, size, cell) {
  const {fw, fh} = viewOf(size, cell), z = Math.max(1, zoomOf(clip)), pan = clip.pan === undefined ? 0.5 : clip.pan;
  const zx = clip.zx === undefined ? 0.5 : clip.zx, zy = clip.zy === undefined ? 0.5 : clip.zy;
  const w = fw / z, h = fh / z;
  return {x: pan * (1 - fw) + (fw - w) * zx, y: pan * (1 - fh) + (fh - h) * zy, w, h};
}

// The framing fields that make a fill crop show this box, the inverse of boxFromFields.
function fieldsFromBox(box, size, cell) {
  const {fw, fh} = viewOf(size, cell), z = fw / box.w;
  const x0 = Math.min(1 - fw, Math.max(0, box.x + box.w / 2 - fw / 2)), y0 = Math.min(1 - fh, Math.max(0, box.y + box.h / 2 - fh / 2));
  const room = Math.max(1 - fw, 1 - fh), pan = room < 1e-6 ? 0.5 : (1 - fw >= 1 - fh ? x0 / (1 - fw) : y0 / (1 - fh));
  const along = (pos, start, full, part) => (full - part < 1e-6 ? 0.5 : clamp01((pos - start) / (full - part)));
  const r3 = v => Number(v.toFixed(3));
  return {fit: "fill", pan: r3(clamp01(pan)), zoom: z < 1.02 ? 1 : Number(z.toFixed(2)), zx: r3(along(box.x, x0, fw, box.w)), zy: r3(along(box.y, y0, fh, box.h)), tracking: false};
}

// Where the crop centre goes over time so the subject stays where it sat in the box: one (t, zx, zy) per sample.
function followKeys(box, samples, size, cell, fields) {
  const {fw, fh} = viewOf(size, cell), x0 = fields.pan * (1 - fw), y0 = fields.pan * (1 - fh);
  const cx = box.x + box.w / 2, cy = box.y + box.h / 2, r3 = v => Number(v.toFixed(3));
  const along = (pos, start, full, part) => (full - part < 1e-6 ? 0.5 : clamp01((pos - start) / (full - part)));
  return samples.map(s => {
    const bx = Math.min(1 - box.w, Math.max(0, box.x + s.x - cx)), by = Math.min(1 - box.h, Math.max(0, box.y + s.y - cy));
    return [s.t, r3(along(bx, x0, fw, box.w)), r3(along(by, y0, fh, box.h))];
  });
}

// Grow or move a box with a fixed shape: the corner (ax, ay) stays put, the pointer (px, py) pulls the opposite one.
function boxFrom(ax, ay, px, py, shape, max) {
  const sx = px >= ax ? 1 : -1, sy = py >= ay ? 1 : -1;
  const room = Math.min(sx > 0 ? 1 - ax : ax, (sy > 0 ? 1 - ay : ay) / shape, max);
  const w = Math.min(room, Math.max(BOX_MIN, Math.abs(px - ax), Math.abs(py - ay) / shape));
  const h = w * shape;
  return {x: sx > 0 ? ax : ax - w, y: sy > 0 ? ay : ay - h, w, h};
}

const reframeUi = (() => {
  const dlg = document.createElement("dialog");
  dlg.id = "reframeDlg";
  dlg.innerHTML = '<header class="rdhead"><h3 id="rfTitle">Reframe</h3><button type="button" class="rdx" id="rfX" aria-label="Close"><svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M2 2l10 10M12 2L2 12"/></svg></button></header>' +
    '<div id="rfFrame"><div id="rfStage"><video id="rfVideo" muted playsinline preload="auto"></video><div id="rfBox" hidden>' + ["nw", "ne", "sw", "se"].map(h => `<i class="fh ${h}" data-h="${h}"></i>`).join("") + '</div></div></div>' +
    '<div class="rfscrub"><input type="range" id="rfScrub" min="0" max="1" step="0.001" value="0" aria-label="Frame of the clip"><span class="num" id="rfTime"></span>' +
    '<span class="rfzoom"><button type="button" id="rfZoomOut" aria-label="Zoom out">&minus;</button><button type="button" id="rfZoomPct" aria-label="Fit the whole frame" title="Fit the whole frame">100%</button><button type="button" id="rfZoomIn" aria-label="Zoom in">+</button></span></div><p class="hint" id="rfHint"></p>' +
    '<div class="btnrow rffoot"><button type="button" id="rfFace">Find face</button><span class="grow"></span><button type="button" id="rfStop" hidden>Stop tracking</button><button type="button" id="rfReset">Reset</button><button type="button" id="rfApply" class="rfapply">Apply</button></div>';
  document.body.append(dlg);
  return dlg;
})();

let rf = null;

const RF_ZOOM_MAX = 6;

// The picture can be magnified while drawing, to place a box on something small. view.x and view.y are the stage's
// offset inside its frame in pixels; both stay at or below 0 so the picture always covers the frame.
function paintView() {
  const stage = document.getElementById("rfStage"), frame = document.getElementById("rfFrame"), v = rf.view;
  v.x = Math.min(0, Math.max(frame.clientWidth - stage.offsetWidth * v.z, v.x));
  v.y = Math.min(0, Math.max(frame.clientHeight - stage.offsetHeight * v.z, v.y));
  stage.style.transform = v.z === 1 ? "" : `translate(${v.x}px, ${v.y}px) scale(${v.z})`;
  stage.style.setProperty("--zs", String(1 / v.z));
  frame.classList.toggle("zoomed", v.z > 1);
  document.getElementById("rfZoomPct").textContent = `${Math.round(v.z * 100)}%`;
}

// Change the magnification, keeping the point (cx, cy) in the frame, in pixels, under the pointer.
function zoomTo(z, cx, cy) {
  const v = rf.view, next = Math.min(RF_ZOOM_MAX, Math.max(1, z));
  const px = (cx - v.x) / v.z, py = (cy - v.y) / v.z;
  rf.view = {z: next, x: cx - px * next, y: cy - py * next};
  paintView();
}

function zoomBy(factor, e) {
  if (!rf || !rf.size) return;
  const frame = document.getElementById("rfFrame"), r = frame.getBoundingClientRect();
  zoomTo(rf.view.z * factor, e ? e.clientX - r.left : r.width / 2, e ? e.clientY - r.top : r.height / 2);
}

function paintBox() {
  const el = document.getElementById("rfBox"), b = rf.box;
  el.hidden = !b;
  if (b) Object.assign(el.style, {left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%`});
  document.getElementById("rfApply").disabled = !b;
}

function openReframe(i, mode = "frame") {
  const clip = state.project.clips[i], v = clip && byPath(clip.src);
  if (!v) return toast("This clip's video is not loaded");
  const vid = document.getElementById("rfVideo");
  const follow = mode === "track";
  rf = {i, mode, cell: cellOf(clip), size: null, box: null, gesture: null, start: clip, view: {z: 1, x: 0, y: 0}, space: false, at: follow ? clip.in : clip.in + (clip.out - clip.in) / 2};
  document.getElementById("rfTitle").textContent = `${follow ? "Tracking" : "Reframe"} clip ${i + 1}`;
  document.getElementById("rfHint").textContent = "Drag inside to move · Corners to resize · Drag outside to redraw";
  document.getElementById("rfHint").title = "Click outside the crop to center it there. The crop ratio stays locked. Pinch or Ctrl-scroll to magnify; hold Space and drag to pan.";
  document.getElementById("rfApply").textContent = follow ? "Track" : "Apply";
  document.getElementById("rfStop").hidden = !(follow && trackingOn(clip));
  const ready = () => {
    rf.size = [vid.videoWidth, vid.videoHeight];
    document.getElementById("rfStage").style.aspectRatio = `${vid.videoWidth} / ${vid.videoHeight}`;
    paintView();
    seekStill(follow ? 0 : 0.5);
    resetBox(true);
  };
  vid.onloadedmetadata = ready;
  vid.src = `/media/${v.id}`;
  if (vid.readyState >= 1) ready();
  paintBox();
  reframeUi.showModal();
}

// Show the frame a fraction of the way through the clip, and remember its time as where the box was drawn.
function seekStill(f) {
  const clip = state.project.clips[rf.i];
  rf.at = Number((clip.in + f * (clip.out - clip.in)).toFixed(3));
  document.getElementById("rfScrub").value = f;
  document.getElementById("rfTime").textContent = `${(rf.at - clip.in).toFixed(1)}s`;
  document.getElementById("rfVideo").currentTime = rf.at;
}

function resetBox(fromClip) {
  const {fw, fh} = viewOf(rf.size, rf.cell), c = rf.start;
  const fresh = fromClip && fitOf(c) === "fill" && zoomOf(c) >= 1 ? boxFromFields(c, rf.size, rf.cell) : {x: (1 - fw) / 2, y: (1 - fh) / 2, w: fw, h: fh};
  rf.box = fresh;
  paintBox();
}

function pointOn(e) {
  const r = document.getElementById("rfStage").getBoundingClientRect();
  return [clamp01((e.clientX - r.left) / r.width), clamp01((e.clientY - r.top) / r.height)];
}

function startBox(e) {
  if (!rf || !rf.size || (e.button !== 0 && e.button !== 1)) return;
  const [px, py] = pointOn(e), {fw} = viewOf(rf.size, rf.cell), b = rf.box;
  const shape = (rf.cell[1] * rf.size[0]) / (rf.cell[0] * rf.size[1]), handle = e.target.closest(".fh");
  e.preventDefault();
  if (e.button === 1 || rf.space) {
    rf.gesture = {kind: "pan", cx: e.clientX, cy: e.clientY, x: rf.view.x, y: rf.view.y};
  } else if (handle && b) {
    const h = handle.dataset.h, ax = h.includes("w") ? b.x + b.w : b.x, ay = h.includes("n") ? b.y + b.h : b.y;
    rf.gesture = {kind: "grow", ax, ay, shape, max: fw};
  } else if (b && px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h) {
    rf.gesture = {kind: "move", dx: px - b.x, dy: py - b.y};
  } else {
    rf.gesture = {kind: "draw", ax: px, ay: py, cx: e.clientX, cy: e.clientY, moved: false, original: b, shape, max: fw};
  }
  document.getElementById("rfStage").setPointerCapture(e.pointerId);
}

function moveBox(e) {
  const g = rf && rf.gesture;
  if (!g) return;
  if (g.kind === "pan") {
    rf.view = {...rf.view, x: g.x + e.clientX - g.cx, y: g.y + e.clientY - g.cy};
    return paintView();
  }
  const [px, py] = pointOn(e);
  if (g.kind === "draw") {
    if (!g.moved && Math.hypot(e.clientX - g.cx, e.clientY - g.cy) < 4) return;
    g.moved = true;
  }
  if (g.kind === "move") {
    const b = rf.box;
    rf.box = {...b, x: Math.min(1 - b.w, Math.max(0, px - g.dx)), y: Math.min(1 - b.h, Math.max(0, py - g.dy))};
  } else {
    rf.box = boxFrom(g.ax, g.ay, px, py, g.shape, g.max);
  }
  paintBox();
}

// Tracking runs on the server and takes a while, so ask for it, then check on it until it is done. `onPct` hears how far along it is.
async function followJob(body, onPct) {
  let job = await api("/api/follow", "POST", body);
  const id = job.id;
  while (job.state === "queued" || job.state === "working") {
    onPct(job.pct || 0);
    await new Promise(r => setTimeout(r, 700));
    job = await api(`/api/follow/${id}`);
  }
  if (job.state !== "ready") throw new Error(job.message || "Tracking failed");
  return job;
}

async function applyFollow() {
  const {i, box, size, cell} = rf, clip = state.project.clips[i], fields = fieldsFromBox(box, size, cell);
  if (fields.zoom === 1) return toast("Draw a box smaller than the picture so the crop has room to track");
  const btn = document.getElementById("rfApply");
  btn.disabled = true;
  btn.textContent = "Tracking";
  try {
    const found = await followJob({src: clip.src, in: clip.in, out: clip.out, box, at: rf.at}, pct => { btn.textContent = pct > 0 ? `Tracking ${pct}%` : "Tracking"; });
    const keys = followKeys(box, found.track, size, cell, fields);
    state.project = {...state.project, clips: state.project.clips.map((c, n) => (n === i ? {...c, ...fields, track: keys, tracking: true} : c))};
    changed(false, `tracking:${Date.now()}`);
    reframeUi.close();
    toast("Crop is tracking it");
  } catch (err) {
    toast(err.message);
    btn.disabled = false;
    btn.textContent = "Track";
  }
}

function applyBox() {
  if (!rf || !rf.box) return;
  if (rf.mode === "track") return applyFollow();
  const patch = fieldsFromBox(rf.box, rf.size, rf.cell), i = rf.i;
  state.project = {...state.project, clips: state.project.clips.map((c, n) => (n === i ? {...c, ...patch} : c))};
  changed(false, `reframe:${Date.now()}`);
  reframeUi.close();
  toast("Reframed");
}

async function findFaceBox() {
  if (!rf || !rf.size) return;
  const btn = document.getElementById("rfFace");
  btn.disabled = true;
  try {
    const patch = await reframeOne(rf.i);
    if (!patch) return toast("No face found in this clip");
    rf.box = boxFromFields({...state.project.clips[rf.i], ...patch, fit: "fill"}, rf.size, rf.cell);
    paintBox();
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
}

function finishBox(e) {
  if (!rf || !rf.gesture) return;
  const g = rf.gesture;
  if (e.type === "pointercancel") {
    if (g.kind === "draw") { rf.box = g.original; paintBox(); }
  } else if (g.kind === "draw" && !g.moved && g.original) {
    const b = g.original;
    rf.box = {...b, x: Math.max(0, Math.min(1 - b.w, g.ax - b.w / 2)), y: Math.max(0, Math.min(1 - b.h, g.ay - b.h / 2))};
    paintBox();
  }
  rf.gesture = null;
}
const rfStage = document.getElementById("rfStage");
rfStage.addEventListener("pointerdown", startBox);
rfStage.addEventListener("pointermove", moveBox);
rfStage.addEventListener("pointerup", finishBox);
rfStage.addEventListener("pointercancel", finishBox);
rfStage.parentElement.addEventListener("wheel", e => {
  if (!rf || !rf.size) return;
  e.preventDefault();
  if (e.ctrlKey || e.metaKey) return zoomBy(Math.exp(-e.deltaY * 0.01), e);
  rf.view = {...rf.view, x: rf.view.x - e.deltaX, y: rf.view.y - e.deltaY};
  paintView();
}, {passive: false});
document.getElementById("rfZoomIn").onclick = () => zoomBy(1.5);
document.getElementById("rfZoomOut").onclick = () => zoomBy(1 / 1.5);
document.getElementById("rfZoomPct").onclick = () => rf && rf.size && zoomTo(1, 0, 0);
reframeUi.addEventListener("keydown", e => {
  if (!rf || e.target.closest("input, button")) return;
  if (e.key === " ") { rf.space = true; e.preventDefault(); }
  else if (e.key === "+" || e.key === "=") zoomBy(1.5);
  else if (e.key === "-") zoomBy(1 / 1.5);
  else if (e.key === "0") zoomTo(1, 0, 0);
});
reframeUi.addEventListener("keyup", e => { if (rf && e.key === " ") rf.space = false; });
document.getElementById("rfScrub").oninput = e => rf && rf.size && seekStill(Number(e.target.value));
document.getElementById("rfApply").onclick = applyBox;
document.getElementById("rfReset").onclick = () => rf && rf.size && resetBox(false);
document.getElementById("rfFace").onclick = findFaceBox;
document.getElementById("rfStop").onclick = () => { const i = rf.i; reframeUi.close(); setTracking([i], false); };
document.getElementById("rfX").onclick = () => reframeUi.close();
reframeUi.addEventListener("close", () => { document.getElementById("rfVideo").pause(); rf = null; });
