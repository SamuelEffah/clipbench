// Clip from a YouTube or Twitch player: watch it here, mark an in and out, and the server downloads just that stretch.
// It lives in the source monitor: the player takes the video's place, and the monitor's own Mark in, Mark out, play and
// seek controls drive it. The bottom timeline becomes the stream's buffer, where the clip's range is set and shown. Depends on app.js: $, api, toast, refreshLibrary.
const live = {player: null, kind: "", id: "", channel: false, recStart: 0, url: "", isLive: false, start: null, ranges: [], shift: null, buffer: 900, ticker: 0, resume: "", viewSeconds: 900};
// The server cuts at most 600 seconds, and each selection is cut with padding either side.
const MAX_MARK = 540;
const PLAYER_TIMEOUT = 20000;
const liveEl = id => $(id);
const TWITCH_PAGES = ["videos", "directory", "downloads", "jobs", "settings", "turbo", "store", "subs", "friends", "wallet", "search", "clips", "popout", "embed", "p", "u"];
const loaded = {};
const streaming = () => document.body.classList.contains("streaming");

function liveSource(text) {
  let u;
  try { u = new URL(text.trim()); } catch { return null; }
  const host = u.hostname.replace(/^(www|m|music)\./, "");
  if (host === "youtu.be") return {kind: "youtube", id: u.pathname.slice(1)};
  if (host === "youtube.com") {
    const v = u.searchParams.get("v") || (u.pathname.match(/^\/(?:live|embed|shorts)\/([\w-]{6,})/) || [])[1];
    return v ? {kind: "youtube", id: v} : null;
  }
  if (host === "twitch.tv") {
    const vod = u.pathname.match(/^\/videos\/(\d+)/);
    if (vod) return {kind: "twitch", id: vod[1]};
    const chan = u.pathname.match(/^\/([A-Za-z0-9_]{2,25})\/?$/);
    return chan && !TWITCH_PAGES.includes(chan[1].toLowerCase()) ? {kind: "twitch", id: chan[1], channel: true} : null;
  }
  return null;
}

function loadScript(src) {
  loaded[src] = loaded[src] || new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = ok;
    s.onerror = () => { delete loaded[src]; fail(new Error("Couldn't load the player. Check your connection")); };
    document.head.appendChild(s);
  });
  return loaded[src];
}

let ytReady = null;
function youtubeApi() {
  if (window.YT && window.YT.Player) return Promise.resolve();
  ytReady = ytReady || new Promise((ok, fail) => {
    window.onYouTubeIframeAPIReady = ok;
    loadScript("https://www.youtube.com/iframe_api").catch(err => { ytReady = null; fail(err); });
  });
  return ytReady;
}

// YouTube and Twitch name their player controls differently.
const isTwitch = () => live.kind === "twitch";
const playerPlay = () => (isTwitch() ? live.player.play() : live.player.playVideo());
const playerPause = () => (isTwitch() ? live.player.pause() : live.player.pauseVideo());
const playerPaused = () => (isTwitch() ? live.player.isPaused() : live.player.getPlayerState() !== 1);
const playerSeek = t => (isTwitch() ? live.player.seek(Math.max(0, t)) : live.player.seekTo(t, true));

const YT_ERRORS = {2: "That link doesn't point to a video", 5: "This video can't play here", 100: "That video was removed or is private",
  101: "This video can't play outside YouTube. It may be private, removed, or blocked from other sites",
  150: "This video can't play outside YouTube. It may be private, removed, or blocked from other sites"};

function mount() {
  const host = liveEl("liveStage");
  host.replaceChildren(Object.assign(document.createElement("div"), {id: "livePlayer"}));
}

function liveStatus(text, isError) {
  const el = liveEl("liveHint");
  el.hidden = !text;
  el.textContent = text;
  el.classList.toggle("err", Boolean(isError));
}

// Browsers refuse sound before a click, so a start they block runs again muted, and the sound comes on at the next click or key.
function playMutedUntilTouched(mute, unmute) {
  mute();
  const on = () => {
    unmute();
    document.removeEventListener("pointerdown", on, true);
    document.removeEventListener("keydown", on, true);
  };
  document.addEventListener("pointerdown", on, true);
  document.addEventListener("keydown", on, true);
  toast("Playing muted. Click anywhere to turn the sound on");
}

