// Suggest clips: ask the server which stretches of the open video are worth cutting, and list them above the clips. Depends on app.js and review.js (loadReviews, saveReview).
let suggestion = {vid: null, clips: [], model: "", busy: false};

function suggestClip(s, v = state.current) {
  return {src: v.path, in: s.in, out: s.out, note: "", caption: "", speed: 1, volume: 1, fit: "fit", pan: 0.5, effect: "none", ramp: "none", freeze: 0, thumb: `/video-thumb/${v.id}.jpg`};
}

// The clips a suggestion becomes: one, or one per piece of two moments joined with the gap between them cut out.
const suggestPieces = s => s.pieces || [[s.in, s.out]];
const suggestClips = (s, v = state.current) => suggestPieces(s).map(([a, b]) => suggestClip({in: a, out: b}, v));

const suggestAdded = s => Boolean(state.current) && suggestPieces(s).every(([a, b]) =>
  state.project.clips.some(c => c.src === state.current.path && Math.abs(c.in - a) < 0.05 && Math.abs(c.out - b) < 0.05));

function suggestionKey(s) { return `${s.in}:${s.out}`; }
let suggestionReview = new Map();
let suggestionPreview = null;
function addKeptSuggestions() {
  if (!state.current || suggestion.vid !== state.current.id) return;
  const clips = suggestion.clips.filter(s => suggestionReview.get(suggestionKey(s)) === "keep" && !suggestAdded(s)).flatMap(s => suggestClips(s));
  if (!clips.length) return;
  state.project = {...state.project, clips: [...clips, ...state.project.clips]};
  clips.forEach(requestCut);
  state.sel = 0;
  changed();
  paintSuggest();
  toast(`${clips.length} clip${clips.length === 1 ? "" : "s"} added`);
}

// Review ranges are transient: they never become project clips until explicitly added.
function paintSuggestionRange() {
  const strip = $("strip");
  strip.querySelectorAll(".suggestion-range").forEach(el => el.remove());
  if (state.mode !== "clip" || !state.current || suggestion.vid !== state.current.id || $("suggest").hidden) return;
  const moment = suggestion.clips.find(s => suggestionKey(s) === suggestionPreview);
  if (!moment) return;
  suggestPieces(moment).forEach(([a, b], i) => {
    const start = Math.max(a, view.s), end = Math.min(b, view.e);
    if (end <= start) return;
    const range = document.createElement("div");
    range.className = "suggestion-range";
    range.setAttribute("role", "img");
    range.setAttribute("aria-label", `Suggested range ${fmt(a)} to ${fmt(b)}`);
    placeRange(range, {in: start, out: end});
    const label = document.createElement("span");
    label.textContent = moment.pieces ? `Preview · ${i + 1}` : "Preview";
    range.append(label);
    strip.append(range);
  });
}

const PROFILE_NOTE = {speech: "Mostly talk, so wording counts most.", visual: "Mostly picture and few words, so motion and sound count most.", audio: "Little speech, so sound counts most.", mixed: "Talk and picture both, so both count."};
const STEADY_NOTE = "Steady sound, like music, so loudness and the beat count most.";
const profileNote = p => (p && p.steady ? STEADY_NOTE : PROFILE_NOTE[(p || {}).kind] || "");
const partsNote = p => p ? `, <span class="parts" title="How the moment scored out of 100: its opening, its sound, its motion, its wording">hook ${p.hook}, sound ${p.energy}${p.motion === undefined ? "" : `, motion ${p.motion}`}, words ${p.words}</span>` : "";
// What earlier decisions and published Shorts taught about moments like this one, with how far it moved the score.
const learnedNote = l => l && l.note ? `, <span class="learned" title="Moved ${l.delta > 0 ? "up" : "down"} ${Math.abs(l.delta)}% by what you kept and skipped before and by how your Shorts did on YouTube">${esc(l.note)}, ${l.delta > 0 ? "+" : ""}${l.delta}%</span>` : "";

