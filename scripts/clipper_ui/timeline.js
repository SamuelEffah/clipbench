// Getting a Short out faster: pick several clips and add them together.
// Depends on app.js and short.js: $, state, changed, laneTotal, sourceAt, insertClip, restartPreviewAt, bankOf.
const bankSel = new Set();
let bankAnchor = -1;

function clearBankSel() {
  bankSel.clear();
  bankAnchor = -1;
}

function pickBank(i, e) {
  if (e.shiftKey && bankAnchor >= 0) {
    for (let n = Math.min(bankAnchor, i); n <= Math.max(bankAnchor, i); n++) bankSel.add(n);
  } else {
    bankSel.has(i) ? bankSel.delete(i) : bankSel.add(i);
    bankAnchor = i;
  }
  renderBank();
}

function addPickedToShort() {
  const bank = bankOf(), picked = [...bankSel].sort((a, b) => a - b).map(i => bank[i]).filter(Boolean);
  if (!picked.length) return;
  const list = timelineOf(), first = laneInsertAt(list, "top", Infinity);
  setTimeline([...list.slice(0, first), ...picked.map(c => newTimelineItem(c, "top")), ...list.slice(first)]);
  for (const c of picked) setTimeout(() => captionFromSubtitles(c), 0);
  clearBankSel();
  state.sel = first;
  changed();
  restartPreviewAt(first);
  toast(`${picked.length} clip${picked.length === 1 ? "" : "s"} added to the timeline`);
}

function bankBar() {
  const bar = document.createElement("div");
  bar.className = "bankbar";
  const all = bankSel.size === bankOf().length;
  bar.innerHTML = `<b class="num">${bankSel.size} selected</b><button class="bb primary" data-bb="add">Add to timeline</button>` +
    `<button class="bb" data-bb="all">${all ? "Select none" : "Select all"}</button><button class="bb" data-bb="clear" aria-label="Clear selection">Clear</button>`;
  bar.querySelector('[data-bb="add"]').onclick = addPickedToShort;
  bar.querySelector('[data-bb="all"]').onclick = () => {
    if (all) clearBankSel(); else bankOf().forEach((_, i) => bankSel.add(i));
    renderBank();
  };
  bar.querySelector('[data-bb="clear"]').onclick = () => { clearBankSel(); renderBank(); };
  return bar;
}

// ----- Keyboard assembly -----

// Where each clip starts on its lane, in seconds, indexed like the timeline list.
function clipStarts(list) {
  const at = {}, prev = {};
  return list.map(c => {
    const lane = laneOf(c), len = outLen(c);
    at[lane] = (at[lane] || 0) - seamOverlap(prev[lane], c, undefined, len);
    const start = at[lane];
    at[lane] += len;
    prev[lane] = c;
    return start;
  });
}

// Move the selected clip one place along its lane.
function moveSelected(dir) {
  const clips = state.project.clips, c = clips[state.sel];
  if (!c) return toast("Select a clip first");
  const lane = laneOf(c), inLane = clips.flatMap((x, i) => (laneOf(x) === lane ? [i] : []));
  const to = inLane.indexOf(state.sel) + dir;
  if (to < 0 || to >= inLane.length) return;
  moveClip(state.sel, lane, to);
  changed();
  restartPreviewAt(state.sel);
}

// Select the clip in the lane above or below that is playing at the same moment as the selected one starts.
function selectLane(dir) {
  const clips = state.project.clips, c = clips[state.sel];
  if (!c) return;
  const lanes = LANES.slice(0, laneCount()), target = lanes[lanes.indexOf(laneOf(c)) + dir];
  if (!target) return;
  const starts = clipStarts(clips), here = starts[state.sel];
  let best = -1, gap = Infinity;
  clips.forEach((x, i) => {
    if (laneOf(x) !== target) return;
    const d = here < starts[i] ? starts[i] - here : here >= starts[i] + outLen(x) ? here - (starts[i] + outLen(x)) : 0;
    if (d < gap) { gap = d; best = i; }
  });
  if (best >= 0) pickClip(best);
}

// ----- Slip and roll -----

const prevInLane = gi => {
  const clips = state.project.clips;
  for (let n = gi - 1; n >= 0; n--) if (laneOf(clips[n]) === laneOf(clips[gi])) return n;
  return -1;
};
const clipBlockAt = gi => stlBody.querySelector(`.stl-clip[data-gi="${gi}"]`);