// Loading another link, or leaving, while one is still loading drops it, so the player always shows the link that clips are cut from.
let liveLoadToken = 0;
async function openLive() {
  const src = liveSource(liveEl("liveUrl").value);
  if (!src) return liveStatus("Paste a YouTube link, or a Twitch channel or video link", true);
  const token = ++liveLoadToken;
  liveStatus("Loading the player");
  try {
    destroyLive();
    mount();
    if (src.kind === "youtube") {
      await youtubeApi();
      if (token !== liveLoadToken) return;
      const player = await new Promise((ok, fail) => {
        const late = setTimeout(() => fail(new Error("The player didn't load. Check the link and your connection")), PLAYER_TIMEOUT);
        const p = new YT.Player("livePlayer", {videoId: src.id, width: "100%", height: "100%", playerVars: {playsinline: 1, rel: 0, autoplay: 1},
          events: {onReady: () => { clearTimeout(late); ok(p); p.playVideo(); }, onStateChange: e => e.data === 1 && onPlaying(),
            onAutoplayBlocked: () => playMutedUntilTouched(() => { p.mute(); p.playVideo(); }, () => p.unMute()),
            onError: e => { clearTimeout(late); const msg = YT_ERRORS[e.data] || "This video can't play here"; fail(new Error(msg)); if (token === liveLoadToken) liveStatus(msg, true); }}});
      });
      if (token !== liveLoadToken) { try { player.destroy(); } catch {} return; }
      live.player = player;
    } else {
      await loadScript("https://player.twitch.tv/js/embed/v1.js");
      if (token !== liveLoadToken) return;
      const twitch = new Twitch.Player("livePlayer", {[src.channel ? "channel" : "video"]: src.id, width: "100%", height: "100%", parent: [location.hostname], autoplay: true});
      twitch.addEventListener(Twitch.Player.READY, () => twitch.play());
      twitch.addEventListener(Twitch.Player.PLAYBACK_BLOCKED, () => playMutedUntilTouched(() => { twitch.setMuted(true); twitch.play(); }, () => twitch.setMuted(false)));
      live.player = twitch;
    }
    const url = liveEl("liveUrl").value.trim(), same = url === live.url, keep = same && !src.channel;
    Object.assign(live, {shift: src.channel ? 0 : null, isLive: Boolean(src.channel), buffer: 900, kind: src.kind, id: src.id, channel: Boolean(src.channel), recStart: 0, url, start: keep ? live.start : null, ranges: keep ? live.ranges : []});
    if (src.channel) await startRecording(url, token);
    liveEl("liveStage").hidden = false;
    liveStatus("");
    liveEl("srcName").textContent = streamTitle() || "Stream";
    liveEl("srcMeta").textContent = src.kind === "twitch" ? "Twitch" : "YouTube";
    paintBuffer();
    renderLibrary();
  } catch (err) {
    if (token === liveLoadToken) liveStatus(err.message, true);
  }
}

// Twitch keeps about 6 seconds of a live channel, so the server records it while you watch and clips are cut from that.
async function startRecording(url, token) {
  liveStatus("Starting the recording");
  try {
    const got = await api("/api/live-record", "POST", {url});
    if (token === liveLoadToken) live.recStart = got.started;
    liveStatus("");
  } catch (err) {
    if (token === liveLoadToken) liveStatus(`Can't record this channel: ${err.message}`, true);
  }
}
const stopRecording = () => { if (live.channel) { live.recStart = 0; api("/api/live-record/stop", "POST", {}).catch(() => {}); } };
window.addEventListener("pagehide", () => { if (live.channel) navigator.sendBeacon("/api/live-record/stop", new Blob(["{}"], {type: "application/json"})); });

function destroyLive() {
  stopRecording();
  if (live.player && live.player.destroy) { try { live.player.destroy(); } catch {} }
  live.player = null;
}

