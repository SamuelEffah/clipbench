// Captions timed to the speech. A clip keeps the words Whisper heard as [text, start, end] in seconds from its in point
// (words), the same list as first heard (heard) so edits to the text can be retimed against it, and a style: static
// text, a phrase at a time, or the phrase with the spoken word lit. Keep the grouping in step with phrases_of in make_short.py.
const PHRASE_WORDS = 3, PHRASE_CHARS = 22, PHRASE_GAP = 0.6, HOLD_AFTER = 0.35, MAX_WORDS = 400;
// How a caption can look, in step with LOOKS in make_short.py: size scales the base text, outline is the border as a
// fraction of the text size (the padding of the box), upper shows capitals.
const CAP_LOOKS = {
  classic: {label: "Classic", hint: "Bold white with a black outline", font: "Arial,Helvetica,sans-serif", weight: "bold", size: 1, outline: 0.06, box: false, shadow: false, upper: false, fill: "FFFFFF", edge: "000000"},
  impact: {label: "Impact", hint: "Heavy capitals, thick outline", font: "Impact,Arial,sans-serif", weight: "normal", size: 1.15, outline: 0.08, box: false, shadow: false, upper: true, fill: "FFFFFF", edge: "000000"},
  box: {label: "Box", hint: "White on a dark box", font: "Arial,Helvetica,sans-serif", weight: "bold", size: 0.9, outline: 0.2, box: true, shadow: false, upper: false, fill: "FFFFFF", edge: "000000"},
  clean: {label: "Clean", hint: "Thin outline with a soft shadow", font: "Arial,Helvetica,sans-serif", weight: "bold", size: 1, outline: 0.03, box: false, shadow: true, upper: false, fill: "FFFFFF", edge: "000000"},
  pop: {label: "Pop", hint: "Bold white capitals with a spoken-word highlight", font: "'Arial Black',Arial,sans-serif", weight: "normal", size: 1.5, outline: 0.065, box: false, shadow: false, upper: true, fill: "FFFFFF", edge: "000000"},
  marker: {label: "Marker", hint: "Dark text on a yellow highlighter box", font: "Arial,Helvetica,sans-serif", weight: "bold", size: 0.9, outline: 0.2, box: true, shadow: false, upper: false, fill: "111111", edge: "FFD84A"},
  stamp: {label: "Stamp", hint: "White capitals on a red box", font: "Impact,Arial,sans-serif", weight: "normal", size: 1.05, outline: 0.18, box: true, shadow: false, upper: true, fill: "FFFFFF", edge: "E5322D"},
  neon: {label: "Neon", hint: "Cyan rounded text, deep blue outline", font: "'Arial Rounded MT Bold',Arial,sans-serif", weight: "normal", size: 1, outline: 0.09, box: false, shadow: true, upper: false, fill: "7DF9FF", edge: "10206B"},
  bubble: {label: "Bubble", hint: "White rounded text, thick purple outline", font: "'Arial Rounded MT Bold',Arial,sans-serif", weight: "normal", size: 1, outline: 0.15, box: false, shadow: false, upper: false, fill: "FFFFFF", edge: "6A35E0"},
  cinema: {label: "Cinema", hint: "Small serif, film subtitle", font: "Georgia,serif", weight: "normal", size: 0.85, outline: 0.03, box: false, shadow: true, upper: false, fill: "FFFFFF", edge: "000000"},
};
const HIGHLIGHTS = [["FFD84A", "Yellow"], ["5CE08A", "Green"], ["FF6FAE", "Pink"], ["5CC8FF", "Blue"], ["FF9A3C", "Orange"]];
const DEFAULT_LOOK = "classic", DEFAULT_HIGHLIGHT = "FFD84A";
const capModeOf = c => (c && c.capMode) || "text";
const isSynced = c => capModeOf(c) !== "text" && Boolean(c.words && c.words.length);
let speechTask = "translate";

