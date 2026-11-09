// Draft Short: build the Short from the clips in the bank. They go on the open project's timeline in the order they sit in the video, a long
// one is cut down to its best part so the whole comes to about a minute, then Auto lays it out and captions it. It never makes another project.
// Depends on app.js (state, toast, byPath, momentFinder), suggest.js (fetchSuggestions), short.js (bankOf, setMode, insertClip, isTop, changed)
// and autolayout.js (autoLayout, autoBusy).
const drafting = {on: false};
const draftButtons = document.querySelectorAll("[data-draft]");
const DRAFT_LEN = [40, 60];  // seconds the Short aims for; a bank that already comes to less is used whole
const DRAFT_PIECE_MIN = 8;   // a clip is never cut shorter than this

const draftRound = t => Number(t.toFixed(2));
const draftScore = (clip, moments) => Math.max(0, ...moments.filter(m => !m.pieces && m.out > clip.in && m.in < clip.out).map(m => m.score || 0));

// `len` seconds of a clip, centred on its best-scored moment when the scan found one inside it, else from its start.
function draftWindow(clip, len, moments) {
  const best = moments.filter(m => !m.pieces && m.out > clip.in && m.in < clip.out).sort((a, b) => (b.score || 0) - (a.score || 0))[0];
  const mid = best ? (Math.max(best.in, clip.in) + Math.min(best.out, clip.out)) / 2 : clip.in + len / 2;
  const start = Math.min(Math.max(mid - len / 2, clip.in), clip.out - len);
  return {...clip, in: draftRound(start), out: draftRound(start + len)};
}

// The clips of the draft, in video order. Over the longest length, every clip longer than the floor is shortened by the same share, then the lowest-scored are dropped.
// `momentsOf(src)` lists that video's scored moments ({in, out, score}); it may be empty.
function draftPlan(bank, momentsOf = () => [], [, most] = DRAFT_LEN) {
  const order = [...new Set(bank.map(c => c.src))];
  const items = bank.map(c => ({clip: c, len: c.out - c.in, score: draftScore(c, momentsOf(c.src))}))
    .sort((a, b) => order.indexOf(a.clip.src) - order.indexOf(b.clip.src) || a.clip.in - b.clip.in);
  const total = () => items.reduce((sum, it) => sum + it.len, 0);
  while (total() > most + 0.05) {
    const long = items.filter(it => it.len > DRAFT_PIECE_MIN + 0.05), fixed = total() - long.reduce((sum, it) => sum + it.len, 0);
    const keep = (most - fixed) / long.reduce((sum, it) => sum + it.len, 0);
    if (long.length && keep > 0) long.forEach(it => { it.len = Math.max(DRAFT_PIECE_MIN, it.len * Math.min(keep, 1)); });
    else items.splice(items.indexOf([...items].sort((a, b) => a.score - b.score || b.clip.in - a.clip.in)[0]), 1);
  }
  return items.map(it => (it.len < it.clip.out - it.clip.in - 0.05 ? draftWindow(it.clip, it.len, momentsOf(it.clip.src)) : it.clip));
}

async function draftMoments(bank) {
  const found = new Map();
  for (const src of new Set(bank.map(c => c.src))) {
    const v = byPath(src);
    found.set(src, v ? await fetchSuggestions(v).catch(() => []) : []);
  }
  return src => found.get(src) || [];
}

async function draftShorts() {
  if (drafting.on || autoBusy.on) return;
  const findUsed = momentFinder(state.project.clips);
  const bank = bankOf().filter(c => findUsed(c) < 0);
  if (!bank.length) return toast(bankOf().length ? "Every clip is already on the timeline" : "No clips in the bank yet");
  drafting.on = true;
  draftButtons.forEach(b => { b.disabled = true; });
  try {
    const long = bank.reduce((sum, c) => sum + c.out - c.in, 0) > DRAFT_LEN[1];
    if (long) toast("Picking the best parts");
    const plan = draftPlan(bank, long ? await draftMoments(bank) : () => []);
    const fresh = !state.project.clips.some(isTop);
    setMode("short");
    plan.forEach(c => insertClip(c, "top"));
    state.sel = state.project.clips.length - plan.length;
    changed();
    if (fresh) await autoLayout();
    else toast(`Added ${plan.length} ${plan.length > 1 ? "clips" : "clip"} to the timeline`);
  } catch (err) {
    toast(err.message || "Couldn't draft a Short");
  } finally {
    drafting.on = false;
    draftButtons.forEach(b => { b.disabled = false; });
  }
}

draftButtons.forEach(b => b.addEventListener("click", draftShorts));
