// Live captions: the caption of the clip that is playing, beside the Short preview, as one block of text that scrolls so the
// phrase on screen stays in view and is the only part lit. Click a word to jump there, or press Edit to type. Switched on and off from the Settings panel.
// Depends on app.js (state, setCaptionAt, updatePreview, togglePreview, video) and captions.js (syncedCues, isSynced).
const LIVECAP_KEY = "clipbench.liveCaptions";

function liveCapOn() {
  try { return localStorage.getItem(LIVECAP_KEY) !== "0"; } catch { return true; }
}

// The words of a timed clip in order, and for every cue where its phrase sits in them.
const liveWordCache = new WeakMap();
function liveWordsOf(clip) {
  if (liveWordCache.has(clip)) return liveWordCache.get(clip);
  const texts = [], ranges = [], src = [];
  const a = aligned(clip), span = a.out - a.in;
  for (const w of a.words) if (w[2] > 0 && w[1] < span) src.push(a.in + Math.max(w[1], 0));
  let start = 0;
  for (const q of syncedCues(clip)) {
    if (q.lit <= 0) { start = texts.length; texts.push(...q.words); }
    ranges.push({a: q.a, start, len: q.words.length, lit: q.lit});
  }
  const out = {texts, ranges, src};
  liveWordCache.set(clip, out);
  return out;
}

let liveCapKey = "", liveCueKey = "", liveWordEls = [], liveEditing = false, liveIdx = 0;

function buildLiveFlow(clip, synced, text) {
  const flow = $("lcFlow");
  let nodes;
  if (!text) nodes = [Object.assign(document.createElement("span"), {className: "lw hint", textContent: "No caption on this clip. Click to type one."})];
  else if (!synced) nodes = [Object.assign(document.createElement("span"), {className: "lw win", textContent: text})];
  else nodes = liveWordsOf(clip).texts.flatMap((w, n) => {
    const el = Object.assign(document.createElement("span"), {className: isSynced(clip) ? "lw" : "lw win", textContent: w});
    el.dataset.src = liveWordsOf(clip).src[n];
    el.dataset.word = n;
    return n ? [" ", el] : [el];
  });
  flow.replaceChildren(...nodes);
  liveWordEls = flow.querySelectorAll(".lw");
}

function lightLiveCue(clip, cap) {
  const words = liveWordEls, flow = $("lcFlow"), box = $("lcScroll");
  const r = cap ? liveWordsOf(clip).ranges.find(x => x.a === cap.a) : null;
  const end = r ? r.start + r.len : 0, now = r && r.lit >= 0 ? r.start + r.lit : -1;
  const previous = lightLiveCue.previous;
  const paint = n => {
    if (n < 0 || n >= words.length) return;
    const value = `lw${r ? (n >= r.start && n < end ? (n === now ? " win now" : " win") : n < r.start ? " before" : "") : ""}`;
    if (words[n].className !== value) words[n].className = value;
  };
  if (previous && previous.words === words) {
    if (previous.start === (r ? r.start : 0) && previous.end === end) {
      paint(previous.now);
      paint(now);
    } else {
      for (let n = Math.min(previous.start, r ? r.start : 0); n < Math.max(previous.end, end); n++) paint(n);
    }
  } else words.forEach((_, n) => paint(n));
  lightLiveCue.previous = {words, start: r ? r.start : 0, end, now};
  const y = r && words[r.start] ? words[r.start].offsetTop - box.clientHeight * 0.34 : 0;
  liveAutoY = Math.max(0, Math.round(y));
  applyLiveScroll();
}

// Wheel over the caption to read ahead or back. A second after the last tick it eases back to the phrase being said.
let liveAutoY = 0, liveManual = 0, liveSnapBack = 0;
function applyLiveScroll() {
  const flow = $("lcFlow"), room = Math.max(0, flow.offsetHeight + 56 - $("lcScroll").clientHeight);
  const y = Math.min(Math.max(room, liveAutoY), Math.max(0, liveAutoY + liveManual));
  liveManual = y - liveAutoY;
  flow.style.transform = `translateY(${-y}px)`;
  positionTranscriptAction();
}