// A live stream has no fixed time line, so its marks are wall-clock seconds. The player's own duration is not reliable on a
// live stream, so instead the player is sent to the live edge and the clock is read there: after that a position t is at
// wall-clock t + shift. Jump to live does the same again to re-sync. A recording's marks are plain positions.
const playingLive = () => Boolean(live.player && live.kind === "youtube" && live.player.getVideoData().isLive);
let syncing = false;
async function syncToLive() {
  if (syncing || !live.player) return;
  syncing = true;
  previewEnd = null;
  liveStatus("Finding the live edge");
  try {
    live.player.seekTo(1e9, true);
    live.player.playVideo();
    let last = -1;
    for (let n = 0; n < 24; n++) {
      await new Promise(r => setTimeout(r, 500));
      if (!live.player) return;
      const t = Number(live.player.getCurrentTime());
      if (n >= 3 && live.player.getPlayerState() === 1 && t - last > 0.2) break;
      last = t;
    }
    live.shift = Date.now() / 1000 - Number(live.player.getCurrentTime());
    live.isLive = true;
    liveStatus("");
    api("/api/live-buffer", "POST", {url: live.url}).then(r => { live.buffer = r.seconds || live.buffer; paintBuffer(); }).catch(() => {});
  } finally {
    syncing = false;
    paintBuffer();
  }
}
function onPlaying() {
  if (live.shift !== null || syncing || !playingLive()) return paintBuffer();
  live.isLive = true;
  syncToLive();
}
const liveNow = () => {
  if (live.channel) return Date.now() / 1000;
  const t = Number(live.player.getCurrentTime());
  return live.isLive && live.shift !== null ? t + live.shift : t;
};

// The stretch of the stream the buffer bar shows, in the same units as the marks.
function domain() {
  if (!live.player) return null;
  if (live.channel) return live.recStart ? {lo: live.recStart, hi: Date.now() / 1000} : null;
  if (live.isLive && live.shift !== null) {
    const hi = Date.now() / 1000;
    return {lo: hi - live.buffer, hi};
  }
  const dur = Number(live.player.getDuration && live.player.getDuration());
  return dur > 0 && Number.isFinite(dur) && !live.isLive ? {lo: 0, hi: dur} : null;
}

// Zoom changes only the visible window; the real buffer still bounds seeks and clips.
function bufferView(available) {
  if (!available || !live.isLive || live.viewSeconds === 0) return available;
  return {lo: available.hi - (live.viewSeconds || 900), hi: available.hi};
}

const TWITCH_LIVE_HINT = "Recording this channel from when you opened it. Press I and O as you watch, then Clip selection. A live Twitch stream can't be rewound.";
const stamp = t => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
const clock = secs => (secs >= 60 ? `${Math.round(secs / 60)} min` : `${Math.round(secs)}s`);
let made = [];
// Marking by hand runs late, so each selection is cut with a little extra either side to trim away.
const PAD = 3;
// The player runs a few seconds behind the stream's own playlist, so what you saw at a mark is a little earlier in the playlist.
const PLAYER_LAG = 3;


function place(el, d, from, to) {
  const span = d.hi - d.lo;
  const a = Math.max(0, (from - d.lo) / span), b = Math.min(1, (to - d.lo) / span);
  el.style.left = `${a * 100}%`;
  el.style.width = `${Math.max(0, b - a) * 100}%`;
}

const behindText = () => {
  const behind = Math.round(Math.max(0, Date.now() / 1000 - liveNow()));
  return behind < 1 ? "At the live edge" : `${Math.floor(behind / 60)}:${String(behind % 60).padStart(2, "0")} behind live`;
};

// Play a selection as it will be cut, padding included, and stop at its end.
let previewEnd = null;
function previewSelection(i) {
  const r = live.ranges[i], d = domain();
  if (!r || !d) return;
  if (live.channel) return toast("A live Twitch stream can't be rewound. The clip is cut from the recording");
  seekTo(Math.max(d.lo, r.start - PAD));
  previewEnd = Math.min(d.hi, r.end + PAD);
  playerPlay();
}
function checkPreview() {
  if (previewEnd === null || !live.player) return;
  if (liveNow() >= previewEnd) { previewEnd = null; playerPause(); }
}

