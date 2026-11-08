// Moving a clip along or between lanes with the pointer. A ghost of the clip follows the hand, the other clips slide to
// make room (short.js: showSlot, makeRoom, slotFromX), the lane is the one under the pointer, the timeline scrolls when
// the pointer is near an edge, and Escape lets go. The browser's own drag and drop is not used: it gives a frozen
// snapshot, events a few times a second and no scrolling. Depends on short.js: stlBody, dragPx, moveClip, clearSlots,
// restartPreviewAt; lanes.js: laneLocked, lockedToast; app.js: state, changed, laneOf.
const DRAG_START_PX = 4, EDGE_SCROLL_PX = 48, EDGE_SCROLL_MAX = 24;

// How far to scroll per frame for a pointer this close to an edge of the timeline: nothing in the middle, faster the closer.
function edgeScrollStep(x, box) {
  const fromLeft = x - box.left, fromRight = box.left + box.width - x;
  if (fromLeft < EDGE_SCROLL_PX) return -Math.ceil((1 - Math.max(0, fromLeft) / EDGE_SCROLL_PX) * EDGE_SCROLL_MAX);
  if (fromRight < EDGE_SCROLL_PX) return Math.ceil((1 - Math.max(0, fromRight) / EDGE_SCROLL_PX) * EDGE_SCROLL_MAX);
  return 0;
}

// The lane whose track is under this height, or the nearest one when the pointer is between lanes.
function laneAtY(tracks, y) {
  let best = null, gap = Infinity;
  for (const track of tracks) {
    const r = track.getBoundingClientRect();
    const d = y < r.top ? r.top - y : y > r.bottom ? y - r.bottom : 0;
    if (d < gap) { gap = d; best = track.dataset.lane; }
  }
  return best;
}

function startLaneDrag(e, gi, block) {
  if (e.button !== 0 || e.altKey || e.shiftKey || e.metaKey || e.ctrlKey) return;
  if (e.target.closest && e.target.closest(".th, .stl-del")) return;
  const clip = state.project.clips[gi];
  if (!clip || laneLocked(laneOf(clip))) return;
  // Or the browser starts selecting text as the hand moves away from the block.
  e.preventDefault();
  const x0 = e.clientX, y0 = e.clientY, grab = block.getBoundingClientRect();
  let ghost = null, lane = null, last = e, frame = 0;
  const tracks = () => stlBody.querySelectorAll(".stl-track[data-lane]");
  const follow = ev => {
    ghost.style.left = `${grab.left + ev.clientX - x0}px`;
    ghost.style.top = `${grab.top + ev.clientY - y0}px`;
  };
  const place = ev => {
    lane = laneAtY(tracks(), ev.clientY);
    if (lane) showSlot(ev, lane);
  };
  const scroll = () => {
    frame = 0;
    const step = edgeScrollStep(last.clientX, stlBody.getBoundingClientRect());
    if (!step) return;
    const before = stlBody.scrollLeft;
    stlBody.scrollLeft = Math.max(0, Math.min(stlBody.scrollWidth - stlBody.clientWidth, before + step));
    if (stlBody.scrollLeft !== before) place(last);
    frame = requestAnimationFrame(scroll);
  };
  const begin = () => {
    block.classList.add("dragging");
    dragPx = block.offsetWidth;
    ghost = block.cloneNode(true);
    ghost.classList.add("stl-drag-ghost");
    ghost.classList.remove("dragging", "sel", "multi");
    ghost.style.transform = "";
    Object.assign(ghost.style, {width: `${grab.width}px`, height: `${grab.height}px`});
    document.body.append(ghost);
    document.body.classList.add("lane-dragging");
  };
  const stop = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    window.removeEventListener("pointercancel", cancel);
    window.removeEventListener("keydown", key);
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    if (!ghost) return false;
    ghost.remove();
    block.classList.remove("dragging");
    block.style.transform = "";
    block.dataset.moved = "1";
    document.body.classList.remove("lane-dragging");
    dragPx = 0;
    clearSlots();
    return true;
  };
  const move = ev => {
    last = ev;
    if (!ghost) {
      if (Math.abs(ev.clientX - x0) < DRAG_START_PX && Math.abs(ev.clientY - y0) < DRAG_START_PX) return;
      begin();
    }
    ev.preventDefault();
    follow(ev);
    place(ev);
    if (!frame && edgeScrollStep(ev.clientX, stlBody.getBoundingClientRect())) frame = requestAnimationFrame(scroll);
  };
  const up = ev => {
    const target = lane;
    if (!stop() || !target) return;
    if (laneLocked(target)) return lockedToast();
    moveClip(gi, target, slotFromX(ev, target));
    changed();
    restartPreviewAt(state.sel);
  };
  const cancel = () => stop();
  const key = ev => { if (ev.key === "Escape") stop(); };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", cancel);
  window.addEventListener("keydown", key);
}
