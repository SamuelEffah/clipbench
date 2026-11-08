// Lane controls on the Short timeline: mute a lane's sound, solo it to hear it alone, lock it against edits.
// Mute and lock are saved with the project (laneMute, laneLock). Solo is only for listening and is never saved.
// Depends on app.js (state, changed, toast, laneOf, volumeOf, laneVids, preview, syncLanes, applyLiveSound) and short.js (stlBody, laneTrack, LANE_NAMES).
const laneSolo = new Set();

const laneMuted = lane => Boolean((state.project.laneMute || {})[lane]);
const laneLocked = lane => Boolean((state.project.laneLock || {})[lane]);
const laneDimmedBySolo = lane => laneSolo.size > 0 && !laneSolo.has(lane);
const laneQuiet = c => laneMuted(laneOf(c)) || laneDimmedBySolo(laneOf(c));

// What the preview plays for a clip: its own level, or nothing when its lane is muted or another lane is soloed.
const playVolume = c => (laneQuiet(c) ? 0 : volumeOf(c));

const NAME_MAX = 20;
const COLLAPSE_KEY = "bench.soundCollapsed";

// Which lanes have their sound row folded away. It is a view setting, kept in this browser and not in the project.
function readCollapsed() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLLAPSE_KEY) || "{}");
    return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
  } catch {
    return {};
  }
}
let collapsedSound = readCollapsed();
const soundCollapsed = lane => Boolean(collapsedSound[lane]);

function toggleSoundRow(lane) {
  collapsedSound = {...collapsedSound, [lane]: !soundCollapsed(lane)};
  if (!collapsedSound[lane]) delete collapsedSound[lane];
  try {
    localStorage.setItem(COLLAPSE_KEY, JSON.stringify(collapsedSound));
  } catch {}
  renderShortTl();
}

// A lane's name: the one you gave it, else Lane 1 to Lane 4.
const laneNameOf = lane => ((state.project.laneName || {})[lane] || "").trim() || LANE_NAMES[lane];

function setLaneName(lane, text) {
  const name = text.replace(/\s+/g, " ").trim().slice(0, NAME_MAX).trim();
  const next = {...(state.project.laneName || {})};
  if (name && name !== LANE_NAMES[lane]) next[lane] = name;
  else delete next[lane];
  if (JSON.stringify(next) === JSON.stringify(state.project.laneName || {})) return;
  state.project = {...state.project, laneName: next};
  changed(false, `laneName:${lane}`);
}

// Swap the name for a text box. Enter keeps the new name, Escape leaves it, and an empty name goes back to the default.
function editLaneName(span, lane) {
  const input = Object.assign(document.createElement("input"), {className: "lh-edit", value: laneNameOf(lane), maxLength: NAME_MAX});
  input.setAttribute("aria-label", `Name of ${LANE_NAMES[lane]}`);
  let done = false;
  const finish = keep => {
    if (done) return;
    done = true;
    if (keep) setLaneName(lane, input.value);
    renderShortTl();
  };
  input.onkeydown = e => {
    e.stopPropagation();
    if (e.key === "Enter") finish(true);
    else if (e.key === "Escape") finish(false);
  };
  input.onblur = () => finish(true);
  span.replaceWith(input);
  input.focus();
  input.select();
}

const lockedToast = () => toast("That lane is locked. Unlock it to edit");

// True (with a message) when the clip at index i sits in a locked lane.
function blockedByLock(i) {
  const c = state.project.clips[i];
  if (!c || !laneLocked(laneOf(c))) return false;
  lockedToast();
  return true;
}

function setLaneFlag(key, lane, on) {
  const next = {...(state.project[key] || {})};
  if (on) next[lane] = true;
  else delete next[lane];
  state.project = {...state.project, [key]: next};
  changed(true, `${key}:${lane}`);
  renderShortTl();
}

// Make the sound that is already playing follow a mute or solo change.
function refreshLaneSound() {
  const c = state.project.clips[preview.idx];
  if (c) applyLiveSound(c);
  if (preview.on) syncLanes();
}

