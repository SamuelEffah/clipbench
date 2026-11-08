// Short preview: drag a picture to move its crop, drag a corner or scroll to zoom it, double-click to reset.
// Depends on app.js (preview, mirror, laneBoxes, lowNow, laneVids, fitOf, zoomOf) and short.js (inShort).
const FRAME_ZOOM = {min: 0.25, max: 4, snap: 0.04};
const framer = Object.assign(document.createElement("div"), {id: "framer"});
const frameBox = Object.assign(document.createElement("div"), {id: "frameBox", hidden: true});
frameBox.innerHTML = ["nw", "ne", "sw", "se"].map(h => `<i class="fh ${h}" data-h="${h}"></i>`).join("") + '<span id="frameRead"></span><div id="frameBar"><button id="frameAi" type="button" title="Reframe: find the face and crop to it" aria-label="Reframe"><svg viewBox="0 0 24 24"><path d="M7 3v13a1 1 0 0 0 1 1h13M3 7h13a1 1 0 0 1 1 1v13"/></svg></button><button id="frameTrack" type="button" title="Tracking: move the crop with the subject" aria-label="Tracking"><svg viewBox="0 0 24 24"><path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2M9 9.5v1.5M15 9.5v1.5M12 9.5v3.5h-1M9 16c1.7 1.4 4.3 1.4 6 0"/></svg></button><button id="frameSpeaker" type="button" title="Follow the speaker: keep the crop on whoever is talking" aria-label="Follow the speaker"><svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.2"/><path d="M3.5 20c0-3.4 2.4-5.5 5.5-5.5s5.5 2.1 5.5 5.5M17.5 8.5c1 1 1 2.8 0 3.8M20 6.5c2 2.2 2 5.8 0 8"/></svg></button></div>';
framer.append(frameBox);
mirror.after(framer);
let frameGesture = null, frameLane = null;

const frameLive = () => inShort() && preview.on && !document.querySelector("dialog[open]");

// Keep the overlay on the picture, whatever the layout code does to the canvas.
function placeFramer() {
  const {left, top, width, height} = mirror.style;
  Object.assign(framer.style, {left, top, width, height});
}
new MutationObserver(placeFramer).observe(mirror, {attributes: true, attributeFilter: ["style"]});
placeFramer();

// The lane under the pointer: its box, its clip's index, and the video that is drawing it.
function laneUnder(e) {
  const r = mirror.getBoundingClientRect(), fx = (e.clientX - r.left) / r.width, fy = (e.clientY - r.top) / r.height;
  const k = splitOn() ? laneCount() : 1;
  const n = laneBoxes(k).findIndex(([x, y, w, h]) => fx >= x && fx < x + w && fy >= y && fy < y + h);
  if (n < 0) return null;
  const clip = n === 0 ? state.project.clips[preview.idx] : lowNow[n - 1] && lowNow[n - 1].clip;
  const i = clip ? state.project.clips.indexOf(clip) : -1;
  if (i < 0) return null;
  const [bx, by, bw, bh] = laneBoxes(k)[n];
  return {n, i, clip, vid: n === 0 ? video : laneVids[n - 1], box: [bx, by, bw, bh], rect: r};
}

// What a drag on this picture changes, if anything: the fill crop position, or the zoom focus.
function dragKind(lane) {
  const {clip, vid, box, rect} = lane;
  const z = zoomOf(clip);
  if (z > 1 || (z < 1 && fitOf(clip) !== "fill")) return "focus";
  if (z < 1 && vid.videoWidth) return "zoom-out";
  if (fitOf(clip) !== "fill" || !vid.videoWidth) return null;
  const W = mirror.width * box[2], H = mirror.height * box[3];
  const r = Math.max(W / vid.videoWidth, H / vid.videoHeight);
  const over = {x: vid.videoWidth * r - W, y: vid.videoHeight * r - H};
  if (Math.max(over.x, over.y) < 1) return null;
  return over.x >= over.y ? "pan-x" : "pan-y";
}

