// The Text tool in the rail: caption styles to click or drag onto the preview. Dropping one sets the look of the clip
// being shown and puts its caption where it landed. A clip with no caption is captioned from its speech. Depends on app.js (state, preview, setClipField, capStyleOf, toast, $),
// captions.js (CAP_LOOKS) and short.js (inShort, captionRuns).
const TEXT_DRAG = "application/x-caption-look";
const TEXT_EDGE = {x: [0.05, 0.95], y: [0.02, 0.98]};

const clampTo = (v, [lo, hi]) => Math.min(hi, Math.max(lo, v));
const textClip = () => state.project.clips[preview.on ? preview.idx : state.sel];

// Where a pointer is in the frame, 0 to 1, kept clear of the edges and snapped to the middle line like a caption drag.
function framePoint(e) {
  const r = $("card1080").getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
  const snapped = Math.abs(x - 0.5) < 0.03 ? 0.5 : x;
  return {x: Number(clampTo(snapped, TEXT_EDGE.x).toFixed(4)), y: Number(clampTo(y, TEXT_EDGE.y).toFixed(4))};
}

let listening = false;
let newCaptionMode = "word";
const CAPTION_MODES = [["word", "Words", "The word being said lights up"], ["phrase", "Phrases", "A few words at a time, as they are said"], ["text", "Static", "One caption for the whole clip"]];

// A clip with no caption gets one from what is said, timed so each word lights up as it is spoken.
async function autoCaption(i) {
  if (listening) return;
  listening = true;
  const progress = {set textContent(text) { toast(text); }};
  try {
    await syncSpeech(i, newCaptionMode === "text" ? "phrase" : newCaptionMode, progress);
    if (newCaptionMode === "text") setClipField(i, {capMode: "text"});
  } finally {
    listening = false;
  }
}

function applyTextStyle(look, point) {
  const i = state.project.clips.indexOf(textClip());
  if (i < 0 || !isTop(state.project.clips[i])) return toast("Select a clip in the top lane first");
  const clip = state.project.clips[i];
  const patch = {capLook: look, ...(point ? {capX: point.x, capY: point.y} : {})};
  styleCaption(i, patch, `text:${i}`, false);
  if (captionOf(clip)) return toast(`${CAP_LOOKS[look].label} caption${point ? " placed" : ""}`);
  autoCaption(i);
}

// Caption runs already resolve stops and speech-timed captions in one forward pass.
function captionModeTargets(clips, here, all) {
  if (!all) return here >= 0 && isTop(clips[here]) && captionOf(clips[here]) ? [here] : [];
  const targets = [];
  for (const {head, last} of captionRuns(clips)) {
    for (let n = head; n <= last; n++) if (isTop(clips[n])) targets.push(n);
  }
  return targets;
}

async function applyCaptionMode(mode) {
  newCaptionMode = mode;
  const clips = state.project.clips, here = clips.indexOf(textClip()), all = $("textModeAllBox").checked;
  const targets = captionModeTargets(clips, here, all);
  const ready = n => mode === "text" || (clips[n].words && clips[n].words.length);
  const now = new Set(targets.filter(ready));
  if (now.size) {
    state.project = {...state.project, clips: clips.map((c, n) => (now.has(n) ? {...c, capMode: mode} : c))};
    changed(false, `capmode:${mode}`);
  }
  for (const n of targets.filter(n => !ready(n))) await autoCaption(n);
}

function applyWordColour(hex) {
  const i = state.project.clips.indexOf(textClip());
  if (i < 0 || !isTop(state.project.clips[i])) return toast("Select a clip in the top lane first");
  styleCaption(i, {capHi: hex}, `hi:${i}`, false);
}

// How captions show, set here so a style dropped on a clip need not start as the word-by-word one.
function paintCaptionMode(c) {
  const row = $("textMode"), label = document.createElement("span");
  label.textContent = "Caption mode";
  row.hidden = !c || !isTop(c);
  const now = c && captionOf(c) ? capModeOf(c) : newCaptionMode;
  row.replaceChildren(label, pickRow("How captions show", now, CAPTION_MODES, applyCaptionMode));
}

// The colour the spoken word lights up in, whatever the look. Shown beside the looks so Neon can keep a cyan caption with a pink word.
function paintWordColour(c) {
  const row = $("textHi"), now = c ? capStyleOf(c).hi : null, label = document.createElement("span");
  label.textContent = "Word colour";
  row.hidden = !c || !isTop(c);
  row.replaceChildren(label, ...HIGHLIGHTS.map(([hex, name]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "hidot";
    b.style.setProperty("--dot", `#${hex}`);
    b.title = name;
    b.setAttribute("aria-label", name);
    b.setAttribute("aria-pressed", hex === now);
    b.onclick = () => applyWordColour(hex);
    return b;
  }));
}

function paintText() {
  const c = textClip(), now = c ? capStyleOf(c).look : null;
  $("textNote").textContent = c && isTop(c) ? "Click a style to use it, or drag it onto the preview to place the caption." : "Select a clip in the top lane to style its caption.";
  paintCaptionMode(c);
  paintWordColour(c);
  let captions = 0;
  const several = state.project.clips.some(x => isTop(x) && x.caption && ++captions > 1);
  $("textSame").hidden = !several;
  $("textModeAll").hidden = !several;
  $("textSameBox").checked = !capsApart();
  $("textGrid").replaceChildren(...Object.entries(CAP_LOOKS).map(([id, look]) => {
    const b = document.createElement("button");
    b.className = "tt tx";
    b.draggable = true;
    b.setAttribute("aria-pressed", id === now);
    b.title = look.hint;
    b.innerHTML = `<i class="tv"><em class="sample ${id}">Aa</em></i><span>${look.label}</span>`;
    b.onclick = () => applyTextStyle(id);
    b.ondragstart = e => {
      e.dataTransfer.setData(TEXT_DRAG, id);
      e.dataTransfer.effectAllowed = "copy";
      $("card1080").classList.add("textdrop");
    };
    b.ondragend = () => $("card1080").classList.remove("textdrop");
    return b;
  }));
}

const card = $("card1080");
const isTextDrag = e => Array.from(e.dataTransfer ? e.dataTransfer.types : []).includes(TEXT_DRAG);
card.addEventListener("dragover", e => {
  if (!isTextDrag(e)) return;
  e.preventDefault();
  e.dataTransfer.dropEffect = "copy";
});
card.addEventListener("drop", e => {
  if (!isTextDrag(e)) return;
  e.preventDefault();
  card.classList.remove("textdrop");
  const look = e.dataTransfer.getData(TEXT_DRAG);
  if (CAP_LOOKS[look]) applyTextStyle(look, framePoint(e));
});

$("textSameBox").onchange = e => {
  if (e.target.checked) captionsToFirstPosition();
  else e.target.checked = true;
};
