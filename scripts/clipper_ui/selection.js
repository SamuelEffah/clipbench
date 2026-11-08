// Working on several clips of the Short at once: pick them, edit them together, copy and paste, the right-click menu and the razor.
// Depends on app.js, short.js and timeline.js: state, changed, setClipField, pickClip, restartPreviewAt, clipStarts, splitClipAt.
const picked = new Set();
let pickedLen = -1, clipboard = [], razor = false;

// The clips the next action works on: the picked group, or the selected clip alone.
function chosen() {
  const n = state.project.clips.length;
  if (picked.size > 1) return [...picked].filter(i => i < n).sort((a, b) => a - b);
  return state.sel >= 0 && state.sel < n ? [state.sel] : [];
}

function syncPicked() {
  const n = state.project.clips.length;
  if (n !== pickedLen) picked.clear();
  pickedLen = n;
}

function setPicked(list) {
  picked.clear();
  list.forEach(i => picked.add(i));
  pickedLen = state.project.clips.length;
}

// Shift extends from the selected clip along its lane, Cmd or Ctrl adds or removes one.
function pickMore(gi, e) {
  const clips = state.project.clips, lane = laneOf(clips[gi]);
  const group = picked.size > 1 ? new Set(picked) : new Set(state.sel >= 0 ? [state.sel] : []);
  if (e.shiftKey && state.sel >= 0 && laneOf(clips[state.sel]) === lane) {
    const [a, b] = [Math.min(state.sel, gi), Math.max(state.sel, gi)];
    for (let i = Math.max(0, Math.ceil(a)); i <= b && i < clips.length; i++) {
      if (i in clips && laneOf(clips[i]) === lane) group.add(i);
    }
  } else if (group.has(gi) && group.size > 1) group.delete(gi);
  else group.add(gi);
  if (!group.has(state.sel)) state.sel = [...group][0];
  state.audioSel = null;
  setPicked(group.size > 1 ? [...group] : []);
  state.sel = group.has(gi) ? gi : state.sel;
  setTab("details");
  render();
}

function selectAllClips() {
  const all = state.project.clips.map((_, i) => i);
  if (!all.length) return;
  setPicked(all);
  state.sel = all[0];
  state.audioSel = null;
  setTab("details");
  render();
}

// ----- Bulk edits: each is one new clips list and one undo step -----

function editChosen(patch, key) {
  const ids = new Set(chosen());
  state.project = {...state.project, clips: state.project.clips.map((c, i) => (ids.has(i) ? {...c, ...(typeof patch === "function" ? patch(c) : patch)} : c))};
  changed(Boolean(key), key || "");
}

function removeChosen() {
  const ids = new Set(chosen());
  if (!ids.size) return;
  const first = Math.min(...ids);
  state.project = {...state.project, clips: state.project.clips.filter((_, i) => !ids.has(i))};
  picked.clear();
  state.sel = Math.min(first, state.project.clips.length - 1);
  changed();
  restartPreviewAt(state.sel);
}

function duplicateChosen() {
  const ids = new Set(chosen());
  if (!ids.size) return;
  const clips = state.project.clips, made = [], next = [];
  clips.forEach((c, i) => {
    next.push(c);
    if (ids.has(i)) { made.push(next.length); next.push({...c}); }
  });
  state.project = {...state.project, clips: next};
  state.sel = made[0];
  setPicked(made.length > 1 ? made : []);
  changed();
  restartPreviewAt(state.sel);
}

function toggleMuteChosen() {
  const clips = state.project.clips, ids = chosen();
  if (!ids.length) return toast("Select a clip first");
  const loud = ids.some(i => volumeOf(clips[i]) > 0);
  editChosen({volume: loud ? 0 : 1});
  toast(loud ? "Muted" : "Sound on");
}

function copyChosen() {
  clipboard = chosen().map(i => ({...state.project.clips[i]}));
  if (clipboard.length) toast(`Copied ${clipboard.length} clip${clipboard.length === 1 ? "" : "s"}`);
}