function jumpToLive() {
  if (live.player && live.isLive) syncToLive();
}

function paintBuffer() {
  const available = domain(), d = bufferView(available), ok = Boolean(d && d.hi > d.lo), n = live.ranges.length;
  liveEl("bufZoom").hidden = !live.isLive;
  const coverage = liveEl("bufAvailable");
  coverage.hidden = !ok;
  if (ok) place(coverage, d, available.lo, available.hi);
  paintMoments(available, d);
  const btn = liveEl("liveClip");
  btn.disabled = !n;
  btn.title = n > 1 ? `Clip the ${n} selections (Enter)` : "Clip the selection (Enter)";
  liveEl("liveCnt").textContent = n;
  liveEl("liveCnt").hidden = n < 2;
  liveEl("liveBadge").hidden = !(live.player && live.isLive);
  liveEl("liveIn").classList.toggle("pending", live.start !== null);
  liveEl("bufHint").textContent = !live.player ? "Connect a stream from Sources" : live.channel && ok ? TWITCH_LIVE_HINT : !ok ? "Press play to load the stream's timeline"
    : "Press I and O at the playhead for each clip, then Clip selection. Drag the handles to adjust";
  const total = live.ranges.reduce((t, r) => t + r.end - r.start + 2 * PAD, 0);
  liveEl("bufSel").textContent = live.start !== null ? "Now mark the out" : n ? `${n} selected, ${total.toFixed(1)}s` : "";
  liveEl("liveJump").hidden = !(live.player && live.isLive && !live.channel);
  const title = live.player ? streamTitle() : "";
  if (title && liveEl("srcName").textContent !== title) liveEl("srcName").textContent = title;
  if (live.player) liveEl("srcMeta").textContent = `${live.kind === "twitch" ? "Twitch" : "YouTube"}, ${live.isLive || live.channel ? "live" : "recording"}`;
  liveEl("bufLen").textContent = ok && live.channel ? `Recording ${clock(available.hi - available.lo)}` : ok && live.isLive ? `Buffer holds ${clock(live.buffer)}` : "";
  liveEl("liveTc").textContent = !live.player ? "" : live.channel && !ok ? "Starting the recording" : !ok ? (syncing ? "Finding the live edge" : "Press play") : live.isLive ? behindText() : `${stamp(liveNow())} / ${stamp(d.hi)}`;
  checkPreview();
  const edge = liveEl("bufEdge"), play = liveEl("bufPlay"), mark = liveEl("bufMark");
  edge.hidden = !(ok && live.isLive);
  play.hidden = !ok;
  liveEl("bufPlayTail").hidden = !ok;
  mark.hidden = !(ok && live.start !== null);
  if (!ok) { syncRanges(null); liveEl("bufMade").replaceChildren(); liveEl("bufTicks").replaceChildren(); return; }
  const span = d.hi - d.lo;
  const now = liveNow();
  const outside = now < d.lo || now > d.hi;
  play.hidden = outside;
  liveEl("bufPlayTail").hidden = outside;
  const frac = Math.min(1, Math.max(0, (now - d.lo) / span));
  play.style.left = `${frac * 100}%`;
  liveEl("bufPlayTail").style.left = `calc(14px + (100% - 28px) * ${frac})`;
  if (live.start !== null) mark.style.left = `${Math.min(1, Math.max(0, (live.start - d.lo) / span)) * 100}%`;
  syncRanges(d);
  const host = liveEl("bufMade"), visible = made.filter(m => m.end > d.lo && m.start < d.hi);
  while (host.children.length > visible.length) host.lastChild.remove();
  visible.forEach((m, i) => {
    let marker = host.children[i];
    if (!marker) {
      marker = document.createElement("i");
      marker.title = "Already clipped";
      host.appendChild(marker);
    }
    place(marker, d, m.start, m.end);
  });
  const ticks = liveEl("bufTicks");
  while (ticks.children.length < 4) ticks.appendChild(document.createElement("span"));
  for (let k = 0; k < 4; k++) {
    const label = live.isLive ? (k === 3 ? "Live" : `${mmss(span * (3 - k) / 3)} ago`) : stamp(d.lo + span * k / 3);
    if (ticks.children[k].textContent !== label) ticks.children[k].textContent = label;
  }
}

