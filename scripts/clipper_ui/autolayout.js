// Auto: look at the clips and set up the Short: layout and crops that suit them, sound, length and captions.
// Depends on rail.js (the layout controls it sits beside), app.js (state, changed, api, toast, LANES, isTop, canvasOf, outLen), captions.js (captionFromSubtitles, sameClip, speechTask, setClipField), reframe.js (cellOf, pictureIn, reframeFor, clamp01) and tighten.js (cutPauses, pausesFor).
const autoBusy = {on: false};
const MAX_AUTO_ZOOM = 4;

// The framing that fills a clip's cell with a rectangle of the picture (fractions of the frame), such as a streamer's webcam.
function rectFor(clip, rect, size, cell) {
  const filled = {...clip, fit: "fill"};
  const flat = pictureIn(filled, size, cell, 0.5);
  const c = {x: rect.x + rect.w / 2, y: rect.y + rect.h / 2};
  const zoom = Math.min(MAX_AUTO_ZOOM, Math.ceil(Math.max(1, flat.W / (rect.w * flat.w), flat.H / (rect.h * flat.h)) * 100) / 100);
  const wide = Math.abs(flat.W - flat.w) >= Math.abs(flat.H - flat.h);
  const pan = clamp01(wide ? (flat.W / 2 - c.x * flat.w) / (flat.W - flat.w || 1) : (flat.H / 2 - c.y * flat.h) / (flat.H - flat.h || 1));
  const out = {fit: "fill", pan: Number(pan.toFixed(3)), zoom, zx: 0.5, zy: 0.5, track: [], tracking: false};
  if (zoom === 1) return out;
  const pic = pictureIn(filled, size, cell, pan);
  const fx = pic.x + c.x * pic.w, fy = pic.y + c.y * pic.h;
  out.zx = Number(clamp01((fx - pic.W / (2 * zoom)) / (pic.W - pic.W / zoom)).toFixed(3));
  out.zy = Number(clamp01((fy - pic.H / (2 * zoom)) / (pic.H - pic.H / zoom)).toFixed(3));
  return out;
}

// The part of the picture beside a webcam that sits against a side edge: all of the height, and the width the webcam leaves.
// Framing it fills the gameplay lane without the webcam in it.
function besideCam(cam) {
  const left = cam.x + cam.w / 2 < 0.5;
  const x = left ? cam.x + cam.w : 0;
  return {x, y: 0, w: left ? 1 - x : cam.x, h: 1};
}

// What each lane of one clip shows, top first, as framing patches. `found` is the answer of /api/layout.
function lanePlan(clip, found, lanes) {
  const size = [found.width, found.height];
  const cellAt = k => cellOf({...clip, lane: LANES[k]});
  const whole = {fit: "fill", pan: 0.5, zoom: 1, zx: 0.5, zy: 0.5, track: [], tracking: false};
  if (found.layout === "people") {
    return Array.from({length: lanes}, (_, k) => (found.faces[k] ? reframeFor({...clip, fit: "fill"}, found.faces[k], size, cellAt(k)) : whole))
      .map(p => ({...p, fit: "fill", tracking: false}));
  }
  if (found.layout === "webcam") {
    return [rectFor(clip, found.webcam, size, cellAt(0)), ...Array.from({length: lanes - 1}, () => rectFor(clip, besideCam(found.webcam), size, cellAt(1)))];
  }
  if (found.layout === "single") {
    const face = reframeFor({...clip, fit: "fill"}, found.faces[0], size, cellAt(0));
    return [{...face, fit: "fill", tracking: false}, ...Array.from({length: lanes - 1}, () => ({...whole, fit: "fit"}))];
  }
  return Array.from({length: lanes}, () => ({...whole, fit: "fit"}));
}

// One template for the whole Short: stacked lanes when most of its running time wants them, else a single full frame.
function templateFor(pieces) {
  const stacked = pieces.filter(p => p.found.layout === "people" || p.found.layout === "webcam");
  const time = list => list.reduce((sum, p) => sum + (p.clip.out - p.clip.in), 0);
  if (time(stacked) * 2 <= time(pieces)) return "full";
  const most = Math.max(...stacked.map(p => (p.found.layout === "people" ? p.found.faces.length : 2)));
  return most >= 4 ? "four" : most === 3 ? "three" : "split";
}