function pasteClips() {
  if (!clipboard.length) return toast("Copy a clip first");
  const clips = state.project.clips, ids = chosen();
  const lane = ids.length ? laneOf(clips[ids[ids.length - 1]]) : "top";
  const after = ids.length ? ids[ids.length - 1] : clips.length - 1;
  const made = clipboard.map(c => ({...c, lane}));
  state.project = {...state.project, clips: [...clips.slice(0, after + 1), ...made, ...clips.slice(after + 1)]};
  const at = made.map((_, n) => after + 1 + n);
  state.sel = at[0];
  setPicked(at.length > 1 ? at : []);
  changed();
  restartPreviewAt(state.sel);
}

// ----- Matching the style of one clip on the others -----

const CAPTION_STYLE = ["capLook", "capHi", "capScale", "capRot", "capX", "capY"];
const PICTURE_SOUND = ["fit", "pan", "zoom", "zx", "zy", "volume"];

function matchStyle(fromIndex, keys, targets, what) {
  const from = state.project.clips[fromIndex];
  if (!from) return;
  const ids = new Set(targets.filter(i => i !== fromIndex));
  if (!ids.size) return toast("There are no other clips to change");
  const patch = Object.fromEntries(keys.map(k => [k, from[k] === undefined ? null : from[k]]));
  state.project = {...state.project, clips: state.project.clips.map((c, i) => (ids.has(i) ? {...c, ...patch} : c))};
  changed();
  toast(`${what} copied to ${ids.size} clip${ids.size === 1 ? "" : "s"}`);
}

const laneMates = i => state.project.clips.flatMap((c, n) => (laneOf(c) === laneOf(state.project.clips[i]) ? [n] : []));

function applyRows(i) {
  const mk = (label, run) => Object.assign(document.createElement("button"), {className: "mini", textContent: label, onclick: run});
  const top = isTop(state.project.clips[i]);
  return [...(top ? [mk("Use this caption style on the whole lane", () => matchStyle(i, CAPTION_STYLE, laneMates(i), "Caption style"))] : []),
    mk("Use this framing and sound on the whole lane", () => matchStyle(i, PICTURE_SOUND, laneMates(i), "Framing and sound"))];
}

// ----- The panel for a group -----

function bulkSlider(label, key, min, max, step, show) {
  const clips = state.project.clips, ids = chosen(), vals = ids.map(i => (key === "volume" ? volumeOf(clips[i]) : clips[i][key] || 0));
  const same = vals.every(v => v === vals[0]), avg = vals.reduce((s, v) => s + v, 0) / vals.length;
  const row = document.createElement("label");
  row.className = "zoomrow";
  const out = Object.assign(document.createElement("output"), {className: "num", textContent: same ? show(vals[0]) : "Mixed"});
  const input = Object.assign(document.createElement("input"), {type: "range", min, max, step, value: same ? vals[0] : avg});
  input.setAttribute("aria-label", `${label} for the selected clips`);
  input.oninput = () => {
    const v = Number(input.value);
    out.textContent = show(v);
    editChosen({[key]: v}, `bulk-${key}`);
  };
  input.onchange = () => render();
  row.append(Object.assign(document.createElement("span"), {textContent: label}), input, out);
  return row;
}