function toggleMute(lane) {
  setLaneFlag("laneMute", lane, !laneMuted(lane));
  refreshLaneSound();
}

function toggleSolo(lane) {
  laneSolo.has(lane) ? laneSolo.delete(lane) : laneSolo.add(lane);
  renderShortTl();
  refreshLaneSound();
}

function toggleLock(lane) {
  setLaneFlag("laneLock", lane, !laneLocked(lane));
  toast(laneLocked(lane) ? `${laneNameOf(lane)} locked` : `${laneNameOf(lane)} unlocked`);
}

const LANE_ICONS = {
  mute: '<svg viewBox="0 0 24 24"><path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path class="wave" d="M15.5 9a4 4 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11"/><path class="slash" d="M4 4l16 16"/></svg>',
  sound: '<svg viewBox="0 0 24 24"><path d="M5 10v4M9 7v10M13 4v16M17 8v8M21 11v2"/></svg>',
  lock: '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path class="shackle" d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
};

function laneButton(kind, lane, on, title, onclick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `lh-btn lh-${kind}`;
  b.title = title;
  b.setAttribute("aria-label", title);
  b.setAttribute("aria-pressed", on);
  b.innerHTML = kind === "solo" ? "S" : LANE_ICONS[kind];
  b.onclick = onclick;
  return b;
}

// One header per lane, lined up with its track. They live beside the timeline so scrolling and zooming never move them.
function paintLaneHeads(lanes) {
  const heads = $("stlHeads");
  heads.replaceChildren(laneAddControls(), ...lanes.map(lane => {
    const track = laneTrack(lane), head = document.createElement("div");
    head.className = "lanehead";
    head.dataset.lane = lane;
    Object.assign(head.style, {top: `${track.offsetTop}px`, height: `${track.offsetHeight}px`});
    const name = Object.assign(document.createElement("span"), {className: "lh-name", textContent: laneNameOf(lane), title: "Double-click to rename"});
    name.ondblclick = () => editLaneName(name, lane);
    const row = document.createElement("div");
    row.className = "lh-row";
    row.append(
      laneButton("mute", lane, laneMuted(lane), laneMuted(lane) ? "Sound off. Click to turn it on" : "Mute this lane's sound", () => toggleMute(lane)),
      laneButton("solo", lane, laneSolo.has(lane), laneSolo.has(lane) ? "Soloed. Click to hear every lane" : "Solo: hear only this lane", () => toggleSolo(lane)),
      laneButton("sound", lane, soundCollapsed(lane), soundCollapsed(lane) ? "Show this lane's sound" : "Hide this lane's sound", () => toggleSoundRow(lane)),
      laneButton("lock", lane, laneLocked(lane), laneLocked(lane) ? "Locked. Click to edit it" : "Lock this lane against edits", () => toggleLock(lane)));
    head.append(name, row);
    return head;
  }));
}

function addVideoLane() {
  const count = laneCount();
  if (count >= LANES.length) return;
  state.project = {...state.project, template: ["full", "split", "three", "four"][count]};
  changed();
  if (preview.on) startPreviewAt(nextTop(-1));
}

function laneAddControls() {
  const controls = document.createElement("div");
  controls.className = "lane-add";
  const videoButton = document.createElement("button");
  videoButton.type = "button";
  videoButton.textContent = "V";
  videoButton.disabled = laneCount() >= LANES.length;
  videoButton.title = videoButton.disabled ? "All four video lanes are visible" : "Add a video lane (updates the split layout)";
  videoButton.setAttribute("aria-label", "Add video lane");
  videoButton.onclick = addVideoLane;
  const audioButton = document.createElement("button");
  audioButton.type = "button";
  audioButton.textContent = "A";
  audioButton.title = "Add audio to the timeline";
  audioButton.setAttribute("aria-label", "Add audio track");
  audioButton.onclick = () => { railShow("music"); $("musicAdd").focus(); };
  controls.append(videoButton, audioButton);
  return controls;
}