// How much of the height the webcam lane gets: as much as the webcam's own shape needs, between 30% and 42%, so gameplay keeps the rest.
const CAM_LANE = [0.3, 0.42];
function topShare(pieces, template) {
  const cams = pieces.filter(p => p.found.layout === "webcam");
  if (template !== "split" || !cams.length || cams.length !== pieces.filter(p => p.found.layout !== "none").length) return 0.5;
  const [cw, ch] = canvasOf();
  const {webcam: r, width, height} = cams.reduce((a, b) => (b.clip.out - b.clip.in > a.clip.out - a.clip.in ? b : a)).found;
  const natural = (cw * r.h * height) / (r.w * width) / ch;
  return Number(Math.min(CAM_LANE[1], Math.max(CAM_LANE[0], natural)).toFixed(3));
}

// The longest a Short runs. There is no cap: nothing is dropped or trimmed for length. Set a number to bring the cap back.
const SHORT_MAX = Infinity;
function fitLength(pieces, max = SHORT_MAX, lengthOf = outLen) {
  const kept = [];
  let left = max;
  for (const p of pieces) {
    if (left <= 0.05) break;
    const len = lengthOf(p.clip);
    if (len <= left + 0.01) {
      kept.push(p);
      left -= len;
      continue;
    }
    const ratio = left / len;
    kept.push({...p, clip: {...p.clip, out: Number((p.clip.in + (p.clip.out - p.clip.in) * ratio).toFixed(2))}});
    break;
  }
  return kept;
}

// A clip cut where its shots call for different layouts: one piece per stretch, the first keeping the caption.
function piecesOf(clip, found) {
  const stretches = found.segments && found.segments.length ? found.segments : [{...found, start: clip.in, end: clip.out}];
  return stretches.map((s, n) => ({clip: {...clip, in: s.start, out: s.end, ...(n ? {caption: "", words: null} : {})}, found: {...found, ...s}}));
}

// The companion lanes this tool made earlier: a lane clip repeating a top clip's source and range.
const isCompanion = (c, tops) => !isTop(c) && tops.some(t => t.src === c.src && t.in === c.in && t.out === c.out);

// Top clips that run on from one another in the same video are looked at as one span, so the crop does not change at their seam.
const TOUCH = 0.05;
const SPAN_MAX = 180;  // the longest range /api/layout looks at
function spansOf(tops) {
  const spans = [];
  for (const c of tops) {
    const last = spans[spans.length - 1];
    const joins = last && last.src === c.src && Math.abs(c.in - last.out) <= TOUCH && c.out - last.in <= SPAN_MAX;
    if (joins) spans[spans.length - 1] = {...last, out: c.out, clips: [...last.clips, c]};
    else spans.push({src: c.src, in: c.in, out: c.out, clips: [c]});
  }
  return spans;
}

// The server remembers a cam found from its border for the rest of the stream, so a span looked at before that cam turned up is asked again:
// its own clip may show the cam with nobody in it. `ask` is the call for one span; returns the answers, in place of the ones asked again.
async function askAgain(spans, answers, ask) {
  const ownCam = a => a.layout === "webcam" && !a.guessed;
  const first = answers.findIndex(a => ownCam(a) && !a.remembered);
  if (first <= 0) return answers;
  const redone = [];
  for (const [n, span] of spans.slice(0, first).entries()) redone.push(ownCam(answers[n]) ? answers[n] : await ask(span));
  return [...redone, ...answers.slice(first)];
}