function bulkDetails() {
  const clips = state.project.clips, ids = chosen();
  const head = document.createElement("div");
  head.className = "dhead";
  head.innerHTML = `<div class="pic multi-pic"><b class="num">${ids.length}</b></div><div><b>${ids.length} clips selected</b><small class="num">${outLenOf(ids).toFixed(1)}s together</small></div>`;
  const remove = Object.assign(document.createElement("button"), {className: "ico", title: "Remove the selected clips", innerHTML: '<svg class="i"><use href="#trash"/></svg>'});
  remove.setAttribute("aria-label", "Remove the selected clips");
  remove.onclick = removeChosen;
  head.append(remove);
  const speeds = ids.map(i => speedOf(clips[i])), speedSame = speeds.every(s => s === speeds[0]);
  const menu = Object.assign(document.createElement("select"), {className: "menu"});
  menu.setAttribute("aria-label", "Speed for the selected clips");
  if (!speedSame) menu.add(new Option("Mixed", "mixed", true, true));
  for (const s of SPEEDS) menu.add(new Option(s === 1 ? "1x (normal)" : `${s}x`, s, false, speedSame && speeds[0] === s));
  menu.onchange = () => { if (menu.value !== "mixed") editChosen({speed: Number(menu.value)}); };
  const speedRow = numberRow("Speed", menu);
  const secs = v => (v === 0 ? "Off" : `${v.toFixed(1)}s`);
  const muteBtn = Object.assign(document.createElement("button"), {className: "mini", textContent: "Mute or unmute them", onclick: toggleMuteChosen});
  const primary = state.sel;
  const style = [Object.assign(document.createElement("button"), {className: "mini", textContent: "Use the caption style of the first clip", onclick: () => matchStyle(primary, CAPTION_STYLE, ids, "Caption style")}),
    Object.assign(document.createElement("button"), {className: "mini", textContent: "Use the framing and sound of the first clip", onclick: () => matchStyle(primary, PICTURE_SOUND, ids, "Framing and sound")})];
  return [head, section("Speed", [speedRow]),
    section("Sound and fades", [bulkSlider("Volume", "volume", 0, MAX_VOLUME, 0.05, v => (v === 0 ? "Muted" : percent(v))), bulkSlider("Fade in", "fadeIn", 0, 3, 0.1, secs), bulkSlider("Fade out", "fadeOut", 0, 3, 0.1, secs), muteBtn]),
    section("Match", style)];
}
const outLenOf = ids => ids.reduce((s, i) => s + outLen(state.project.clips[i]), 0);

// ----- Marquee: drag on empty track space to pick the clips inside the box -----