function paintSuggest() {
  const box = $("suggest"), here = state.current && suggestion.vid === state.current.id;
  box.hidden = !here || (!suggestion.clips.length && !suggestion.busy);
  paintSuggestionRange();
  if (box.hidden) return;
  // The model scores one moment at a time, so while it works the list shows what it has scored so far, best first.
  const filling = suggestion.busy && suggestion.clips.length > 0;
  const head = filling ? `${suggestion.clips.length} so far, ${suggestion.pct || 0}% scored` :
    suggestion.busy ? `Looking for clips${suggestion.pct ? `, ${suggestion.pct}%` : ""}` : `${suggestion.clips.length} suggested`;
  const spoken = suggestion.clips.some(s => s.text);
  const basis = filling ? "Scored one moment at a time, best first. The order settles as the rest come in." :
    suggestion.busy ? "Finding complete moments across the transcript and checking scene boundaries." :
    `${spoken ? `Moments up to about a minute, with natural dialogue boundaries. ${suggestion.model ? `${esc(suggestion.model)} ranked a shortlist with surrounding dialogue for setup, payoff and clarity.` : "No local model is running, so there is no score for story. Start Ollama for a smarter pick."}` : "Stretches picked from the sound, the motion and the scene cuts, since little is said."} ${profileNote(suggestion.profile)} Best first.`;
  const rows = suggestion.clips.map((s, i) => {
    const key = suggestionKey(s), added = suggestAdded(s), decision = suggestionReview.get(key);
    const duration = suggestPieces(s).reduce((sum, [a, b]) => sum + b - a, 0);
    const status = added ? "Added to clips" : decision === "keep" ? "Kept" : decision === "skip" ? "Skipped" : `Moment ${i + 1}`;
    const reason = s.why || (s.text ? "Selected from the dialogue and scene boundaries." : "Selected from sound, motion and scene changes.");
    return `<article class="sg sgcard" data-i="${i}" data-decision="${added ? "added" : decision || "pending"}" data-preview="${suggestionPreview === key}" aria-label="Suggested moment ${i + 1}">
      <button class="sgpreview" type="button" aria-label="Preview moment ${i + 1}" aria-pressed="${suggestionPreview === key}"><span class="sgthumb"><img src="/video-thumb/${state.current.id}.jpg" alt="" loading="lazy"><svg class="i"><use href="#c-play"/></svg><span class="sgduration num">${duration.toFixed(0)}s</span></span><span class="sgmeta"><span class="sgstatus">${status}</span><span class="num">${fmt(s.in)} – ${fmt(s.out)}</span></span></button>
      <p class="sgquote">${esc(s.text || "A visual moment. Preview to review the action.")}</p>
      <p class="sgreason">${esc(reason)}${s.pieces ? " · Two moments joined" : ""}</p>
      ${s.parts || s.learned ? `<details class="sgdetails"><summary>Ranking details</summary><div>${partsNote(s.parts).replace(/^, /, "")}${learnedNote(s.learned)}</div></details>` : ""}
      <div class="sgactions"><button type="button" class="sgkeep" aria-label="Keep moment ${i + 1}" aria-pressed="${decision === "keep"}"${added ? " disabled" : ""}>${added ? "Added" : decision === "keep" ? "✓ Kept" : "Keep"}</button><button type="button" class="sgskip" aria-label="Skip moment ${i + 1}" aria-pressed="${decision === "skip"}"${added ? " disabled" : ""}>${decision === "skip" ? "Skipped" : "Skip"}</button></div></article>`;
  }).join("");
  box.innerHTML = `<div class="sghead"><b>${head}</b><button class="ico" id="suggestClose" aria-label="Back to saved clips" title="Back to saved clips">Saved clips (${state.project.clips.length})</button></div><details class="sgmethod"><summary>How moments are selected</summary><p class="sgbasis">${basis}</p></details><div class="sgreview"><span>Preview, then keep or skip</span><button id="suggestAddKept">Add kept</button></div><div class="sglist">${rows}</div>`;
  const note = box.querySelector(".sgbasis");
  note.title = note.textContent;
  $("suggestClose").onclick = () => { suggestionPreview = null; suggestion = {...suggestion, vid: null, clips: []}; paintSuggest(); };
  const kept = suggestion.clips.filter(s => suggestionReview.get(suggestionKey(s)) === "keep" && !suggestAdded(s)).length;
  $("suggestAddKept").textContent = `Add kept${kept ? ` (${kept})` : ""}`;
  $("suggestAddKept").disabled = !kept;
  $("suggestAddKept").onclick = addKeptSuggestions;
  box.querySelectorAll(".sg").forEach(row => {
    const s = suggestion.clips[Number(row.dataset.i)];
    row.querySelector(".sgpreview").onclick = () => {
      suggestionPreview = suggestionKey(s);
      box.querySelectorAll(".sgcard").forEach(card => {
        const active = card === row;
        card.dataset.preview = active;
        card.querySelector(".sgpreview").setAttribute("aria-pressed", active);
      });
      paintSuggestionRange();
      playRange(suggestClips(s)[0]);
    };
    for (const decision of ["keep", "skip"]) row.querySelector(`.sg${decision}`).onclick = e => {
      e.stopPropagation();
      const key = suggestionKey(s), next = suggestionReview.get(key) === decision ? null : decision;
      suggestionReview.set(key, next);
      const scroll = box.querySelector(".sglist").scrollTop;
      paintSuggest();
      box.querySelector(".sglist").scrollTop = scroll;
      box.querySelector(`.sg[data-i="${row.dataset.i}"] .sg${decision}`).focus({preventScroll: true});
      saveReview(state.current, s, next, suggestion.profile);
    };
  });
}