// A cam only guessed from its face (no border showed, as on a dark menu) takes the border-found cam of another clip of the same stream when that
// cam holds the face: a streamer's cam does not move between clips.
function adoptCam(found, others) {
  if (found.layout !== "webcam" || !found.guessed) return found;
  const face = found.faces && found.faces[0];
  const holds = r => Boolean(r && face) && face.x >= r.x && face.x <= r.x + r.w && face.y >= r.y && face.y <= r.y + r.h;
  const other = others.find(o => o !== found && o.layout === "webcam" && !o.guessed && o.width === found.width && o.height === found.height && holds(o.webcam));
  if (!other) return found;
  const swap = s => (s.layout === "webcam" && s.guessed ? {...s, webcam: other.webcam, guessed: false} : s);
  return {...swap(found), segments: (found.segments || []).map(swap)};
}

// A span's answer cut down to one of its clips: the stretches inside the clip, the longest of them describing the whole.
function foundFor(clip, found) {
  const cut = (found.segments || []).map(s => ({...s, start: Math.max(s.start, clip.in), end: Math.min(s.end, clip.out)})).filter(s => s.end - s.start > TOUCH);
  if (!cut.length) return found;
  // A sliver dropped at either end is folded into its neighbour, so the pieces still cover the whole clip.
  const inside = cut.map((s, n) => ({...s, start: n ? s.start : clip.in, end: n < cut.length - 1 ? s.end : clip.out}));
  const longest = inside.reduce((a, b) => (b.end - b.start > a.end - a.start ? b : a));
  const {start, end, ...describes} = longest;
  return {...found, ...describes, segments: inside};
}

// The crop of one person follows them: the face /api/reframe saw over time, framed the way the Reframe panel frames it. Null when no face was seen.
function followedPlan(clip, found, cell) {
  if (!found || !found.found) return null;
  const patch = reframeFor({...clip, fit: "fill"}, found.face, [found.width, found.height], cell, found.track || []);
  return {...patch, fit: "fill", tracking: patch.track.length > 1};
}

// Follow the person in each top clip that Auto framed as a single person. Returns how many clips are now tracking.
async function followSingles(singles) {
  let following = 0;
  for (const clip of singles) {
    const at = () => state.project.clips.findIndex(x => sameClip(x, clip) && isTop(x));
    if (at() < 0) continue;
    const found = await api("/api/reframe", "POST", {src: clip.src, in: clip.in, out: clip.out});
    const plan = followedPlan(clip, found, cellOf(state.project.clips[at()]));
    const i = at();
    if (!plan || i < 0) continue;
    state.project = {...state.project, clips: state.project.clips.map((c, n) => (n === i ? {...c, ...plan} : c))};
    if (plan.tracking) following++;
  }
  if (following) changed(false, `autolayout-follow:${Date.now()}`);
  return following;
}

// Captions for a top-lane clip: from its video's subtitles when it has them, else from listening to the speech. Returns whether it got any.
async function autoCaption(clip) {
  await captionFromSubtitles(clip);
  const now = () => state.project.clips.find(x => sameClip(x, clip) && isTop(x));
  if (!now() || now().caption) return Boolean(now());
  let job = await api("/api/transcribe", "POST", {src: clip.src, in: clip.in, out: clip.out, timed: true, task: speechTask});
  while (job.state === "working") {
    await new Promise(r => setTimeout(r, 1000));
    job = await api(`/api/transcribe/${job.id}`);
  }
  const at = state.project.clips.findIndex(x => sameClip(x, clip) && isTop(x) && !x.caption);
  if (job.state !== "done" || !job.words || !job.words.length || at < 0) return false;
  setClipField(at, {words: job.words, heard: job.words, wordsIn: clip.in, wordsLen: clip.out - clip.in, caption: job.text, capMode: "word"});
  return true;
}

