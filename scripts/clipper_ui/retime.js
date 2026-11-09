// Re-time a clip's captions when a trim has taken it past the speech that was timed, so the new stretch isn't left without any.
// It waits until the edits stop, tries each range of a clip once, and leaves a clip alone whose caption has been edited by hand.
// Depends on app.js (state, changed), short.js (inShort, isTop) and captions.js (uncovered, syncSpeech, capModeOf).
const RETIME_WAIT_MS = 1500;
const retiming = {timer: null, busy: false, tried: new Set()};

const retimeKey = c => `${c.src}|${c.in}|${c.out}`;
const wordsText = list => (list || []).map(w => w[0]).join(" ").replace(/\s+/g, " ").trim();

// A top clip whose timed speech no longer reaches all of it and whose words are as they were heard, and not tried for this range yet.
function retimeable(c, tried = retiming.tried) {
  if (!isTop(c) || !uncovered(c) || tried.has(retimeKey(c))) return false;
  const heard = wordsText(c.heard || c.words);
  return wordsText(c.words) === heard && String(c.caption || "").replace(/\s+/g, " ").trim() === heard;
}

function scheduleRetime() {
  clearTimeout(retiming.timer);
  retiming.timer = setTimeout(retimeNext, RETIME_WAIT_MS);
}

async function retimeNext() {
  if (retiming.busy || !inShort()) return;
  const at = state.project.clips.findIndex(c => retimeable(c));
  if (at < 0) return;
  const clip = state.project.clips[at];
  retiming.tried.add(retimeKey(clip));
  retiming.busy = true;
  try {
    await syncSpeech(at, capModeOf(clip), {textContent: ""});
  } finally {
    retiming.busy = false;
  }
  scheduleRetime();
}