function paintLiveCap(clip, idx, cap) {
  const box = $("liveCap"), show = Boolean(clip) && state.mode === "short" && liveCapOn();
  if (box.hidden === show) box.hidden = !show;
  if (!show) return;
  const synced = isSynced(clip), text = clip.caption || "", key = `${idx}|${synced}|${text}`;
  const rebuilt = key !== liveCapKey;
  if (rebuilt) {
    liveCapKey = key;
    liveAutoY = liveManual = 0;
    const field = $("lcText");
    $("lcMeta").textContent = `Clip ${idx + 1}`;
    field.dataset.at = idx;
    liveIdx = idx;
    if (document.activeElement !== field) field.value = text;
    buildLiveFlow(clip, Boolean(clip.words?.length), text);
  }
  if (!synced || !text) return;
  const cueKey = cap ? `${cap.a}|${cap.key}` : "";
  if (rebuilt || cueKey !== liveCueKey) {
    liveCueKey = cueKey;
    lightLiveCue(clip, cap);
  }
}

function showLiveCount() {
  const n = $("lcText").value.length;
  $("lcCount").textContent = `${n} character${n === 1 ? "" : "s"}`;
}

function editLiveCaption(on) {
  liveEditing = on;
  const field = $("lcText");
  $("lcScroll").hidden = on;
  field.hidden = !on;
  $("lcEdit").hidden = on;
  $("lcCount").hidden = !on;
  if (on) {
    showLiveCount();
    if (!video.paused) togglePreview();
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
  }
}

$("lcScroll").onclick = e => {
  const word = e.target.closest && e.target.closest(".lw[data-src]");
  if (window.getSelection()?.toString().trim()) return;
  if (word && preview.on) return startPreviewAt(liveIdx, Number(word.dataset.src));
  editLiveCaption(true);
};
$("lcEdit").onclick = () => editLiveCaption(true);
$("lcScroll").addEventListener("wheel", e => {
  e.preventDefault();
  liveManual += e.deltaY;
  applyLiveScroll();
  clearTimeout(liveSnapBack);
  liveSnapBack = setTimeout(() => { liveManual = 0; applyLiveScroll(); }, 1000);
}, {passive: false});

// Double-click a word to retype just that word. Falls back to the whole caption when the words and the text don't line up one to one.
function editLiveWord(el) {
  const at = liveIdx, tokens = (state.project.clips[at].caption || "").split(/\s+/).filter(Boolean);
  const n = [...liveWordEls].indexOf(el);
  if (n < 0 || tokens.length !== liveWordEls.length) return editLiveCaption(true);
  if (!video.paused) togglePreview();
  const input = Object.assign(document.createElement("input"), {className: "lwedit", value: tokens[n], size: Math.max(2, tokens[n].length)});
  input.setAttribute("aria-label", `Word ${n + 1} of the caption`);
  const done = save => {
    if (input.dataset.done) return;
    input.dataset.done = "1";
    const word = input.value.trim().replace(/\s+/g, " ");
    liveCapKey = "";
    if (save && word && word !== tokens[n]) setCaptionAt(at, tokens.map((t, i) => (i === n ? word : t)).join(" "), `caption:${at}`);
    render();
  };
  input.oninput = () => { input.size = Math.max(2, input.value.length); };
  input.onkeydown = e => { e.stopPropagation(); if (e.key === "Enter") done(true); else if (e.key === "Escape") done(false); };
  input.onblur = () => done(true);
  el.replaceWith(input);
  input.focus();
  input.select();
}
$("lcScroll").ondblclick = e => {
  const word = e.target.closest && e.target.closest(".lw[data-src]");
  if (word) editLiveWord(word);
};
$("lcScroll").onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); editLiveCaption(true); } };
$("lcText").oninput = e => {
  const field = e.target, at = Number(field.dataset.at);
  setCaptionAt(at, field.value.replace(/\s*\n\s*/g, " "), `caption:${at}`);
  showLiveCount();
  updatePreview();
};
$("lcText").onblur = () => { editLiveCaption(false); liveCapKey = ""; render(); };
$("lcText").onkeydown = e => {
  e.stopPropagation();
  // A caption is one line, so Enter finishes the edit; the field keeps its own keys, select all among them.
  if (e.key === "Enter") e.preventDefault();
  if (e.key === "Enter" || e.key === "Escape") e.target.blur();
};