// Hold Alt and drag a clip to slip it: the picture and sound inside it change, and its place and length on the timeline do not.
function slipOnTimeline(e, gi, block) {
  e.preventDefault();
  e.stopPropagation();
  const c0 = state.project.clips[gi], v = byPath(c0.src), x0 = e.clientX, speed = speedOf(c0);
  const lowest = -c0.in, highest = (v ? v.duration : Infinity) - c0.out;
  let shift = 0;
  block.draggable = false;
  block.setPointerCapture(e.pointerId);
  const move = ev => {
    shift = Math.min(highest, Math.max(lowest, Math.round((ev.clientX - x0) / stlPps * speed * 20) / 20));
    showSndTip(ev.clientX + 14, ev.clientY - 30, `Slip ${shift >= 0 ? "+" : ""}${shift.toFixed(2)}s`);
  };
  const up = () => {
    block.removeEventListener("pointermove", move);
    block.removeEventListener("pointerup", up);
    block.removeEventListener("pointercancel", up);
    block.draggable = true;
    hideSndTip();
    if (!shift) return;
    setClipField(gi, {in: Number((c0.in + shift).toFixed(3)), out: Number((c0.out + shift).toFixed(3))});
    restartPreviewAt(gi);
  };
  block.addEventListener("pointermove", move);
  block.addEventListener("pointerup", up);
  block.addEventListener("pointercancel", up);
}

// Shift-drag a clip's end to roll the cut between it and its neighbour: one gets longer by as much as the other gets shorter.
// Returns false when the clip has no neighbour on that side, so the plain trim runs instead.
function rollOnTimeline(e, gi, side, block) {
  const clips = state.project.clips, other = side === "r" ? nextInLane(gi) : prevInLane(gi);
  if (other < 0) return false;
  e.preventDefault();
  e.stopPropagation();
  const [ia, ib] = side === "r" ? [gi, other] : [other, gi], a0 = clips[ia], b0 = clips[ib];
  const va = byPath(a0.src), sa = speedOf(a0), sb = speedOf(b0), x0 = e.clientX;
  const lowest = Math.max((a0.in + MIN_CLIP - a0.out) / sa, -b0.in / sb);
  const highest = Math.min(((va ? va.duration : Infinity) - a0.out) / sa, (b0.out - MIN_CLIP - b0.in) / sb);
  const blockA = clipBlockAt(ia), blockB = clipBlockAt(ib), wa = blockA.offsetWidth, wb = blockB.offsetWidth, lb = blockB.offsetLeft;
  const starts = clipStarts(clips), cut0 = starts[ib];
  let snapping = {clips, count: clips.length, edit: editCount, starts, skipClips: laterInLane(gi, ia)};
  let d = 0;
  block.setPointerCapture(e.pointerId);
  const move = ev => {
    d = Math.min(highest, Math.max(lowest, (ev.clientX - x0) / stlPps));
    // Rolling changes only the two block widths until release. Reuse its
    // timing preparation, but observe edits made elsewhere during the gesture.
    const current = state.project.clips;
    if (snapping.clips !== current || snapping.count !== current.length || snapping.edit !== editCount) {
      snapping = {clips: current, count: current.length, edit: editCount,
        starts: clipStarts(current), skipClips: laterInLane(gi, ia)};
    }
    const hit = snapNear([cut0 + d], snapping, ev.altKey);
    if (hit) { d = Math.min(highest, Math.max(lowest, hit.at - cut0)); showSnapLine(hit.at); } else hideSnapLine();
    blockA.style.width = `${Math.max(wa + d * stlPps, 28)}px`;
    Object.assign(blockB.style, {left: `${lb + d * stlPps}px`, width: `${Math.max(wb - d * stlPps, 28)}px`});
    showSndTip(ev.clientX + 14, ev.clientY - 30, `Roll ${d >= 0 ? "+" : ""}${d.toFixed(2)}s`);
  };
  const up = () => {
    block.removeEventListener("pointermove", move);
    block.removeEventListener("pointerup", up);
    block.removeEventListener("pointercancel", up);
    hideSndTip();
    hideSnapLine();
    if (Math.abs(d) < 0.02) return render();
    state.project = {...state.project, clips: clips.map((x, n) => (n === ia ? {...x, out: Number((a0.out + d * sa).toFixed(3))} : n === ib ? {...x, in: Number((b0.in + d * sb).toFixed(3))} : x))};
    changed();
    restartPreviewAt(gi);
  };
  block.addEventListener("pointermove", move);
  block.addEventListener("pointerup", up);
  block.addEventListener("pointercancel", up);
  return true;
}
