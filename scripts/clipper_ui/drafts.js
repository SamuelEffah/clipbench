// Draft Short: take the open video's best moment and put it on the open project's timeline, then lay it out, caption it and trim it to length,
// so adjusting it is all that is left. It never makes another project. Depends on app.js (state, toast), suggest.js (fetchSuggestions, suggestClip),
// short.js (setMode, addToShort, isTop) and autolayout.js (autoLayout, autoBusy).
const drafting = {on: false};
const DRAFT_LEN = [30, 60];  // seconds; a moment this long makes a Short on its own, since Auto trims it to the longest a Short runs

// The best moment to draft from: one already the length of a Short first, else the best of the rest.
function draftPick(moments) {
  const fits = m => m.out - m.in >= DRAFT_LEN[0] && m.out - m.in <= DRAFT_LEN[1];
  return moments.find(fits) || moments[0] || null;
}

async function draftShorts() {
  const v = state.current;
  if (!v) return toast("Pick a video first");
  if (drafting.on || autoBusy.on) return;
  drafting.on = true;
  $("draftBtn").disabled = true;
  try {
    toast("Looking for the best moment");
    const pick = draftPick(await fetchSuggestions(v));
    if (!pick) return toast("Nothing stood out in this video");
    const fresh = !state.project.clips.some(isTop);
    setMode("short");
    addToShort(suggestClip(pick, v));
    if (fresh) await autoLayout();
    else toast(`Added ${fmt(pick.in)} to ${fmt(pick.out)}`);
  } catch (err) {
    toast(err.message || "Couldn't draft a Short");
  } finally {
    drafting.on = false;
    $("draftBtn").disabled = false;
  }
}

const draftBtn = $("draftBtn");
draftBtn.addEventListener("click", draftShorts);