// The server's suggested moments for a video, best first, starting the search when it has not run. `progress` hears each poll of a running search.
async function fetchSuggestions(v, progress = () => {}) {
  let job = await api(`/api/suggest/${v.id}`);
  if (job.state === "none" || job.state === "error") job = await api(`/api/suggest/${v.id}`, "POST");
  while (job.state === "working") {
    progress(job);
    await new Promise(r => setTimeout(r, 1500));
    job = await api(`/api/suggest/${v.id}`);
  }
  if (job.state !== "ready") throw new Error(job.message || "Couldn't look for clips");
  return Object.assign(job.clips, {model: job.model, profile: job.profile});
}

async function runSuggest() {
  const v = state.current;
  if (!v) return toast("Pick a video first");
  if (suggestion.busy) return;
  suggestionReview = new Map();
  suggestionPreview = null;
  suggestion = {vid: v.id, clips: [], model: "", busy: true, pct: 0};
  $("suggestBtn").disabled = true;
  paintSuggest();
  try {
    // Earlier decisions come first, so the moments that show while the model is still scoring already wear them.
    suggestionReview = await loadReviews(v);
    const clips = await fetchSuggestions(v, job => { suggestion = {...suggestion, pct: job.pct || 0, model: job.model || "", clips: job.clips || [], profile: job.profile}; paintSuggest(); });
    suggestion = {vid: v.id, clips, model: clips.model, profile: clips.profile, busy: false};
    if (!clips.length) toast("Nothing stood out in this video");
  } catch (err) {
    suggestion = {vid: null, clips: [], model: "", busy: false};
    toast(err.message);
  }
  $("suggestBtn").disabled = false;
  paintSuggest();
}

// A downloaded video is scanned, listened to and ranked in the background; this shows how far along that is and says when it is done.
let prepareWatch = 0;
const wait = ms => new Promise(r => setTimeout(r, ms));

async function watchPrepare(v) {
  const mine = ++prepareWatch, btn = $("suggestBtn");
  const idle = btn.dataset.idle || (btn.dataset.idle = btn.title);
  btn.title = idle;
  let announced = false, none = 0;
  while (mine === prepareWatch && state.current && state.current.id === v.id) {
    let job;
    try { job = await api(`/api/prepare/${v.id}`); } catch (err) { break; }
    if (job.state === "queued" || job.state === "working") {
      announced = true;
      btn.title = `Getting this video ready: ${(job.step || "waiting").toLowerCase()}`;
      await wait(3000);
    } else if (job.state === "none" && ++none < 3) {
      await wait(1000);
    } else {
      if (job.state === "ready" && announced) toast("Suggestions are ready");
      break;
    }
  }
  if (mine === prepareWatch) btn.title = idle;
}

$("suggestBtn").onclick = runSuggest;
video.addEventListener("loadedmetadata", () => { paintSuggest(); if (state.current) watchPrepare(state.current); });