function phrasesOf(words) {
  const groups = [];
  let current = [];
  for (const word of words) {
    if (current.length) {
      const last = current[current.length - 1];
      const chars = current.reduce((n, w) => n + w[0].length + 1, 0) + word[0].length;
      if (current.length >= PHRASE_WORDS || chars > PHRASE_CHARS || word[1] - last[2] > PHRASE_GAP || /[.,;:!?]$/.test(last[0])) {
        groups.push(current);
        current = [];
      }
    }
    current.push(word);
  }
  if (current.length) groups.push(current);
  return groups;
}

// Word times are measured from the in point they were timed at (wordsIn). When the clip is trimmed, the same speech sits at
// a different offset, so shift the times rather than re-listening. Words trimmed off the front go negative and are kept, so
// trimming back restores them.
function aligned(c) {
  if (!c.words || !c.words.length || c.wordsIn === undefined || Math.abs(c.wordsIn - c.in) < 1e-6) return c;
  const shift = c.wordsIn - c.in, move = list => list && list.map(([t, a, b]) => [t, Number((a + shift).toFixed(3)), Number((b + shift).toFixed(3))]);
  return {...c, words: move(c.words), heard: move(c.heard), wordsIn: c.in};
}

// True when the clip now reaches earlier or later than the stretch that was timed, so some of it has no caption.
function uncovered(c) {
  if (!c.words || !c.words.length || c.wordsIn === undefined || c.wordsLen === undefined) return false;
  return c.in < c.wordsIn - 0.1 || c.out > c.wordsIn + c.wordsLen + 0.1;
}

// The caption text for what the clip still holds, so a split or trim leaves each clip with its own words.
function spokenText(c) {
  const a = aligned(c), span = a.out - a.in;
  return a.words.filter(w => w[2] > 0 && w[1] < span).map(w => w[0]).join(" ");
}

// The on-screen cues for a clip, in seconds into the clip as the Short plays it. Cached per clip object.
const cueCache = new WeakMap(), orderedCueLists = new WeakSet();
function syncedCues(clip) {
  if (cueCache.has(clip)) return cueCache.get(clip);
  const c = aligned(clip);
  const span = c.out - c.in, length = outLen(c);
  const marks = c.words.filter(w => w[2] > 0 && w[1] < span).map(([t, a, b]) => [t, outTimeAt(c, c.in + Math.max(a, 0)), outTimeAt(c, c.in + Math.min(b, span))]);
  const steps = [];
  for (const group of phrasesOf(marks)) {
    const texts = group.map(w => w[0]);
    if (capModeOf(c) === "phrase") steps.push({a: group[0][1], b: group[group.length - 1][2], words: texts, lit: -1});
    else group.forEach((w, n) => steps.push({a: w[1], b: n + 1 < group.length ? group[n + 1][1] : w[2], words: texts, lit: n}));
  }
  const cues = steps.map((q, n) => ({...q, b: Math.max(q.b, Math.min(q.b + HOLD_AFTER, n + 1 < steps.length ? steps[n + 1].a : length))}));
  // Binary lookup is safe only for finite, ordered cues without overlaps.
  if (cues.every((q, n) => Number.isFinite(q.a) && Number.isFinite(q.b) && q.a <= q.b && (!n || cues[n - 1].b <= q.a))) orderedCueLists.add(cues);
  cueCache.set(clip, cues);
  return cues;
}

// What shows over the clip at `pos` seconds in. While paused between phrases the nearest one stays up so it can be dragged.
function captionAt(c, pos, live) {
  if (!c) return null;
  if (!isSynced(c)) { const text = captionOf(c); return text ? {key: `s:${text}`, words: [text], lit: -1} : null; }
  const cues = syncedCues(c);
  let cue, preceding;
  if (orderedCueLists.has(cues) && Number.isFinite(pos)) {
    let lo = 0, hi = cues.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (cues[mid].a <= pos) lo = mid + 1; else hi = mid;
    }
    const nearest = cues[lo - 1];
    if (nearest && pos < nearest.b) cue = nearest;
    if (!live) preceding = nearest;
  } else for (const q of cues) {
    if (pos >= q.a && pos < q.b) { cue = q; break; }
    if (!live && q.a <= pos) preceding = q;
  }
  if (!cue && !live) cue = preceding || cues[0];
  return cue ? {...cue, key: `${cue.words.join(" ")}|${cue.lit}`} : null;
}

