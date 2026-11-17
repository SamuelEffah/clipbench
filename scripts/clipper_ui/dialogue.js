// Search what is said: type a line and every video with subtitles answers with the places it is spoken. Depends on app.js.
let dialogue = {q: "", results: [], videos: 0, unheard: [], busy: false};
let dialogueSeq = 0, dialogueTimer = 0, listenTimer = 0;

const DIALOGUE_DELAY = 250, LISTEN_POLL = 4000;
const dialogueClip = r => ({src: r.path, in: r.in, out: r.out, note: "", caption: "", speed: 1, volume: 1, fit: "fit", pan: 0.5, effect: "none", ramp: "none", freeze: 0, thumb: `/video-thumb/${r.vid}.jpg`});
const dialogueAdded = r => state.project.clips.some(c => c.src === r.path && Math.abs(c.in - r.in) < 0.05 && Math.abs(c.out - r.out) < 0.05);

// The matched words are lit; the rest of the line is left alone.
function lit(text, q) {
  const words = q.toLowerCase().replace(/[^\w\s']/g, " ").split(/\s+/).filter(Boolean);
  if (!words.length) return esc(text);
  const hit = new RegExp(`(${words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(hit).map((part, n) => (n % 2 ? `<mark>${esc(part)}</mark>` : esc(part))).join("");
}

function dialogueAdd(r) {
  state.project = {...state.project, clips: [dialogueClip(r), ...state.project.clips]};
  requestCut(state.project.clips[0]);
  state.sel = 0;
  state.arrived = 0;
  changed();
  state.arrived = -1;
  paintDialogue();
}

async function dialoguePlay(r) {
  const v = byPath(r.path);
  if (!v) return toast("That video is missing from the library");
  if (!state.current || state.current.id !== v.id) await openVideo(v, r.in);
  playRange(dialogueClip(r));
}

// Videos with no subtitle track can only be searched once they have been listened to; this offers that, and shows it running.
function paintListen() {
  const box = $("dlisten"), list = dialogue.unheard, working = list.filter(v => v.working).length, n = list.length;
  box.hidden = !n;
  if (!n) return;
  const videos = `${n} ${n === 1 ? "video has" : "videos have"}`;
  box.innerHTML = working
    ? `<p>Listening to ${working} ${working === 1 ? "video" : "videos"}, a few minutes each. Search finds them when it's done.</p>`
    : `<p>${videos} no subtitles, so search can't find what is said in ${n === 1 ? "it" : "them"}.</p><button id="dlisten-go">Listen</button>`;
  const go = $("dlisten-go");
  if (go) go.onclick = listenToAll;
}

async function refreshUnheard() {
  const project = projectQuery();
  if (dialogue.project !== project) {
    dialogue = {...dialogue, project, results: [], videos: 0, unheard: [], busy: false};
    paintListen();
    if (typeof paintDialogue === "function") paintDialogue();
  }
  try {
    const got = await api(`/api/dialogue?q=${project.replace(/^\?/, "&")}`);
    if (project !== projectQuery()) return;
    dialogue = {...dialogue, videos: got.videos, unheard: got.unheard || []};
  } catch (err) { return; }
  paintListen();
}

async function listenToAll() {
  const todo = dialogue.unheard.filter(v => !v.working);
  try {
    await Promise.all(todo.map(v => api("/api/index-speech", "POST", {id: v.id})));
  } catch (err) { return toast("Couldn't start listening"); }
  dialogue = {...dialogue, unheard: dialogue.unheard.map(v => ({...v, working: true}))};
  paintListen();
  pollListen();
}

// Polls until nothing is still being listened to, says which videos failed, then searches again with what was heard.
function pollListen() {
  clearTimeout(listenTimer);
  listenTimer = setTimeout(async () => {
    const before = dialogue.unheard.filter(v => v.working);
    await refreshUnheard();
    const stillWorking = dialogue.unheard.some(v => v.working);
    if (stillWorking) return pollListen();
    const failed = await Promise.all(before.map(v => api(`/api/index-speech/${v.id}`).catch(() => ({state: "error"}))));
    const bad = failed.find(j => j.state === "error");
    if (bad) toast(bad.message || "Couldn't listen to a video");
    else toast("Done listening. Search now finds what they say");
    if (dialogue.q.trim().length >= 2) runDialogue();
  }, LISTEN_POLL);
}

function paintDialogue() {
  const box = $("dresults"), q = dialogue.q.trim();
  box.hidden = q.length < 2;
  $("dclear").hidden = !dialogue.q;
  if (box.hidden) return;
  if (dialogue.busy && !dialogue.results.length) { box.innerHTML = `<p class="sgbasis">Reading the subtitles of every video</p>`; return; }
  if (!dialogue.results.length) {
    box.innerHTML = `<p class="sgbasis">${dialogue.videos ? `Nobody says that in ${dialogue.videos} ${dialogue.videos === 1 ? "video" : "videos"} with subtitles. Try fewer words.` : "No video here has English subtitles to search."}</p>`;
    return;
  }
  const n = dialogue.results.length;
  const rows = dialogue.results.map((r, i) => {
    const added = dialogueAdded(r);
    return `<div class="sg" data-i="${i}" role="button" tabindex="0" title="Play this line"><div class="sgbody"><small class="num">${fmt(r.at)}, ${(r.out - r.in).toFixed(0)}s${r.cut ? ", on the cuts" : ""}, ${esc(r.name.replace(/\.[^.]+$/, "").replace(/^_+|_encoded$/g, "").replace(/_+/g, " "))}</small><p>${lit(r.text, q)}</p></div>` +
      `<button class="sgadd" aria-pressed="${added}" aria-label="${added ? "Already a clip" : "Make this a clip"}" title="${added ? "Already a clip" : "Make this a clip"}"${added ? " disabled" : ""}><svg class="i"><use href="#${added ? "c-check" : "plus"}"/></svg></button></div>`;
  }).join("");
  box.innerHTML = `<div class="sghead"><b>${n}${n >= 40 ? "+" : ""} ${n === 1 ? "place" : "places"}</b></div><div class="sglist">${rows}</div>`;
  box.querySelectorAll(".sg").forEach(row => {
    const r = dialogue.results[Number(row.dataset.i)];
    row.onclick = () => dialoguePlay(r);
    row.onkeydown = e => { if (e.key === "Enter" && e.target === row) dialoguePlay(r); };
    row.querySelector(".sgadd").onclick = e => { e.stopPropagation(); dialogueAdd(r); };
  });
}

let dialoguePending = null, dialogueRunning = null;
function runDialogue() {
  const q = dialogue.q.trim(), seq = ++dialogueSeq;
  dialoguePending = q.length >= 2 ? {q, seq, project: projectQuery()} : null;
  if (q.length < 2) {
    dialogue = {...dialogue, results: [], busy: false};
    paintDialogue();
  }
  if (dialogueRunning) return dialogueRunning;
  if (!dialoguePending) return Promise.resolve();
  dialogueRunning = (async () => {
    try {
      while (dialoguePending) {
        const next = dialoguePending;
        dialoguePending = null;
        if (next.seq === dialogueSeq && next.project === projectQuery())
          await searchDialogue(next.q, next.seq, next.project);
      }
    } finally { dialogueRunning = null; }
  })();
  return dialogueRunning;
}

async function searchDialogue(q, seq, project) {
  if (q.length < 2) { dialogue = {...dialogue, results: [], busy: false}; return paintDialogue(); }
  dialogue = {...dialogue, busy: true};
  paintDialogue();
  try {
    const got = await api(`/api/dialogue?q=${encodeURIComponent(q)}${project.replace(/^\?/, "&")}`);
    if (seq !== dialogueSeq || project !== projectQuery()) return;
    dialogue = {...dialogue, results: got.results, videos: got.videos, unheard: got.unheard || [], busy: false};
  } catch (err) {
    if (seq !== dialogueSeq || project !== projectQuery()) return;
    dialogue = {...dialogue, results: [], busy: false};
    toast("Couldn't search the subtitles");
  }
  paintDialogue();
}

$("dq").oninput = e => {
  dialogueSeq++;
  dialoguePending = null;
  dialogue = {...dialogue, q: e.target.value};
  clearTimeout(dialogueTimer);
  paintDialogue();
  dialogueTimer = setTimeout(runDialogue, DIALOGUE_DELAY);
};
$("dq").onkeydown = e => { if (e.key === "Escape") $("dclear").click(); e.stopPropagation(); };
$("dclear").onclick = () => {
  $("dq").value = "";
  dialogue = {q: "", results: [], videos: dialogue.videos, busy: false};
  dialogueSeq++;
  dialoguePending = null;
  clearTimeout(dialogueTimer);
  paintDialogue();
  $("dq").focus();
};
// Subtitle counts load with refreshLibrary, after the project has been selected.