stlBody.addEventListener("pointerdown", e => {
  if (e.button || !inShort() || !e.target.matches(".stl-track, .stl-lane, .stl-body")) return;
  if (e.target.closest(".sruler, .stl-playhead")) return;
  const origin = stlBody.getBoundingClientRect(), x0 = e.clientX, y0 = e.clientY;
  let box = null, hits = [], geometry = null;
  const move = ev => {
    if (!box && Math.hypot(ev.clientX - x0, ev.clientY - y0) < 5) return;
    if (!box) { box = Object.assign(document.createElement("i"), {className: "stl-marquee"}); stlBody.append(box); }
    const l = Math.min(x0, ev.clientX), t = Math.min(y0, ev.clientY), r = Math.max(x0, ev.clientX), b = Math.max(y0, ev.clientY);
    Object.assign(box.style, {left: `${l - origin.left + stlBody.scrollLeft}px`, top: `${t - origin.top + stlBody.scrollTop}px`, width: `${r - l}px`, height: `${b - t}px`});
    const nodes = Array.from(stlBody.querySelectorAll(".stl-clip"));
    const host = stlBody.getBoundingClientRect();
    const key = [state.project, stlPps, stlBody.scrollLeft, stlBody.scrollTop,
      host.left, host.top, host.width, host.height, stlBody.scrollWidth, stlBody.scrollHeight];
    const animating = stlBody.getAnimations?.({subtree: true}).some(animation => animation.playState === "running" || animation.playState === "pending");
    if (!geometry || animating || geometry.animating || key.some((value, i) => value !== geometry.key[i]) ||
        nodes.length !== geometry.nodes.length || nodes.some((node, i) => node !== geometry.nodes[i])) {
      // Read all bounds before changing highlights, and reuse them for this
      // gesture until scrolling, layout, content, or project state changes.
      geometry = {key, nodes, animating, bounds: nodes.map(node => node.getBoundingClientRect())};
    }
    hits = [];
    nodes.forEach((el, i) => {
      const k = geometry.bounds[i], inside = k.left < r && k.right > l && k.top < b && k.bottom > t;
      el.classList.toggle("marked", inside);
      if (inside) hits.push(Number(el.dataset.gi));
    });
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    if (!box) return;
    box.remove();
    stlBody.querySelectorAll(".stl-clip.marked").forEach(el => el.classList.remove("marked"));
    if (!hits.length) return;
    state.sel = hits[0];
    state.audioSel = null;
    setPicked(hits.length > 1 ? hits : []);
    setTab("details");
    render();
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
});

// ----- Razor -----

function setRazor(on) {
  razor = on;
  document.body.classList.toggle("razor", on);
  if (on) toast("Razor: click a clip to cut it there. Press C or Esc to stop");
}

// A time on the lane, from where the pointer is over the clip's track.
const laneTimeAt = (block, e) => (e.clientX - block.parentElement.getBoundingClientRect().left) / stlPps;

function razorCut(gi, block, e) {
  splitClipAt(gi, laneTimeAt(block, e));
}

// ----- Right-click menu -----

let ctx = null;
function closeCtx() {
  if (ctx) ctx.remove();
  ctx = null;
}

function openCtx(x, y, items) {
  closeCtx();
  ctx = document.createElement("div");
  ctx.className = "ctx";
  ctx.setAttribute("role", "menu");
  for (const it of items) {
    if (it === "-") { ctx.append(Object.assign(document.createElement("hr"), {className: "ctxsep"})); continue; }
    const b = Object.assign(document.createElement("button"), {className: "mi", disabled: Boolean(it.off), innerHTML: `<span>${esc(it.label)}</span>${it.key ? `<kbd>${it.key}</kbd>` : ""}`});
    b.setAttribute("role", "menuitem");
    b.onclick = e => { e.stopPropagation(); closeCtx(); it.run(); };
    ctx.append(b);
  }
  document.body.append(ctx);
  const r = ctx.getBoundingClientRect();
  ctx.style.left = `${Math.max(8, Math.min(x, innerWidth - r.width - 8))}px`;
  ctx.style.top = `${Math.max(8, Math.min(y, innerHeight - r.height - 8))}px`;
}

stlBody.addEventListener("contextmenu", e => {
  const block = e.target.closest(".stl-clip, .stl-snd");
  if (!inShort() || !block || block.dataset.gi === undefined) return;
  e.preventDefault();
  const gi = Number(block.dataset.gi);
  if (!picked.has(gi) || picked.size < 2) { picked.clear(); state.sel = gi; state.audioSel = null; render(); }
  const ids = chosen(), many = ids.length > 1, plural = many ? ` ${ids.length} clips` : "";
  const T = laneTimeAt(block, e);
  const speedItem = (label, s) => ({label, run: () => editChosen({speed: s})});
  openCtx(e.clientX, e.clientY, [
    {label: "Split here", key: "S", off: many, run: () => splitClipAt(gi, T)},
    {label: `Duplicate${plural}`, key: "D", run: duplicateChosen},
    {label: `Copy${plural}`, key: "⌘C", run: copyChosen},
    {label: "Paste after", key: "⌘V", off: !clipboard.length, run: pasteClips},
    "-",
    {label: `Mute or unmute${plural}`, run: toggleMuteChosen},
    voiceMenuItem(ids),
    speedItem("Speed: 0.5x", 0.5), speedItem("Speed: normal", 1), speedItem("Speed: 1.5x", 1.5), speedItem("Speed: 2x", 2),
    "-",
    ...(isTop(state.project.clips[gi]) ? [{label: "Caption style to the whole lane", run: () => matchStyle(gi, CAPTION_STYLE, laneMates(gi), "Caption style")}] : []),
    {label: "Framing and sound to the whole lane", run: () => matchStyle(gi, PICTURE_SOUND, laneMates(gi), "Framing and sound")},
    "-",
    {label: `Remove${plural}`, key: "⌫", run: removeChosen},
  ]);
});
document.addEventListener("click", closeCtx);
window.addEventListener("blur", closeCtx);

// ----- Keys -----

document.addEventListener("keydown", e => {
  if (e.key === "Escape") { closeCtx(); if (razor) setRazor(false); else if (picked.size) { picked.clear(); render(); } return; }
  if (!inShort() || typing(e) || document.querySelector("dialog[open]")) return;
  const mod = e.metaKey || e.ctrlKey, k = e.key.toLowerCase();
  if (mod && !e.shiftKey && !e.altKey && k === "a") { e.preventDefault(); selectAllClips(); }
  else if (mod && !e.shiftKey && !e.altKey && k === "c") { e.preventDefault(); copyChosen(); }
  else if (mod && !e.shiftKey && !e.altKey && k === "v") { e.preventDefault(); pasteClips(); }
  else if (!mod && !e.altKey && k === "c") { e.preventDefault(); setRazor(!razor); }
});