// A plain caption carries on over the top-lane clips after it that have none of their own, until a clip stops it (capStop).
// Keep in step with export_cuts in clipper.py.
function captionOf(c) {
  if (c.caption || !isTop(c) || c.capStop) return c.caption || "";
  const clips = state.project.clips, cached = captionOf.carryCache;
  // Edits replace the clip list. Reuse the active clip's carry between preview frames.
  if (cached && cached.clips === clips && cached.clip === c) return cached.text;
  let text = "";
  for (let i = clips.indexOf(c) - 1; i >= 0; i--) {
    const p = clips[i];
    if (!isTop(p)) continue;
    if (p.caption) { text = isSynced(p) ? "" : p.caption; break; }
    if (p.capStop) break;
  }
  captionOf.carryCache = {clips, clip: c, text};
  return text;
}

function paintCaption(el, cap) {
  const key = cap ? cap.key : "";
  if (el.dataset.cap === key) return;
  el.dataset.cap = key;
  if (!cap || cap.lit < 0) {
    el._captionWords = null;
    el._captionSpans = null;
    el._captionLit = -1;
    el.textContent = cap ? cap.words.join(" ") : "";
    return;
  }
  const samePhrase = el._captionWords && el._captionWords.length === cap.words.length && cap.words.every((word, i) => word === el._captionWords[i]);
  if (!samePhrase) {
    el._captionWords = [...cap.words];
    el._captionSpans = cap.words.map(word => {
      const span = document.createElement("span");
      span.textContent = word;
      span.className = "caption-word";
      return span;
    });
    el.replaceChildren(...el._captionSpans.flatMap((span, i) => i ? [" ", span] : [span]));
    el._captionLit = -1;
  }
  if (el._captionLit !== cap.lit) {
    const previous = el._captionSpans[el._captionLit];
    if (previous) previous.className = "caption-word";
    const current = el._captionSpans[cap.lit];
    if (current) current.className = "caption-word lit";
    el._captionLit = cap.lit;
  }
}

// New text for a synced caption keeps the heard timings: the same word count maps one to one, otherwise the words
// spread over the speech by length.
function retime(words, text) {
  const next = text.split(/\s+/).filter(Boolean).slice(0, MAX_WORDS).map(w => w.slice(0, 40));
  if (!next.length || !words.length) return [];
  if (next.length === words.length) return words.map((w, n) => [next[n], w[1], w[2]]);
  const a = words[0][1], b = words[words.length - 1][2];
  const weights = next.map(w => w.length + 1), sum = weights.reduce((x, y) => x + y, 0);
  let at = a;
  return next.map((w, n) => {
    const from = at;
    at += (b - a) * weights[n] / sum;
    return [w, Number(from.toFixed(2)), Number(at.toFixed(2))];
  });
}

const sameClip = (a, b) => a.src === b.src && a.in === b.in && a.out === b.out;

async function syncSpeech(i, mode, note) {
  const c = state.project.clips[i], project = state.project.name;
  note.textContent = "Listening";
  try {
    let job = await api("/api/transcribe", "POST", {src: c.src, in: c.in, out: c.out, timed: true, task: speechTask});
    while (job.state === "working") {
      note.textContent = job.message;
      await new Promise(r => setTimeout(r, 1000));
      job = await api(`/api/transcribe/${job.id}`);
    }
    if (job.state !== "done") throw new Error(job.message || "Couldn't time the speech");
    const at = state.project.name === project ? state.project.clips.findIndex(x => sameClip(x, c)) : -1;
    if (at < 0) throw new Error("That clip changed while listening, so the timing wasn't added");
    setClipField(at, {words: job.words, heard: job.words, wordsIn: c.in, wordsLen: c.out - c.in, caption: job.text, capMode: mode === "text" ? "phrase" : mode});
    toast(`Timed ${job.words.length} words. Edit the text to fix any`);
  } catch (err) {
    toast(err.message);
    renderDetails();
  }
}