// One box per selection, kept in place between paints so a drag in progress is not interrupted.
function syncRanges(d) {
  const host = liveEl("bufRanges"), want = d ? live.ranges : [];
  while (host.children.length > want.length) host.lastChild.remove();
  while (host.children.length < want.length) host.appendChild(rangeBox(host.children.length));
  want.forEach((r, i) => {
    const box = host.children[i];
    box.hidden = r.end <= d.lo || r.start >= d.hi;
    place(box, d, r.start, r.end);
    box.querySelector(".n").textContent = want.length > 1 ? i + 1 : "";
  });
}

function rangeBox(i) {
  const box = document.createElement("div");
  box.className = "buf-range";
  box.innerHTML = '<i class="h in" tabindex="0" role="slider" aria-label="Clip start"></i><i class="h out" tabindex="0" role="slider" aria-label="Clip end"></i><button type="button" class="p" aria-label="Play this selection" title="Play this selection">&#9654;</button><button type="button" class="x" aria-label="Remove this selection" title="Remove this selection">&times;</button><span class="n"></span>';
  const idx = () => [...box.parentNode.children].indexOf(box);
  box.querySelector(".in").onpointerdown = e => startDrag(idx(), "start", e);
  box.querySelector(".out").onpointerdown = e => startDrag(idx(), "end", e);
  box.querySelector(".x").onpointerdown = e => e.stopPropagation();
  box.querySelector(".p").onpointerdown = e => e.stopPropagation();
  box.querySelector(".p").onclick = e => { e.stopPropagation(); previewSelection(idx()); };
  box.querySelector(".x").onclick = e => { e.stopPropagation(); live.ranges = live.ranges.filter((_, k) => k !== idx()); paintBuffer(); };
  for (const which of ["in", "out"]) {
    const side = which === "in" ? "start" : "end";
    box.querySelector(`.${which}`).onkeydown = e => {
      const step = e.shiftKey ? 5 : 0.5, dir = e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0;
      if (!dir) return;
      e.preventDefault();
      e.stopPropagation();
      moveEdge(idx(), side, live.ranges[idx()][side] + dir * step);
    };
  }
  box.onpointerdown = e => e.stopPropagation();
  return box;
}

function moveEdge(i, side, v) {
  const r = live.ranges[i], gap = 0.5;
  const next = side === "start" ? {...r, start: Math.max(r.end - MAX_MARK, Math.min(v, r.end - gap))}
    : {...r, end: Math.min(r.start + MAX_MARK, Math.max(v, r.start + gap))};
  live.ranges = live.ranges.map((x, k) => (k === i ? {start: Number(next.start.toFixed(2)), end: Number(next.end.toFixed(2))} : x));
  paintBuffer();
}

// I sets where a clip starts and O where it ends. Each pair is one selection; Clip selection cuts them all.
function mark(which) {
  if (!live.player) return toast("Load a stream first");
  if (!domain()) return toast("Press play first");
  const t = Number(liveNow().toFixed(2));
  if (which === "start") {
    live.start = t;
  } else {
    if (live.start === null) return toast("Mark the in first");
    if (t - live.start < 0.5) return liveStatus("The out has to come after the in", true);
    if (t - live.start > MAX_MARK) return liveStatus(`Keep a clip under ${MAX_MARK / 60} minutes`, true);
    live.ranges = [...live.ranges, {start: live.start, end: t}].sort((x, y) => x.start - y.start);
    live.start = null;
  }
  liveStatus("");
  paintBuffer();
}

// The last few seconds that played, ending at the playhead.
function quick(secs) {
  if (!live.player) return toast("Load a stream first");
  const d = domain();
  if (!d) return toast("Press play first");
  const end = Number((liveNow() - (live.isLive ? PLAYER_LAG : 0)).toFixed(2));
  capture(Math.max(d.lo, end - secs), end);
}