async function autoLayout() {
  if (autoBusy.on) return;
  const tops = state.project.clips.filter(isTop);
  if (!tops.length) return toast("Add a clip to the timeline first");
  autoBusy.on = true;
  $("autoLayout").disabled = true;
  toast(tops.length > 1 ? `Looking at ${tops.length} clips` : "Looking at the clip");
  try {
    const found = new Map(), spans = spansOf(tops), asked = [];
    const ask = span => api("/api/layout", "POST", {src: span.src, in: span.in, out: span.out});
    for (const span of spans) asked.push(await ask(span));
    const answers = await askAgain(spans, asked, ask);
    spans.forEach((span, n) => span.clips.forEach(c => found.set(c, foundFor(c, adoptCam(answers[n], answers)))));
    const wanted = tops.flatMap(c => piecesOf(c, found.get(c)).map(p => ({...p, from: c})));
    const tight = cutPauses(wanted, await pausesFor(wanted, spans, SHORT_MAX), SHORT_MAX);
    const all = fitLength(tight);
    const pieces = new Map(tops.map(c => [c, all.filter(p => p.from === c)]));
    const template = templateFor(all);
    const lanes = {full: 1, split: 2, three: 3, four: 4}[template];
    state.project = {...state.project, template, rowSplit: topShare(all, template), normalize: true};
    const next = [], singles = [];
    state.project.clips.filter(c => !isCompanion(c, tops)).forEach(c => {
      if (!isTop(c)) return next.push(c);
      pieces.get(c).forEach(({clip, found: f}) => {
        const plan = lanePlan(clip, f, lanes);
        next.push({...clip, ...plan[0], volume: clip.volume || 1});
        if (f.layout === "single") singles.push(next[next.length - 1]);
        for (let k = 1; k < lanes; k++) next.push({...clip, ...plan[k], lane: LANES[k], volume: 0, caption: "", words: null});
      });
    });
    state.project = {...state.project, clips: next};
    changed(false, `autolayout:${Date.now()}`);
    const span = list => list.reduce((sum, p) => sum + p.clip.out - p.clip.in, 0);
    const paused = tight.filter(p => p.pause).length, quiet = span(wanted) - span(tight), trimmed = span(tight) - span(all) > 0.05;
    toast(describeLayout(all, template) + (paused ? `, ${paused} ${paused > 1 ? "pauses" : "pause"} cut (${quiet.toFixed(1)}s)` : "") + (trimmed ? `, trimmed to ${SHORT_MAX}s` : ""));
    if (singles.length) {
      try {
        const following = await followSingles(singles);
        if (following) toast(following > 1 ? `Following the person in ${following} clips` : "Following the person");
      } catch (err) { toast(err.message); }
    }
    const needing = state.project.clips.filter(c => isTop(c) && !c.caption);
    let captioned = 0;
    for (const clip of needing) {
      try { if (await autoCaption(clip)) captioned++; } catch (err) { toast(err.message); }
    }
    if (needing.length) toast(captioned ? `Captions added to ${captioned} ${captioned > 1 ? "clips" : "clip"}` : "No speech to caption");
  } catch (err) {
    toast(err.message || "Could not look at the clip");
  } finally {
    autoBusy.on = false;
    $("autoLayout").disabled = false;
  }
}

function describeLayout(pieces, template) {
  const kinds = new Set(pieces.map(p => p.found.layout));
  const cuts = pieces.filter(p => !p.pause).length - new Set(pieces.map(p => p.from || p)).size;
  const where = cuts > 0 ? `, ${cuts} ${cuts > 1 ? "cuts" : "cut"} where the shots change` : "";
  if (kinds.size === 1 && kinds.has("webcam")) return `Webcam on top, gameplay below${where}`;
  if (kinds.size === 1 && kinds.has("people")) return `${pieces[0].found.faces.length} people, one lane each${where}`;
  if (template === "full" && kinds.has("none") && kinds.size === 1) return "No faces found, so the clip stays whole";
  return template === "full" ? `One person, filled and framed${where}` : `Layout set from what is in each clip${where}`;
}

const autoBtn = document.createElement("button");
autoBtn.className = "dd";
autoBtn.id = "autoLayout";
autoBtn.title = "Auto: look at the clips and set up the Short, with the layout, crops, sound, length and captions";
autoBtn.setAttribute("aria-label", "Auto");
autoBtn.innerHTML = '<svg class="i" viewBox="0 0 24 24"><path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/></svg><span>Auto</span>';
autoBtn.addEventListener("click", autoLayout);
document.querySelector("#theater .pctl").append(autoBtn);