// A clip added to the top lane is captioned from the subtitles that came with its video, timed word by word. A video with
// no subtitles is left alone rather than guessed at; Suggest and the caption styles still listen for those.
async function captionFromSubtitles(clip) {
  const project = state.project.name;
  if (!inShort() || !isTop(clip) || clip.caption || clip.capStop) return;
  const stillThere = x => sameClip(x, clip) && isTop(x) && !x.caption;
  try {
    let job = await api("/api/transcribe", "POST", {src: clip.src, in: clip.in, out: clip.out, timed: true, task: "translate", subtitles: true});
    while (job.state === "working") {
      await new Promise(r => setTimeout(r, 500));
      job = await api(`/api/transcribe/${job.id}`);
    }
    if (job.state === "none") return;
    if (job.state !== "done") throw new Error(job.message || "Couldn't caption the clip from its subtitles");
    const at = state.project.name === project ? state.project.clips.findIndex(stillThere) : -1;
    if (at < 0) return;
    setClipField(at, {words: job.words, heard: job.words, wordsIn: clip.in, wordsLen: clip.out - clip.in, caption: job.text, capMode: "word"});
  } catch (err) {
    toast(err.message);
  }
}

// A dropdown for one choice from a few. options are [value, text, hint, colour?]; onPick gets the chosen value.
function pickRow(label, current, options, onPick) {
  const sel = document.createElement("select");
  sel.className = "menu";
  sel.setAttribute("aria-label", label);
  for (const [value, text, hint, colour] of options) {
    const o = document.createElement("option");
    o.value = value;
    o.textContent = text;
    o.title = hint;
    o.selected = current === value;
    if (colour) o.style.color = colour;
    sel.appendChild(o);
  }
  const shown = options.find(o => o[0] === current);
  if (shown && shown[3]) sel.style.color = shown[3];
  sel.title = (options.find(o => o[0] === current) || [])[2] || "";
  sel.onchange = () => onPick(sel.value, sel);
  return sel;
}

// The look rows: the typeface and box, and for the word style the colour of the word being said.
function lookRows(i) {
  const c = state.project.clips[i], st = capStyleOf(c);
  const rows = [numberRow("Look", pickRow(`Caption look for clip ${i + 1}`, st.look, Object.entries(CAP_LOOKS).map(([k, l]) => [k, l.label, l.hint]),
    value => styleCaption(i, {capLook: value}, `look:${i}`, false)))];
  if (capModeOf(c) === "word") {
    const pick = pickRow(`Highlight colour for clip ${i + 1}`, st.hi, HIGHLIGHTS.map(([hex, name]) => [hex, `\u25CF ${name}`, name, `#${hex}`]),
      value => styleCaption(i, {capHi: value}, `hi:${i}`, false));
    rows.push(numberRow("Highlight", pick));
  }
  return rows;
}

// The Caption section's rows below the text box: how the caption shows, which language, and the timing.
function syncRows(i) {
  const c = state.project.clips[i], mode = capModeOf(c), timed = Boolean(c.words && c.words.length);
  const note = document.createElement("small");
  note.className = "syncnote num";
  note.textContent = !timed ? "Not timed yet" : uncovered(c) ? "Trimmed past the timed speech. Time again to caption all of it" : `${c.words.length} words timed to the speech`;
  const style = pickRow(`Caption style for clip ${i + 1}`, mode, [
    ["text", "Static", "One caption for the whole clip"],
    ["phrase", "Phrases", "A few words at a time, as they are said"],
    ["word", "Words", "The word being said lights up"]], value => {
    if (value === "text" || timed) return setClipField(i, {capMode: value});
    style.disabled = true;
    syncSpeech(i, value, note);
  });
  const lang = pickRow("Language of the captions", speechTask, [
    ["translate", "English", "Translate what is said into English"],
    ["transcribe", "Original", "Keep the language that is spoken"]], value => { speechTask = value; });
  const again = document.createElement("button");
  again.type = "button";
  again.className = "mini";
  again.textContent = timed ? "Time again" : "Time to speech";
  again.title = "Listen to this clip and time each word to what is said";
  again.onclick = () => { again.disabled = true; syncSpeech(i, mode, note); };
  return [numberRow("Style", style), numberRow("Speech", lang), numberRow("Timing", again), note];
}