// The selections are cut one after another, from the stream they were marked on even if another one is opened meanwhile.
async function liveClip() {
  if (!live.ranges.length) return;
  const todo = live.ranges, title = streamTitle();
  const from = {url: live.url, isLive: live.isLive, buffer: live.buffer, hi: (domain() || {}).hi, recStart: live.recStart};
  live.ranges = [];
  paintBuffer();
  for (const r of todo) {
    const now = Date.now() / 1000;
    const lo = from.isLive ? from.recStart || now - from.buffer : 0, hi = from.isLive ? now : from.hi || r.end + PAD;
    const lag = from.isLive ? PLAYER_LAG : 0;
    const start = Math.max(lo + (from.isLive ? 1 : 0), r.start - PAD - lag), end = Math.min(hi, r.end + PAD - lag);
    await capture(start, end, title, from);
  }
}

const liveToggle = () => {
  if (!live.player) return toast("Load a stream first");
  playerPaused() ? playerPlay() : playerPause();
};
const liveSeek = dt => live.player && !live.channel && playerSeek(Number(live.player.getCurrentTime()) + dt);
const seekTo = v => live.player && !live.channel && playerSeek(live.isLive && live.shift !== null ? v - live.shift : v);

// Clips still being cut, or that failed. A finished one is in the Clips panel instead.
let pending = [];
function paintPending() {
  const list = liveEl("liveCaps");
  list.hidden = !pending.length;
  list.replaceChildren(...pending.map(c => {
    const card = document.createElement("div");
    card.className = `cut${c.error ? " err" : ""}`;
    card.innerHTML = `<b>Live clip, ${c.secs.toFixed(1)}s</b><span class="st"></span>`;
    card.querySelector(".st").textContent = c.message;
    if (!c.error && c.pct) card.insertAdjacentHTML("beforeend", `<div class="prog" role="progressbar" aria-valuenow="${c.pct}" aria-valuemin="0" aria-valuemax="100"><i style="width:${c.pct}%"></i></div>`);
    if (c.error) {
      const x = document.createElement("button");
      x.textContent = "Dismiss";
      x.onclick = () => { pending = pending.filter(p => p !== c); paintPending(); };
      card.append(x);
    }
    return card;
  }));
}

const streamTitle = () => {
  if (live.channel) return live.id;
  try { return (live.player.getVideoData && live.player.getVideoData().title) || ""; } catch { return ""; }
};

async function thumbOf(v) {
  try {
    const res = await fetch(`/video-thumb/${v.id}.jpg`);
    if (!res.ok) return "";
    const blob = await res.blob();
    return await new Promise(ok => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = () => ok(""); r.readAsDataURL(blob); });
  } catch { return ""; }
}

// A finished cut becomes a clip in the project, the whole file, and lands in the clip bank (the Clips panel). If another
// project was opened while it was cutting, the clip stays in Media rather than going into the wrong one, and this says false.
async function addToProject(v, project) {
  const clip = {src: v.path, in: 0, out: v.duration, note: "", caption: "", speed: 1, volume: 1, fit: "fit", pan: 0.5, effect: "none", ramp: "none", freeze: 0, thumb: await thumbOf(v)};
  if (state.project.name !== project) return false;
  requestCut(clip);
  if (inShort()) {
    state.project = {...state.project, other: [...(state.project.other || []), clip]};
  } else {
    state.project = {...state.project, clips: [...state.project.clips, clip]};
    state.sel = state.project.clips.length - 1;
  }
  changed();
  return true;
}

async function capture(start, end, title = streamTitle(), from = live) {
  const cap = {secs: end - start, message: "Starting", error: false}, project = state.project.name;
  pending = [...pending, cap];
  made = [...made, {start, end}];
  paintPending();
  const update = patch => { Object.assign(cap, patch); paintPending(); };
  try {
    const range = from.isLive ? {live: true, wall_start: start, wall_end: end} : {start, end};
    let job = await api("/api/download", "POST", {url: from.url, title, project, ...range});
    while (job.state === "working") {
      update({message: `${job.message}${job.pct ? `, ${job.pct}%` : ""}`, pct: job.pct || 0});
      await new Promise(r => setTimeout(r, 800));
      job = await api(`/api/download/${job.id}`);
    }
    if (job.state !== "done") throw new Error(job.message || "The download failed");
    await refreshLibrary();
    const v = state.library.find(x => x.path === job.file);
    if (!v) throw new Error("The clip was cut but didn't show up in your library");
    if (!(v.duration > 0)) throw new Error("The clip came back empty");
    const same = await addToProject(v, project);
    pending = pending.filter(p => p !== cap);
    paintPending();
    toast(same ? "Clip added" : `Clip cut. It's in Media, since ${project} is no longer open`);
  } catch (err) {
    made = made.filter(m => m.start !== start || m.end !== end);
    update({error: true, message: err.message});
  }
}

