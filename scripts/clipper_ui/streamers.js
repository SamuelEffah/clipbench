// The Streamers list in the Clips station: channels you follow, who is live right now, and one click to load a live one.
// Depends on app.js: $, api, toast, esc and live.js: liveEl, streaming.
const STREAMER_POLL = 120000;
const streamerState = {list: [], status: {}, timer: 0, run: 0};

const streamerName = s => (s.name.startsWith("UC") && s.url.includes("/channel/") ? "Channel" : s.name);

const isLive = s => (streamerState.status[s.url] || {}).live === true;

function paintStreamers() {
  const rows = $("streamerRows");
  const live = streamerState.list.filter(isLive).length;
  $("streamerCount").textContent = streamerState.list.length ? `${live} live` : "";
  $("streamerCount").classList.toggle("hot", live > 0);
  if (!streamerState.list.length) {
    rows.innerHTML = '<p class="note">Follow a YouTube or Twitch channel and it shows here when it goes live.</p>';
    return;
  }
  const ordered = [...streamerState.list].sort((a, b) => Number(isLive(b)) - Number(isLive(a)));
  rows.replaceChildren(...ordered.map(s => {
    const st = streamerState.status[s.url] || "checking", on = isLive(s), name = streamerName(s);
    const row = document.createElement("div");
    row.className = `strow${on ? " on" : ""}`;
    const line = on ? st.title || "Streaming now" : st === "checking" ? "Checking" : st === "unknown" ? "Couldn't check" : "Offline";
    row.innerHTML = `<button type="button" class="stmain" ${on ? "" : "disabled"} title="${on ? "Load this stream" : ""}"><span class="av" aria-hidden="true">${esc(name.charAt(0).toUpperCase())}</span>` +
      `<span class="stt"><b>${esc(name)}${s.kind === "twitch" ? '<em class="plat">Twitch</em>' : ""}${on ? '<em class="livetag">Live</em>' : ""}</b><small class="num">${esc(line)}</small></span></button>` +
      `<button type="button" class="ti stdel" aria-label="Stop following ${esc(name)}" title="Stop following"><svg class="i"><use href="#close"/></svg></button>`;
    row.querySelector(".stmain").onclick = () => loadStreamer(st.watch);
    row.querySelector(".stdel").onclick = () => removeStreamer(s.url);
    return row;
  }));
}

function loadStreamer(watch) {
  if (!watch) return;
  if (!streaming()) enterLive();
  liveEl("liveUrl").value = watch;
  liveEl("liveBar").requestSubmit();
}

// One channel at a time, so a long list never starts a pile of yt-dlp runs.
let streamerChecking = null, streamerCheckPending = false;
function checkStreamers() {
  streamerCheckPending = true;
  if (streamerChecking) return streamerChecking;
  streamerChecking = (async () => {
    while (streamerCheckPending && !document.hidden && !streaming()) {
      streamerCheckPending = false;
      for (const s of [...streamerState.list]) {
        if (document.hidden || streaming()) break;
        let result;
        try { result = await api("/api/streamers/live", "POST", {url: s.url}); } catch { result = "unknown"; }
        if (!streamerState.list.some(current => current.url === s.url)) continue;
        streamerState.status = {...streamerState.status, [s.url]: result};
        if (!document.hidden) paintStreamers();
      }
    }
  })().finally(() => { streamerChecking = null; });
  return streamerChecking;
}

async function loadStreamers() {
  try { streamerState.list = await api("/api/streamers"); } catch (err) { toast(err.message); }
  paintStreamers();
  checkStreamers();
}

async function addStreamer(e) {
  e.preventDefault();
  const input = $("streamerInput"), text = input.value.trim();
  if (!text) return;
  try {
    streamerState.list = await api("/api/streamers", "POST", {input: text});
    input.value = "";
    $("streamerAdd").disabled = true;
    paintStreamers();
    checkStreamers();
  } catch (err) { toast(err.message); }
}

async function removeStreamer(url) {
  try {
    streamerState.list = await api("/api/streamers/remove", "POST", {url});
    paintStreamers();
  } catch (err) { toast(err.message); }
}

// The section folds to its heading; the choice is remembered.
const FOLD_KEY = "streamersFolded";
function foldStreamers(folded) {
  $("streamers").classList.toggle("folded", folded);
  const b = $("streamerFold");
  b.setAttribute("aria-expanded", String(!folded));
  b.setAttribute("aria-label", folded ? "Expand Streamers" : "Collapse Streamers");
  b.title = folded ? "Expand" : "Collapse";
  try { localStorage.setItem(FOLD_KEY, folded ? "1" : "0"); } catch { /* the choice just isn't remembered */ }
}
$("streamerFold").onclick = () => foldStreamers(!$("streamers").classList.contains("folded"));
try { foldStreamers(localStorage.getItem(FOLD_KEY) !== "0"); } catch { /* retain the markup default */ }

// Always in the sources panel. Checks run while the page is visible, and again when you come back to it.
function startStreamers() {
  loadStreamers();
  // Not while a stream is playing: the checks would compete with it for the connection.
  streamerState.timer = setInterval(() => { if (!document.hidden && !streaming()) checkStreamers(); }, STREAMER_POLL);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden && !streaming() && streamerState.list.length) checkStreamers(); });

$("streamerForm").onsubmit = addStreamer;
$("streamerRefresh").onclick = checkStreamers;
$("streamerInput").oninput = e => { $("streamerAdd").disabled = !e.target.value.trim(); };
startStreamers();