function showFrameBox(lane) {
  frameBox.hidden = !lane;
  frameLane = lane;
  if (!lane) return;
  const [x, y, w, h] = lane.box;
  Object.assign(frameBox.style, {left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%`});
  lane = {...lane, clip: state.project.clips[lane.i]};
  frameLane = lane;
  const z = zoomOf(lane.clip);
  $("frameRead").textContent = z === 1 ? "" : `${z.toFixed(2).replace(/0$/, "")}x`;
  framer.dataset.move = dragKind(lane) ? "yes" : "no";
  $("frameTrack").dataset.on = trackingOn(lane.clip) ? "yes" : "no";
}

function setFrame(i, patch, key) {
  const clip = state.project.clips[i];
  if (!clip || Object.entries(patch).every(([field, value]) => clip[field] === value)) return;
  state.project = {...state.project, clips: state.project.clips.map((c, n) => (n === i ? {...c, ...patch} : c))};
  changed(true, key);
}

const clampFrame = v => Math.min(1, Math.max(0, Number(v.toFixed(3))));

function startFrame(e) {
  if (!frameLive() || e.button !== 0) return;
  if (e.target.closest("#frameBar") || overCaption(e)) return;
  const handle = e.target.closest(".fh");
  const lane = handle && frameLane ? {...frameLane, clip: state.project.clips[frameLane.i]} : laneUnder(e);
  if (!lane) return;
  const kind = handle ? "zoom" : dragKind(lane);
  if (!kind) return;
  e.preventDefault();
  const {clip, rect, box} = lane;
  const c = {x: rect.left + (box[0] + box[2] / 2) * rect.width, y: rect.top + (box[1] + box[3] / 2) * rect.height};
  frameGesture = {kind, lane, x: e.clientX, y: e.clientY, pan: clip.pan === undefined ? 0.5 : clip.pan,
    zx: clip.zx === undefined ? 0.5 : clip.zx, zy: clip.zy === undefined ? 0.5 : clip.zy, zoom: zoomOf(clip),
    center: c, dist: Math.hypot(e.clientX - c.x, e.clientY - c.y) || 1, scale: mirror.width / rect.width};
  framer.setPointerCapture(e.pointerId);
  framer.classList.add("active");
}

function moveFrame(e) {
  if (!frameGesture) {
    if (frameLive() && !e.buttons) showFrameBox(overCaption(e) ? null : laneUnder(e));
    return;
  }
  const g = frameGesture, {i, box, vid} = g.lane;
  const dx = (e.clientX - g.x) * g.scale, dy = (e.clientY - g.y) * g.scale;
  const W = mirror.width * box[2], H = mirror.height * box[3];
  if (g.kind === "zoom") {
    const raw = g.zoom * Math.hypot(e.clientX - g.center.x, e.clientY - g.center.y) / g.dist;
    const z = Math.abs(raw - 1) < FRAME_ZOOM.snap ? 1 : Math.min(FRAME_ZOOM.max, Math.max(FRAME_ZOOM.min, raw));
    setFrame(i, {zoom: Number(z.toFixed(2))}, `zoom:${i}`);
  } else if (g.kind === "zoom-out") {
    const r = Math.max(W / vid.videoWidth, H / vid.videoHeight) * g.zoom;
    const roomX = W - vid.videoWidth * r, roomY = H - vid.videoHeight * r;
    const patch = {};
    if (roomX > 0.5) patch.zx = clampFrame(g.zx + dx / roomX);
    if (roomY > 0.5) patch.zy = clampFrame(g.zy + dy / roomY);
    if (roomX < -0.5) patch.pan = clampFrame(g.pan + dx / roomX);
    else if (roomY < -0.5) patch.pan = clampFrame(g.pan + dy / roomY);
    setFrame(i, patch, `focus:${i}`);
  } else if (g.kind === "focus") {
    const patch = {zx: clampFrame(g.zx - dx / (W * (g.zoom - 1))), zy: clampFrame(g.zy - dy / (H * (g.zoom - 1)))};
    if (g.zoom > 1 && fitOf(g.lane.clip) === "fill" && vid.videoWidth) {
      // Fill already crops the source before zoom. Move through both crop ranges.
      const r = Math.max(W / vid.videoWidth, H / vid.videoHeight);
      const overX = Math.max(0, vid.videoWidth * r - W) * g.zoom;
      const overY = Math.max(0, vid.videoHeight * r - H) * g.zoom;
      const zoomX = W * (g.zoom - 1), zoomY = H * (g.zoom - 1);
      if (overX > 0.5) patch.pan = patch.zx = clampFrame((overX * g.pan + zoomX * g.zx - dx) / (overX + zoomX));
      if (overY > 0.5) patch.pan = patch.zy = clampFrame((overY * g.pan + zoomY * g.zy - dy) / (overY + zoomY));
    }
    setFrame(i, patch, `focus:${i}`);
  } else {
    const r = Math.max(W / vid.videoWidth, H / vid.videoHeight);
    const room = g.kind === "pan-x" ? W - vid.videoWidth * r : H - vid.videoHeight * r;
    setFrame(i, {pan: clampFrame(g.pan + (g.kind === "pan-x" ? dx : dy) / room)}, `pan:${i}`);
  }
  showFrameBox(g.lane);
}

function endFrame() {
  if (!frameGesture) return;
  frameGesture = null;
  framer.classList.remove("active");
  render();
}

$("frameAi").addEventListener("click", () => { if (frameLane) openReframe(frameLane.i); });
$("frameTrack").addEventListener("click", () => { if (frameLane) openReframe(frameLane.i, "track"); });
$("frameSpeaker").addEventListener("click", () => { if (frameLane) reframeClips([frameLane.i], true, true); });
framer.addEventListener("pointerdown", startFrame);
framer.addEventListener("pointermove", moveFrame);
framer.addEventListener("pointerup", endFrame);
framer.addEventListener("pointercancel", endFrame);
framer.addEventListener("pointerleave", () => { if (!frameGesture) showFrameBox(null); });

framer.addEventListener("wheel", e => {
  if (!frameLive()) return;
  const lane = laneUnder(e);
  if (!lane) return;
  e.preventDefault();
  const z = Math.min(FRAME_ZOOM.max, Math.max(FRAME_ZOOM.min, zoomOf(lane.clip) * Math.exp(-e.deltaY * 0.002)));
  setFrame(lane.i, {zoom: Number((Math.abs(z - 1) < 0.02 ? 1 : z).toFixed(2))}, `zoom:${lane.i}`);
  showFrameBox(lane);
}, {passive: false});

framer.addEventListener("dblclick", e => {
  if (!frameLive()) return;
  const lane = laneUnder(e);
  if (!lane) return;
  setFrame(lane.i, {pan: 0.5, zoom: 1, zx: 0.5, zy: 0.5}, `reframe:${lane.i}`);
  render();
  toast("Framing reset");
});

// The caption's own frame takes over while the pointer is on the caption.
$("card1080").addEventListener("pointermove", e => { if (!frameGesture && overCaption(e)) showFrameBox(null); });