// The handles and the bar: drag a handle to set the in or out, click the bar to jump the player there.
function valueAt(e) {
  const available = domain(), d = bufferView(available), r = liveEl("bufTrack").getBoundingClientRect();
  if (!d || !(r.width > 0)) return null;
  const time = d.lo + Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * (d.hi - d.lo);
  return Math.max(available.lo, Math.min(available.hi, time));
}
let dragging = null;
function startDrag(i, which, e) { dragging = {i, which}; e.preventDefault(); e.stopPropagation(); liveEl("bufTrack").setPointerCapture(e.pointerId); }
liveEl("bufTrack").onpointermove = e => {
  if (!dragging) return;
  const v = valueAt(e);
  if (v !== null) moveEdge(dragging.i, dragging.which, v);
};
liveEl("bufTrack").onpointerup = e => {
  if (dragging) { dragging = null; return; }
  const v = valueAt(e);
  if (v !== null) seekTo(v);
};

function enterLive() {
  if (typeof video !== "undefined") video.pause();
  document.body.classList.add("streaming");
  for (const id of ["liveClip", "liveQuick", "liveTc"]) liveEl(id).hidden = false;
  liveEl("srcName").textContent = "Stream";
  liveEl("srcMeta").textContent = "";
  liveEl("liveBtn").setAttribute("aria-pressed", "true");
  liveEl("liveBack").hidden = true;
  clearInterval(live.ticker);
  live.ticker = setInterval(() => { if (!dragging) paintBuffer(); }, 250);
  paintBuffer();
  paintPending();
}

// Leaving to edit a clip keeps the stream's link and your marks, so "Back to stream" picks up where you were. Closing drops them.
function leaveLive(forGood = false) {
  liveLoadToken += 1;
  clearInterval(live.ticker);
  live.resume = !forGood && live.url ? live.url : "";
  destroyLive();
  document.body.classList.remove("streaming");
  liveEl("liveBtn").setAttribute("aria-pressed", "false");
  liveEl("liveStage").replaceChildren();
  for (const id of ["liveClip", "liveQuick", "liveTc", "liveJump", "liveStage", "liveHint", "liveBadge"]) liveEl(id).hidden = true;
  previewEnd = null;
  liveEl("liveIn").classList.remove("pending");
  Object.assign(live, {isLive: false, shift: null});
  if (forGood) Object.assign(live, {start: null, ranges: []});
  liveEl("liveBack").hidden = !live.resume;
  renderLibrary();
  if (state.current) labelSource(state.current);
  else liveEl("srcName").textContent = "No video selected";
}

function backToStream() {
  const url = live.resume;
  enterLive();
  liveEl("liveUrl").value = url;
  liveEl("liveBar").requestSubmit();
}

function showLiveDialog() {
  if (!liveEl("liveUrl").value && live.resume) liveEl("liveUrl").value = live.resume;
  liveEl("liveDialogStatus").hidden = true;
  liveEl("liveEnd").hidden = !streaming() && !live.resume;
  liveEl("liveDialog").showModal();
  liveEl("liveUrl").focus();
}
liveEl("liveBtn").onclick = showLiveDialog;
liveEl("liveBack").onclick = backToStream;
liveEl("liveJump").onclick = jumpToLive;
liveEl("liveBar").onsubmit = e => {
  e.preventDefault();
  if (!liveSource(liveEl("liveUrl").value)) {
    const status = liveEl("liveDialogStatus");
    status.textContent = "Paste a YouTube link, or a Twitch channel or video link";
    status.hidden = false;
    if (!liveEl("liveDialog").open) liveEl("liveDialog").showModal();
    liveEl("liveUrl").focus();
    return;
  }
  liveEl("liveDialog").close();
  if (!streaming()) enterLive();
  openLive();
};
liveEl("liveClip").onclick = liveClip;
liveEl("liveQuick").onclick = e => { const b = e.target.closest("button[data-secs]"); if (b) quick(Number(b.dataset.secs)); };
liveEl("liveClose").onclick = () => liveEl("liveDialog").close();
liveEl("liveEnd").onclick = () => {
  liveEl("liveUrl").value = "";
  leaveLive(true);
  liveEl("liveDialog").close();
};