$("lookLive").checked = liveCapOn();
$("lookLive").onchange = e => {
  try { localStorage.setItem(LIVECAP_KEY, e.target.checked ? "1" : "0"); } catch {}
  $("liveCapSizeRow").hidden = !e.target.checked;
  updatePreview();
};

// Selection uses the original timing, independently of how words are grouped on screen.
function transcriptClip(clip, first, last) {
  const a = aligned(clip), words = (a.words || []).filter(w => w[2] > 0 && w[1] < a.out - a.in);
  if (!Number.isInteger(first) || !Number.isInteger(last) || first < 0 || last < first || !words[last]) return null;
  const start = Math.max(a.in, a.in + words[first][1]), end = Math.min(a.out, a.in + words[last][2]);
  if (!(end > start)) return null;
  return {...a, in: start, out: end, wordsIn: a.in, caption: words.slice(first, last + 1).map(w => w[0]).join(" ")};
}
let transcriptSelection = null;
document.addEventListener("selectionchange", () => {
  const selection = window.getSelection(), flow = $("lcFlow"), clip = state.project.clips[liveIdx];
  const range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
  const valid = range && !selection.isCollapsed && flow.contains(range.startContainer) && flow.contains(range.endContainer);
  const words = valid && clip && clip.words?.length ? [...flow.querySelectorAll("[data-word]")].filter(el => range.intersectsNode(el)) : [];
  transcriptSelection = words.length && clip ? {clip, idx: liveIdx, first: Number(words[0].dataset.word), last: Number(words.at(-1).dataset.word)} : null;
  $("lcClip").hidden = !transcriptSelection;
  if (transcriptSelection && !video.paused) togglePreview();
  positionTranscriptAction();
});
$("lcClip").onpointerdown = e => e.preventDefault();
$("lcClip").onclick = () => {
  const selected = transcriptSelection;
  if (!selected || state.project.clips[selected.idx] !== selected.clip) return;
  const clip = transcriptClip(selected.clip, selected.first, selected.last);
  if (!clip) return toast("Select words with speech timing first");
  // Add to the clip bank, leaving the Short and its existing captions untouched.
  state.project = {...state.project, other: [...(state.project.other || []), clip]};
  window.getSelection().removeAllRanges();
  changed();
  toast("Selection added to Clips");
};

// Keep the action outside the masked text scroller, just above the selected line.
function positionTranscriptAction() {
  const button = $("lcClip"), selection = window.getSelection();
  if (!transcriptSelection || !selection?.rangeCount || selection.isCollapsed || $("liveCap").hidden || liveEditing) {
    button.hidden = true;
    return;
  }
  const panel = $("liveCap").getBoundingClientRect(), scroll = $("lcScroll").getBoundingClientRect();
  const rects = [...selection.getRangeAt(0).getClientRects()].filter(r => r.width > 0 && r.bottom > scroll.top + 24 && r.top < scroll.bottom - 24);
  const rect = rects[0];
  button.hidden = !rect;
  if (!rect) return;
  const line = rects.filter(r => Math.abs(r.top - rect.top) < 2);
  const left = Math.min(...line.map(r => r.left)), right = Math.max(...line.map(r => r.right));
  const x = (left + right) / 2 - panel.left - button.offsetWidth / 2;
  button.style.left = `${Math.max(0, Math.min(panel.width - button.offsetWidth, x))}px`;
  button.style.top = `${Math.max(0, rect.top - panel.top - button.offsetHeight - 6)}px`;
}
window.addEventListener("resize", positionTranscriptAction);
$("lcFlow").addEventListener("transitionend", positionTranscriptAction);

function setLiveCaptionSize(value, remember = true) {
  const size = Math.min(26, Math.max(12, Math.round(Number(value) || 17)));
  $("liveCap").style.setProperty("--lc-font", `${size}px`);
  $("liveCapSize").value = size;
  if (remember) { try { localStorage.setItem("clipbench.liveCaptionSize", String(size)); } catch {} }
  liveCueKey = "";
  applyLiveScroll();
  positionTranscriptAction();
}
let savedLiveCaptionSize = 17;
try { savedLiveCaptionSize = localStorage.getItem("clipbench.liveCaptionSize") || 17; } catch {}
setLiveCaptionSize(savedLiveCaptionSize, false);
$("liveCapSizeRow").hidden = !liveCapOn();
$("liveCapSize").onchange = e => setLiveCaptionSize(e.target.value);
