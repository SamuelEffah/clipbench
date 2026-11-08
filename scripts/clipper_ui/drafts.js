// Draft Short: from the open video's best moment, make one complete Short as a new project, laid out, captioned and trimmed to length,
// so adjusting it is all that is left. Depends on app.js (state, api, toast, loadProject, flushSave, projectNames), suggest.js
// (fetchSuggestions, suggestClip), short.js (setMode) and autolayout.js (autoLayout, autoBusy).
const drafting = {on: false};
const DRAFTS = 1;  // one project per press; several at once piled up near-identical projects from the same video
const DRAFT_LEN = [30, 60];  // seconds; a moment this long makes a Short on its own, since Auto trims it to the longest a Short runs
const DRAFT_NAME_MAX = 60;  // the longest project name the server takes

// The moments to draft from, best first: those already the length of a Short, then the best of the rest.
function draftPicks(moments, count = DRAFTS) {
  const fits = m => m.out - m.in >= DRAFT_LEN[0] && m.out - m.in <= DRAFT_LEN[1];
  return [...moments.filter(fits), ...moments.filter(m => !fits(m))].slice(0, count);
}

// Project names for the drafts, after the open project's, skipping any already in use.
function draftNames(base, taken, count) {
  const stem = base.replace(/-draft-\d+$/, "").slice(0, DRAFT_NAME_MAX - "-draft-99".length);
  const names = [];
  for (let n = 1; names.length < count; n++) {
    const name = `${stem}-draft-${n}`;
    if (!taken.includes(name)) names.push(name);
  }
  return names;
}

// A draft as the server stores a project: the moment as the one clip in the top lane of a vertical Short, and in the bank.
function draftProject(name, clip) {
  const top = {...clip, lane: "top"};
  return {name, clips: [top], bank: [{...clip}], audio: [], format: "9:16", template: "full", layout: "title", watermark: true};
}

async function draftShorts() {
  const v = state.current;
  if (!v) return toast("Pick a video first");
  if (drafting.on || autoBusy.on) return;
  drafting.on = true;
  $("draftBtn").disabled = true;
  const made = [];
  try {
    toast("Looking for the best moments");
    const picks = draftPicks(await fetchSuggestions(v));
    if (!picks.length) return toast("Nothing stood out in this video");
    const names = draftNames(state.project.name, projectNames, picks.length);
    await flushSave();
    for (const [k, moment] of picks.entries()) {
      toast(`Draft ${k + 1} of ${picks.length}: ${fmt(moment.in)} to ${fmt(moment.out)}`);
      await api(`/api/project/${names[k]}`, "PUT", draftProject(names[k], suggestClip(moment, v)));
      projectNames = [...projectNames, names[k]];
      await loadProject(names[k]);
      setMode("short");
      await autoLayout();
      await flushSave();
      made.push(names[k]);
    }
    toast(`Draft made, ${made[0]}`);
  } catch (err) {
    toast(made.length ? `${err.message}. ${made.length} ${made.length > 1 ? "drafts were" : "draft was"} made` : err.message || "Couldn't draft Shorts");
  } finally {
    drafting.on = false;
    $("draftBtn").disabled = false;
  }
}

const draftBtn = $("draftBtn");
draftBtn.addEventListener("click", draftShorts);