liveEl("liveIn").onclick = markIn;
liveEl("liveOut").onclick = markOut;
liveEl("liveBack5").onclick = () => seekBy(-5);
liveEl("liveFwd5").onclick = () => seekBy(5);
liveEl("livePlay").onclick = togglePlay;

liveEl("bufZoom").onclick = e => {
  const button = e.target.closest("button[data-window]");
  if (!button) return;
  live.viewSeconds = Number(button.dataset.window);
  for (const option of liveEl("bufZoom").querySelectorAll("button[data-window]")) option.setAttribute("aria-pressed", String(option === button));
  paintBuffer();
};

// Local bookmarks belong to the project and exact stream URL; they are not cut ranges.
function momentKey() { return `clipbench.moments:${state.project.name}:${live.url}`; }
function readMoments() {
  try { const rows = JSON.parse(localStorage.getItem(momentKey()) || "[]"); return Array.isArray(rows) ? rows.filter(x => Number.isFinite(x)) : []; } catch { return []; }
}
function paintMoments(available, visible) {
  const host = liveEl("liveMoments"), marks = readMoments();
  liveEl("liveMoment").disabled = !available || !live.player;
  liveEl("momentStatus").textContent = marks.length ? `${marks.length} moment${marks.length === 1 ? "" : "s"}` : "";
  const visibleMarks = marks.filter(t => available && visible && t >= available.lo && t <= available.hi && t >= visible.lo && t <= visible.hi);
  const key = JSON.stringify([momentKey(), visibleMarks]);
  if (host.dataset.key !== key) {
    host.dataset.key = key;
    host.replaceChildren(...visibleMarks.map(t => {
      const label = live.isLive || live.channel ? new Date(t * 1000).toLocaleTimeString() : stamp(t);
      const b = Object.assign(document.createElement("button"), {type: "button", className: "live-moment", textContent: "◆", title: `Moment ${label} · click to seek; Delete to remove`});
      b.setAttribute("aria-label", b.title);
      b.onpointerup = e => e.stopPropagation();
      b.onclick = () => { if (live.channel) toast("This Twitch channel cannot be rewound; use the recording to revisit this moment"); else seekTo(t); };
      const remove = () => { writeMoments(readMoments().filter(x => x !== t)); paintBuffer(); };
      b.oncontextmenu = e => { e.preventDefault(); remove(); };
      b.onkeydown = e => { if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); e.stopPropagation(); remove(); } };
      return b;
    }));
  }
  visibleMarks.forEach((t, i) => { host.children[i].style.left = `${(t - visible.lo) / (visible.hi - visible.lo) * 100}%`; });
}
function writeMoments(rows) {
  try { localStorage.setItem(momentKey(), JSON.stringify(rows.slice(-200))); return true; }
  catch { toast("Couldn't save this moment in browser storage"); return false; }
}
function markLiveMoment() {
  const d = domain();
  if (!d || !live.player) return;
  const now = liveNow();
  if (!Number.isFinite(now)) return;
  // At the live edge the player clock can sit a fraction of a second past the buffer's end.
  const t = Math.min(d.hi, Math.max(d.lo, now));
  if (Math.abs(t - now) > 0.5) return toast("This moment is outside the stream buffer");
  const marks = readMoments();
  if (!marks.some(x => Math.abs(x - t) < 1) && writeMoments([...marks, t])) toast("Moment marked");
  paintBuffer();
}
liveEl("liveMoment").onclick = markLiveMoment;
