// Short preview: drag the seam between lanes to resize them (split and three; four stays an equal grid).
// Depends on app.js (laneBoxes, SPLIT_RANGE, seamOf, state, changed, mirror, templateOf) and framer.js (framer, frameLive).
const SEAM_SNAPS = [1 / 3, 0.5, 2 / 3];
const SEAM_SNAP_WITHIN = 0.02;
const SEAM_FIELDS = {row: "rowSplit", col: "colSplit"};
const seamEls = {};
for (const axis of ["row", "col"]) {
  const el = Object.assign(document.createElement("div"), {className: `seam ${axis}`, hidden: true});
  el.dataset.axis = axis;
  el.innerHTML = '<i class="grip"></i><span class="tip"></span>';
  seamEls[axis] = el;
  framer.prepend(el);
}
let seamGesture = null;

// Which seams the current layout has, as {axis: [left, top, width, height]} in fractions of the picture.
function seamBoxes() {
  const k = splitOn() ? laneCount() : 1;
  if (k < 2 || k > 3) return {};
  const [, second] = laneBoxes(k);
  const out = {row: [0, second[1], 1, 0]};
  if (k === 3) out.col = [second[0] + second[2], second[1], 0, second[3]];
  return out;
}

function placeSeams() {
  const live = frameLive() && !!document.querySelector("body[data-mode='short']");
  const boxes = live ? seamBoxes() : {};
  for (const axis in seamEls) {
    const el = seamEls[axis], b = boxes[axis];
    el.hidden = !b;
    if (!b) continue;
    Object.assign(el.style, {left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${b[2] * 100}%`, height: `${b[3] * 100}%`});
    el.querySelector(".tip").textContent = `${Math.round(seamValue(axis) * 100)}%`;
  }
}

const seamValue = axis => seamOf(state.project[SEAM_FIELDS[axis]]);

function snapSeam(v, free) {
  if (free) return v;
  const near = SEAM_SNAPS.find(s => Math.abs(v - s) < SEAM_SNAP_WITHIN);
  return near === undefined ? v : near;
}

function setSeam(axis, v, key) {
  const field = SEAM_FIELDS[axis];
  const next = Number(seamOf(v).toFixed(3));
  if (next === seamValue(axis) && state.project[field] !== undefined) return;
  state.project = {...state.project, [field]: next};
  changed(true, key);
}

function startSeam(e) {
  if (e.button !== 0 || !frameLive()) return;
  e.preventDefault();
  e.stopPropagation();
  const el = e.currentTarget;
  seamGesture = {axis: el.dataset.axis};
  el.setPointerCapture(e.pointerId);
  el.classList.add("active");
}

function moveSeam(e) {
  if (!seamGesture) return;
  const r = mirror.getBoundingClientRect(), {axis} = seamGesture;
  let v;
  if (axis === "row") v = (e.clientY - r.top) / r.height;
  else v = (e.clientX - r.left) / r.width;
  setSeam(axis, snapSeam(v, e.altKey), `seam:${axis}`);
  placeSeams();
}

function endSeam(e) {
  if (!seamGesture) return;
  seamEls[seamGesture.axis].classList.remove("active");
  seamGesture = null;
  render();
}

for (const el of Object.values(seamEls)) {
  el.addEventListener("pointerdown", startSeam);
  el.addEventListener("pointermove", moveSeam);
  el.addEventListener("pointerup", endSeam);
  el.addEventListener("pointercancel", endSeam);
  el.addEventListener("wheel", e => e.stopPropagation(), {passive: true});
  el.addEventListener("dblclick", e => {
    e.stopPropagation();
    state.project = {...state.project, [SEAM_FIELDS[el.dataset.axis]]: 0.5};
    changed(true, `seam:${el.dataset.axis}`);
    render();
    toast("Split reset");
  });
}

// Follow undo, template changes and mode switches without hooking each of them.
let seamKey = "";
(function watchSeams() {
  const key = [frameLive(), splitOn() ? laneCount() : 1, seamValue("row"), seamValue("col")].join();
  if (key !== seamKey) { seamKey = key; placeSeams(); }
  requestAnimationFrame(watchSeams);
})();
