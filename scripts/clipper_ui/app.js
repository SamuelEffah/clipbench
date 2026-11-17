"use strict";

const SHORT_LIMIT = 60, FRAME = 1 / 30, MIN_CLIP = 0.2, MIN_SPAN = 1;

const $ = id => document.getElementById(id);
let previewMuted = false;
let videos = [$("video"), makeSpareVideo()];
let video = videos[0];
const spare = () => (video === videos[0] ? videos[1] : videos[0]);
function makeSpareVideo() {
  const el = document.createElement("video");
  el.playsInline = true;
  el.preload = "auto";
  el.className = "off";
  $("video").after(el);
  return el;
}
const state = {favorites: [], library: [], current: null, project: {name: "untitled", hook: "", clips: []}, sel: -1, mode: "clip", pendingIn: null, pendingOut: null, pendingThumb: "", arrived: -1, chain: null, clipStop: null, channel: {}};

// Sources and Saved clips belong to the open project, so every request for them names it.
const projectQuery = () => `?project=${encodeURIComponent(state.project.name)}`;

const fmt = t => {
  const s = Math.max(0, t || 0), m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(2).padStart(5, "0")}`;
};
const speedOf = c => c.speed || 1;
const volumeOf = c => (c.volume === undefined ? 1 : c.volume);
// Speed ramps as (from, to, relative speed) over the clip's source time. Keep in step with RAMPS in make_short.py.
const RAMPS = {
  none: [[0, 1, 1]],
  hero: [[0, 0.3, 1], [0.3, 0.4, 0.7], [0.4, 0.6, 0.35], [0.6, 0.7, 0.7], [0.7, 1, 1]],
  slowdown: [[0, 0.4, 1.6], [0.4, 0.6, 1.1], [0.6, 0.8, 0.6], [0.8, 1, 0.35]],
  speedup: [[0, 0.2, 0.35], [0.2, 0.4, 0.6], [0.4, 0.6, 1.1], [0.6, 1, 1.6]],
};
const rampOf = c => c.ramp || "none";
const freezeOf = c => c.freeze || 0;
const stretches = c => RAMPS[rampOf(c)] || RAMPS.none;
const fractionAt = (c, t) => Math.min(1, Math.max(0, (t - c.in) / (c.out - c.in)));
function movingLen(c) {
  const pieces = stretches(c), span = c.out - c.in, speed = speedOf(c);
  if (pieces === RAMPS.none) return 0 + span / speed;
  return pieces.reduce((sum, [a, b, r]) => sum + (b - a) * span / (speed * r), 0);
}
const outLen = c => movingLen(c) + freezeOf(c);
function outTimeAt(c, t) {
  const span = c.out - c.in, u = Math.min(1, Math.max(0, (t - c.in) / span));
  if (u <= 0) return 0;
  const speed = speedOf(c);
  let acc = 0;
  for (const [a, b, r] of stretches(c)) {
    if (u <= a) break;
    acc += (Math.min(u, b) - a) * span / (speed * r);
  }
  return acc;
}
function speedAt(c, t) {
  const u = fractionAt(c, t), list = stretches(c);
  const piece = list.find(([a, b]) => u >= a && u < b) || list[list.length - 1];
  return speedOf(c) * piece[2];
}
function holdElapsed(c) {
  const cs = state.clipStop;
  return cs && cs.clip === c && cs.holding ? (performance.now() - cs.holding) / 1000 : 0;
}
// A player showing a saved clip file counts time from the clip's start, so data-base holds where that is in the source.
const baseOf = el => Number(el.dataset.base) || 0;
const tnow = (el = video) => el.currentTime + baseOf(el);
const clipPos = c => outTimeAt(c, tnow()) + holdElapsed(c);
const laneOf = c => (c && c.lane) || "top";
const isTop = c => laneOf(c) === "top";
// Layouts, as the renderer has them. Lanes fill the frame in reading order: split is two rows, three is one over two, four is a grid.
// "bottom" is the second lane, so a project can grow from Split to Four without its clips changing lane.
const LANES = ["top", "bottom", "third", "fourth"];
const SHAPES = {
  full: {name: "Fill", k: 1}, fill: {name: "Fill", k: 1}, fit: {name: "Fit", k: 1},
  split: {name: "Split", k: 2}, three: {name: "Three", k: 3}, four: {name: "Four", k: 4},
};
const templateOf = () => (SHAPES[state.project.template] ? state.project.template : "full");
const laneCount = () => SHAPES[templateOf()].k;
const splitOn = () => laneCount() > 1;
// Fill and Fit decide the framing for every clip; Full leaves it to each clip.
const fitOf = c => (state.project.template === "fill" || state.project.template === "fit" ? state.project.template : (c && c.fit) || "fit");
const total = () => state.project.clips.reduce((s, c) => s + (isTop(c) ? outLen(c) : 0), 0);

// While editing, project.clips is the list for the current mode (the clip bank in Clip mode, the Short's timeline in Short mode)
// and project.other holds the other one. Saving and rendering use the stored form, with clips as the timeline and bank beside it.
// Replace image payloads without mutating clips or undo snapshots.
function referencedThumbs(data, refs = rememberThumbnails.refs) {
  if (!refs?.size) return data;
  const convert = items => {
    if (!Array.isArray(items)) return items;
    let next = null;
    items.forEach((clip, i) => {
      const ref = refs.get(clip?.thumb);
      if (!ref) return;
      if (!next) next = items.slice();
      next[i] = {...clip, thumb: ref};
    });
    return next || items;
  };
  if (Array.isArray(data)) return convert(data);
  let next = data;
  for (const field of ["clips", "bank", "other"]) {
    const items = convert(data[field]);
    if (items !== data[field]) next = {...next, [field]: items};
  }
  return next;
}

function rememberThumbnails(payload, response) {
  const refs = rememberThumbnails.refs ||= new Map();
  if (!response?.thumbs?.length) return refs;
  const replacements = new Map(refs);
  let chars = rememberThumbnails.chars || 0;
  for (const {path, url} of response.thumbs) {
    let thumb = payload;
    for (const key of path) thumb = thumb?.[key];
    if (typeof thumb !== "string" || !thumb.startsWith("data:image/")
        || !/^\/clip-thumb\/[0-9a-f]{64}\.(jpg|png|webp)$/.test(url)) continue;
    replacements.set(thumb, url);
    if (refs.has(thumb)) { refs.delete(thumb); chars -= thumb.length; }
    if (thumb.length <= 4 * 1024 * 1024) { refs.set(thumb, url); chars += thumb.length; }
    while (refs.size > 256 || chars > 4 * 1024 * 1024) {
      const oldest = refs.keys().next().value;
      refs.delete(oldest);
      chars -= oldest.length;
    }
  }
  rememberThumbnails.chars = chars;
  return replacements;
}

const canon = (p = state.project, mode = state.mode) => {
  const {other, ...rest} = p;
  return referencedThumbs(mode === "clip" ? {...rest, clips: other || [], bank: p.clips} : {...rest, clips: p.clips, bank: other || []});
};
const orient = (c, mode) => {
  const {bank, ...rest} = c;
  return mode === "clip" ? {...rest, clips: bank || [], other: c.clips || []} : {...rest, clips: c.clips || [], other: bank || []};
};
// B-roll footage is added from its own panel and stays out of the Sources list.
const sourcesOf = () => state.library.filter(v => !v.broll);
let indexedLibrary = null, libraryByPath = new Map();
function byPath(path) {
  // Refreshes replace the library list; retain the source objects themselves so
  // changes to readiness and other metadata remain visible to every caller.
  if (indexedLibrary !== state.library) {
    const index = new Map();
    for (const v of state.library) {
      const key = v.path;
      if (!index.has(key)) index.set(key, v);
    }
    libraryByPath = index;
    indexedLibrary = state.library;
  }
  return libraryByPath.get(path);
}
const stripExt = name => name.replace(/\.[^.]+$/, "");
// A clip keeps its name after its source video is removed from the library.
const clipName = c => {
  const v = byPath(c.src);
  return stripExt(v ? v.name : String(c.src).split("/").pop());
};

let toastTimer;
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("on"), 2600);
}

async function api(path, method = "GET", body) {
  if (/^\/api\/(youtube(?:\/|$)|projects$|shorts$|video-stats$)/.test(path) || (method === "PUT" && path.startsWith("/api/project/"))) {
    let profile = state.profileId;
    if (!profile) { try { profile = localStorage.getItem('clipbench.profile'); } catch {} }
    const requestedProject = state.project.name === 'untitled' ? new URLSearchParams(location.search).get('project') : null;
    const query = new URLSearchParams({project: requestedProject || state.project.name, profile: profile || 'default'});
    path += (path.includes('?') ? '&' : '?') + query;
  }
  // Share only concurrent reads, scoped by the full project/profile URL. No
  // response cache: polling and subsequent library reads always stay fresh.
  const reads = api.reads || (api.reads = new Map());
  if (method === "GET" && reads.has(path)) return reads.get(path);
  const request = (async () => {
    // Job endpoints acknowledge quickly; their work is polled separately. Keep a
    // deadline through body consumption so a stalled connection cannot lock saves.
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(new TypeError("Request timed out. Please try again")), method === "GET" || method === "PUT" ? 30000 : 120000);
    try {
      const res = await fetch(path, {method, signal: controller.signal, headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined});
      let data;
      try { data = await res.json(); }
      catch (err) {
        if (controller.signal.aborted) throw controller.signal.reason;
        throw new Error(res.ok ? "Invalid server response. Please try again" : res.statusText || `Request failed (${res.status})`);
      }
      if (!res.ok) throw new Error(data?.error || data?.message || res.statusText);
      if (data === null || typeof data !== "object") throw new Error("Invalid server response. Please try again");
      return data;
    } finally {
      clearTimeout(deadline);
      if (method === "GET") reads.delete(path);
    }
  })();
  if (method === "GET") reads.set(path, request);
  return request;
}

// Each clip is also saved as its own small file on the server, so playing it never has to seek inside the whole source.
// A clip that couldn't be cut isn't asked for again for a while, since the preview asks on every frame.
const cutIds = new Map(), cutJobs = new Map(), cutFailed = new Map(), CUT_RETRY_MS = 30000;
const cutKey = c => `${c.src}|${c.in.toFixed(3)}|${c.out.toFixed(3)}`;
function requestCut(c) {
  const key = cutKey(c);
  if (cutIds.has(key)) return Promise.resolve(cutIds.get(key));
  if (cutJobs.has(key)) return cutJobs.get(key);
  if (Date.now() - (cutFailed.get(key) || -Infinity) < CUT_RETRY_MS) return Promise.resolve(null);
  const job = (async () => {
    try {
      let st = await api("/api/cut", "POST", {src: c.src, in: c.in, out: c.out});
      while (st.state === "working") {
        await new Promise(r => setTimeout(r, 600));
        st = await api(`/api/cut/${st.id}`);
      }
      if (st.state === "ready") cutIds.set(key, st.id);
      else cutFailed.set(key, Date.now());
      return cutIds.get(key) || null;
    } catch {
      cutFailed.set(key, Date.now());
      return null;
    } finally {
      cutJobs.delete(key);
    }
  })();
  cutJobs.set(key, job);
  return job;
}
// The file to play a clip from: its saved cut when there is one, otherwise the source.
function clipFile(c) {
  const cut = cutIds.get(cutKey(c));
  if (cut) return {id: `cut:${cut}`, url: `/cut/${cut}.mp4`, base: c.in};
  requestCut(c);
  const v = byPath(c.src);
  return v && v.ready ? {id: v.id, url: `/media/${v.id}`, base: 0} : null;
}
// The file a player already holds, when it can show this clip: the clip's own cut, or the source it was cut from. Keeping it
// means a scrub across a cut, or a clip following one from the same video, needs no load at all.
function fileLoadedIn(el, c) {
  if (!el || el.readyState < 1) return null;
  const cut = cutIds.get(cutKey(c));
  if (cut && el.dataset.id === `cut:${cut}`) return {id: `cut:${cut}`, url: `/cut/${cut}.mp4`, base: c.in};
  const v = byPath(c.src);
  return v && el.dataset.id === v.id ? {id: v.id, url: `/media/${v.id}`, base: 0} : null;
}
async function clipFileSoon(c, waitMs = 6000) {
  await Promise.race([requestCut(c), new Promise(r => setTimeout(r, waitMs))]);
  return clipFile(c);
}

let saveTimer, editCount = 0;
const HISTORY_LIMIT = 100, COALESCE_MS = 1000;
let edits = {past: [], future: []}, committed = state.project, lastEdit = {key: "", at: 0};

function resetHistory() {
  edits = {past: [], future: []};
  committed = state.project;
  lastEdit = {key: "", at: 0};
}

function recordEdit(key) {
  if (state.project === committed) return;
  const now = Date.now();
  const merge = key && key === lastEdit.key && now - lastEdit.at < COALESCE_MS;
  if (!merge) edits = {past: [...edits.past, committed].slice(-HISTORY_LIMIT), future: []};
  else edits = {...edits, future: []};
  committed = state.project;
  lastEdit = {key, at: now};
}

function changed(keepDom, key = "") {
  recordEdit(key);
  editCount++;
  unsaved = true;
  paintSaveState($("saved"), "saving");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 500);
  if (!keepDom) render();
  if (typeof scheduleRetime === "function") scheduleRetime();
}

function travel(from, to, label) {
  if (!from.length) return toast(`Nothing to ${label}`);
  const target = from[from.length - 1];
  edits = label === "undo" ? {past: from.slice(0, -1), future: [...to, state.project]} : {past: [...to, state.project], future: from.slice(0, -1)};
  state.project = target;
  committed = target;
  lastEdit = {key: "", at: 0};
  state.sel = Math.min(state.sel, target.clips.length - 1);
  editCount++;
  unsaved = true;
  paintSaveState($("saved"), "saving");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(save, 500);
  render();
  if (typeof paintSuggest === "function") paintSuggest();
}
const undo = () => travel(edits.past, edits.future, "undo");
const redo = () => travel(edits.future, edits.past, "redo");

function updateHistoryButtons() {
  $("undoBtn").disabled = !edits.past.length;
  $("redoBtn").disabled = !edits.future.length;
}
// Edits not yet on the server. A failed save is retried with a growing wait, and closing the tab asks first.
let unsaved = false, retryWait = 2000;
async function save() {
  save.pending = true;
  if (save.running) return save.running;
  save.running = (async () => {
    // A slow request is followed by one save of the latest state, not every edit.
    try {
      while (save.pending) {
        save.pending = false;
        await saveOnce();
      }
    } finally { save.running = null; }
  })();
  return save.running;
}
async function saveOnce() {
  const name = state.project.name, seen = editCount;
  paintSaveState($("saved"), "saving");
  try {
    const payload = canon();
    const response = await api(`/api/project/${name}`, "PUT", payload);
    const refs = rememberThumbnails(payload, response);
    if (state.project.name === name) {
      const before = state.project;
      state.project = referencedThumbs(before, refs);
      if (committed === before) committed = state.project;
    }
    retryWait = 2000;
    if (seen === editCount && state.project.name === name) {
      unsaved = false;
      paintSaveState($("saved"), "saved");
    }
    if (!projectNames.includes(name)) projectNames = [...projectNames, name];
  } catch (err) {
    const offline = err instanceof TypeError;
    paintSaveState($("saved"), offline ? "offline" : "failed", retryNow);
    if (retryWait === 2000) toast(offline ? "Can't reach the clip bench. Is it still running? Your edits are kept and will save when it's back" : `Couldn't save: ${err.message}`);
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, retryWait);
    retryWait = Math.min(retryWait * 2, 30000);
  }
}
function retryNow() {
  clearTimeout(saveTimer);
  retryWait = 2000;
  save();
}
// Saving stays visible until completion; success clears after a short confirmation.
const SAVE_STATES = {
  saving: {text: "Saving…", cls: "saving", title: "Saving your changes locally"},
  offline: {text: "Offline", cls: "bad", title: "The clip bench can't be reached. Your edits stay here and save when it's back. Click to try now"},
  failed: {text: "Not saved", cls: "bad", title: "The bench refused the save. Click to try now"},
  back: {text: "Saved", cls: "good", title: ""},
  saved: {text: "Saved", cls: "", title: ""},
};
const BACK_FOR = 3000;
let backTimer = 0;
function paintSaveState(el, kind, retry) {
  const shown = kind;
  const {text, cls, title} = SAVE_STATES[shown];
  const elements = typeof document === "undefined" ? [el] : [...document.querySelectorAll(".save-status")];
  for (const item of elements) {
    item.textContent = text;
    item.title = title;
    item.className = `saved save-status${cls ? ` ${cls}` : ""}`;
    item.hidden = false;
    item.onclick = cls === "bad" ? retry : null;
    item.disabled = cls !== "bad";
  }
  clearTimeout(backTimer);
  if (kind === "saved" || kind === "back") backTimer = setTimeout(() => {
    for (const item of elements) item.hidden = true;
  }, BACK_FOR);
  return shown;
}
// Save the open project now if it has edits waiting, before another one replaces it.
async function flushSave() {
  if (!unsaved) return;
  clearTimeout(saveTimer);
  await save();
}
window.addEventListener("beforeunload", e => {
  if (!unsaved) return;
  e.preventDefault();
  e.returnValue = "";
});

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function renderSourceWelcome() {
  const empty = !state.current && !streaming();
  document.body.classList.toggle("source-empty", empty);
}

function sourceRowsSummary(project, library) {
  const version = typeof editCount === "number" ? editCount : 0;
  const cached = sourceRowsSummary.cached;
  if (cached && cached.project === project && cached.library === library && cached.version === version &&
      cached.libraryLength === library.length && cached.clips === project.clips && cached.clipLength === project.clips.length &&
      cached.other === project.other && cached.otherLength === (project.other || []).length && cached.hidden === project.hiddenSources) return cached.result;
  const known = new Set(library.map(v => v.path)), counts = new Map(), missing = new Map(), bankCuts = new Set();
  for (const [clips, bank] of [[project.clips, true], [project.other || [], false]]) for (const c of clips) {
    const path = c.src;
    if (!path) continue;
    const key = `${path}|${c.in}|${c.out}`;
    if (!bank && bankCuts.has(key)) continue;
    if (bank) bankCuts.add(key);
    counts.set(path, (counts.get(path) || 0) + 1);
    if (!known.has(path)) {
      const row = missing.get(path) || {path, name: path.split(/[\\/]/).pop(), thumb: c.thumb || "", count: 0, end: 0};
      row.count++;
      row.end = Math.max(row.end, c.out || 0);
      missing.set(path, row);
    }
  }
  const hidden = new Set(project.hiddenSources || []);
  const result = {counts, missing: [...missing.values()].filter(v => !hidden.has(v.path))};
  sourceRowsSummary.cached = {project, library, version, libraryLength: library.length, clips: project.clips,
    clipLength: project.clips.length, other: project.other, otherLength: (project.other || []).length, hidden: project.hiddenSources, result};
  return result;
}

function removeMissingSource(path) {
  if (state.library.some(v => v.path === path)) return;
  const hidden = new Set(state.project.hiddenSources || []);
  if (hidden.has(path)) return;
  hidden.add(path);
  state.project = {...state.project, hiddenSources: [...hidden]};
  changed();
  toast("Unavailable source removed. Undo to restore");
}

const sourceDisplayName = name => name.replace(/\.[^.]+$/, "").replace(/_/g, " ");

function renderLibrary() {
  renderSourceWelcome();
  const box = $("library");
  const sources = sourcesOf();
  const {counts, missing} = sourceRowsSummary(state.project, state.library);
  $("tabMedia").innerHTML = `Sources <span class="num count">${sources.length + missing.length + Number(liveRowWanted())}</span>`;
  if ($("mediaPanel").hidden) return;
  box.innerHTML = "";
  if (!sources.length && !missing.length && !liveRowWanted()) {
    box.innerHTML = '<div class="empty">No videos yet.</div>';
    return;
  }
  sources.forEach(v => {
    const n = counts.get(v.path) || 0;
    const el = document.createElement("div");
    el.className = "media";
    el.tabIndex = 0;
    el.setAttribute("aria-current", !streaming() && state.current && state.current.id === v.id);
    el.innerHTML = `<div class="thumb"><img src="/video-thumb/${v.id}.jpg" alt="" loading="lazy" onerror="this.remove()"></div><div class="source-copy"><b title="${esc(v.name)}">${esc(sourceDisplayName(v.name))}</b><small class="source-meta num"><span>${fmt(v.duration)}</span><span>${n} clip${n === 1 ? "" : "s"}</span></small></div>` +
      `<button class="mediadel" aria-label="Remove ${esc(v.name)}" title="${v.remove === "unlist" ? "Remove from the list" : "Move to the Trash"}"><svg class="i"><use href="#trash"/></svg></button>`;
    el.querySelector(".mediadel").onclick = e => { e.stopPropagation(); askRemoveVideo(v); };
    el.onclick = () => openVideo(v);
    el.onkeydown = e => { if (e.target === el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openVideo(v); } };
    box.appendChild(el);
  });
  missing.forEach(v => {
    const el = document.createElement("div");
    el.className = "media source-missing";
    el.innerHTML = `<div class="thumb">${v.thumb ? `<img src="${esc(v.thumb)}" alt="" loading="lazy" onerror="this.remove()">` : '<svg class="i"><use href="#r-clips"/></svg>'}</div><div class="source-copy"><b title="${esc(v.name)}">${esc(sourceDisplayName(v.name))}</b><small class="source-meta"><span>Source unavailable</span><span class="num">${v.count} clip${v.count === 1 ? "" : "s"}</span></small><button type="button" class="source-locate" aria-label="Locate ${esc(v.name)}">Locate file</button></div><button type="button" class="mediadel" aria-label="Remove unavailable ${esc(v.name)}" title="Remove from Sources; keep saved clips"><svg class="i" aria-hidden="true"><use href="#trash"/></svg></button>`;
    el.querySelector(".source-locate").onclick = () => locateSource(v);
    el.querySelector(".mediadel").onclick = () => removeMissingSource(v.path);
    box.appendChild(el);
  });
  if (liveRowWanted()) box.appendChild(liveSourceRow());
}

// A stream you've loaded stays in the Sources list so you can come back to it.
const liveRowWanted = () => typeof live !== "undefined" && (streaming() || Boolean(live.resume));
function liveSourceRow() {
  const el = document.createElement("div");
  el.className = "media source-stream";
  el.tabIndex = 0;
  el.setAttribute("aria-current", streaming());
  const name = streaming() ? $("srcName").textContent : "Live stream";
  const status = !streaming() ? "Resume stream" : live.isLive ? "Live" : "Video";
  el.innerHTML = `<div class="thumb live"><svg class="i" aria-hidden="true"><use href="#live"/></svg></div><div class="source-copy"><b title="${esc(name)}">${esc(name)}</b><small class="source-meta"><span class="livetag${streaming() ? " is-live" : ""}">${status}</span><span>${live.kind === "twitch" ? "Twitch" : "YouTube"}</span></small></div>`;
  const open = () => { if (!streaming()) backToStream(); };
  el.onclick = open;
  el.onkeydown = e => { if (e.target === el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(); } };
  return el;
}

let removing = null;
function askRemoveVideo(v) {
  removing = v;
  const clips = [...state.project.clips, ...(state.project.other || [])].filter(c => c.src === v.path).length;
  const saved = state.favorites.filter(f => f.src === v.path).length;
  const unlist = v.remove === "unlist";
  const name = v.name.replace(/\.[^.]+$/, "");
  $("rmTitle").textContent = unlist ? "Remove this video from the list?" : "Move this video to the Trash?";
  $("rmName").textContent = name;
  $("rmMeta").textContent = `${fmt(v.duration)}, ${v.w} by ${v.h}`;
  const thumb = $("rmThumb");
  thumb.src = `/video-thumb/${v.id}.jpg`;
  thumb.onerror = () => thumb.removeAttribute("src");
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const facts = [[unlist ? "The file stays where it is. It just stops showing here." : "The file moves to your Trash, and you can put it back from there.", false]];
  if (clips || saved) {
    const where = [clips && `${plural(clips, "clip")} in this project`, saved && `${plural(saved, "saved clip")}`].filter(Boolean).join(" and ");
    facts.push([`${where} cut from it are saved as their own files, so they keep playing and rendering. You just can't trim them past what you cut.`, false]);
  } else {
    facts.push(["No clips use it.", false]);
  }
  $("rmFacts").replaceChildren(...facts.map(([text, warn]) => Object.assign(document.createElement("li"), {textContent: text, className: warn ? "warn" : ""})));
  $("rmGo").textContent = unlist ? "Remove from list" : "Move to Trash";
  $("rmDlg").showModal();
  $("rmCancel").focus();
}
$("rmCancel").onclick = () => $("rmDlg").close();
$("rmGo").onclick = () => {
  const v = removing;
  $("rmDlg").close();
  if (v) removeVideo(v);
};

// No video on screen: the elements let go of their source so the last frame does not linger over another project.
function dropVideo() {
  for (const el of videos) { el.pause(); el.removeAttribute("src"); el.load(); }
  state.current = null;
  renderSourceWelcome();
  state.clipStop = null;
  $("srcName").textContent = "No video selected";
  $("srcMeta").textContent = "";
}

async function removeVideo(v) {
  const used = [...state.project.clips, ...(state.project.other || []), ...state.favorites].some(c => c.src === v.path);
  if (used) toast("Saving its clips as files, then removing the video");
  try {
    await api(`/api/remove-video/${v.id}`, "POST", {});
    if (state.current && state.current.id === v.id) dropVideo();
    await refreshLibrary();
    toast(v.remove === "unlist" ? "Removed from the list" : "Moved to the Trash");
  } catch (err) {
    toast(`Couldn't remove it: ${err.message}`);
  }
}

let view = {s: 0, e: 0};
const dur = () => (state.current && state.current.duration) || 0;
const span = () => view.e - view.s;
const pos = t => (t - view.s) / span() * 100;
const zoomed = () => dur() > 0 && span() < dur() - 0.01;

function setView(s, e) {
  const d = dur();
  const sp = Math.min(Math.max(e - s, Math.min(MIN_SPAN, d)), d);
  const start = Math.min(Math.max(s, 0), d - sp);
  view = {s: start, e: start + sp};
}
const fitView = () => setView(0, dur());
const redrawView = () => { renderTimeline(); renderRuler(); };

function zoomAt(factor, anchor) {
  if (!dur()) return;
  const sp = span(), frac = (anchor - view.s) / sp;
  const next = Math.min(Math.max(sp * factor, MIN_SPAN), dur());
  setView(anchor - frac * next, anchor - frac * next + next);
  redrawView();
}
function panBy(dt) {
  setView(view.s + dt, view.e + dt);
  redrawView();
}
function ensureVisible(a, b) {
  if (!zoomed() || (a >= view.s && b <= view.e)) return;
  const sp = Math.max(span(), (b - a) * 1.4), mid = (a + b) / 2;
  setView(mid - sp / 2, mid + sp / 2);
}
function anchorTime() {
  const t = video.currentTime;
  return t >= view.s && t <= view.e ? t : (view.s + view.e) / 2;
}
function zoomToClip() {
  const c = state.project.clips[state.sel];
  if (zoomed()) fitView();
  else if (c && state.current && c.src === state.current.path) {
    const pad = Math.max((c.out - c.in) * 0.5, 1);
    setView(c.in - pad, c.out + pad);
  } else return toast("Select a clip on this video first");
  redrawView();
}
const timeFromX = (x, rect) => view.s + Math.min(1, Math.max(0, (x - rect.left) / rect.width)) * span();

const waves = {};
const waveCanvas = document.createElement("canvas");
waveCanvas.className = "wavecv";

async function loadWave(v) {
  if (waves[v.id] !== undefined) return;
  waves[v.id] = null;
  try {
    waves[v.id] = await api(`/api/wave/${v.id}`);
  } catch {
    // Forgotten, so opening the video again tries again.
    delete waves[v.id];
  }
  if (state.current && state.current.id === v.id) drawWave();
}

// A scan that failed is forgotten, so opening the video again tries it again.
const scenes = {}, sceneFailed = new Set();

async function loadScenes(v) {
  if (scenes[v.id] !== undefined) return;
  scenes[v.id] = null;
  sceneFailed.delete(v.id);
  try {
    let job = await api(`/api/scenes/${v.id}`);
    while (job.state === "working") {
      await new Promise(r => setTimeout(r, 1500));
      job = await api(`/api/scenes/${v.id}`);
    }
    if (job.state !== "ready") throw new Error(job.message);
    scenes[v.id] = job.scenes;
  } catch {
    delete scenes[v.id];
    sceneFailed.add(v.id);
  }
  if (state.current && state.current.id === v.id) renderTimeline();
}

function sceneList() {
  return (state.current && scenes[state.current.id]) || [];
}

function jumpScene(dir) {
  if (!state.current) return toast("Pick a video first");
  const list = sceneList();
  const id = state.current.id;
  if (!list.length) return toast(scenes[id] === null ? "Still scanning for scene cuts" : sceneFailed.has(id) ? "Couldn't scan this video for scene cuts. Open it again to retry" : "No scene cuts found");
  const t = video.currentTime;
  const target = dir > 0 ? list.find(s => s > t + 0.05) : [...list].reverse().find(s => s < t - 0.05);
  if (target === undefined) return toast(dir > 0 ? "No more scene cuts" : "No earlier scene cuts");
  video.currentTime = target;
  if (zoomed() && (target < view.s || target > view.e)) { ensureVisible(target, target); redrawView(); }
  updateTime();
}

function sceneMarks() {
  const frag = document.createDocumentFragment();
  const inView = sceneList().filter(t => t >= view.s && t <= view.e);
  if (inView.length > 400) return frag;
  for (const t of inView) {
    const m = document.createElement("i");
    m.className = "scene";
    m.style.left = `${pos(t)}%`;
    frag.appendChild(m);
  }
  return frag;
}

// The strip has two lanes, as the Short timeline does: the clips' pictures on top and the sound under them. The waveform is drawn
// in the sound lane the way a clip's sound is in the Short, with the part each clip keeps lit and a muted clip flat.
const VIDEO_LANE = 46, LANE_GAP = 4, BAR_W = 2, BAR_STEP = 3;
// Volume and fade edits redraw the same waveform dimensions. Reuse its backing
// store, clearing in pixel coordinates before applying the display scale again.
// Keep timeline waveform work near the viewport without removing drag or keyboard targets.
function paintWhenVisible(el, paint) {
  const job = el._deferredPaint ||= {paint, done: false};
  if (job.done || job.running) return;
  job.paint = paint;
  if (el.isConnected === false) return;
  const finish = target => {
    const pending = target._deferredPaint;
    if (!pending || pending.done || pending.running || target.isConnected === false) return;
    pending.running = true;
    const complete = () => {
      pending.running = false;
      pending.done = target.isConnected !== false;
      if (pending.done) pending.paint = null;
    };
    try {
      const result = pending.paint();
      if (result && typeof result.then === "function") result.then(complete, err => {
        pending.running = false;
        console.error("Waveform paint failed", err);
      });
      else complete();
    } catch (err) { pending.running = false; throw err; }
  };
  if (typeof IntersectionObserver !== "function") { finish(el); return; }
  if (!paintWhenVisible.observer) {
    const pending = new Set();
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.target.isConnected || entry.isIntersecting) {
          observer.unobserve(entry.target);
          pending.delete(entry.target);
          if (entry.isIntersecting) finish(entry.target);
        }
      }
    }, {root: el.closest?.(".stl-body") || null, rootMargin: "120px"});
    paintWhenVisible.observer = observer;
    paintWhenVisible.pending = pending;
    paintWhenVisible.prune = () => {
      for (const target of pending) if (!target.isConnected) {
        observer.unobserve(target);
        pending.delete(target);
      }
    };
  }
  if (!paintWhenVisible.pending.has(el)) {
    paintWhenVisible.pending.add(el);
    paintWhenVisible.observer.observe(el);
  }
}

function prepareWaveCanvas(canvas, w, h, ratio) {
  const width = Math.round(w * ratio), height = Math.round(h * ratio);
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  const g = canvas.getContext("2d");
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, canvas.width, canvas.height);
  g.scale(ratio, ratio);
  return g;
}

// Waveform bars advance in time. Keep active ranges in original clip order so overlaps
// use the same first clip as a list search, without searching the list for every bar.
function waveClipLookup(clips) {
  const pending = clips.filter(({c}) => c.in < c.out).sort((a, b) => a.c.in - b.c.in);
  const active = [];
  let next = 0;
  return t => {
    while (next < pending.length && pending[next].c.in <= t) {
      const item = pending[next++];
      if (!(t < item.c.out)) continue;
      let n = active.length;
      active.push(item);
      while (n > 0) {
        const parent = (n - 1) >> 1;
        if (active[parent].i <= item.i) break;
        active[n] = active[parent];
        n = parent;
      }
      active[n] = item;
    }
    while (active.length && !(t < active[0].c.out)) {
      const last = active.pop();
      if (!active.length) break;
      let n = 0;
      while (n * 2 + 1 < active.length) {
        let child = n * 2 + 1;
        if (child + 1 < active.length && active[child + 1].i < active[child].i) child++;
        if (last.i <= active[child].i) break;
        active[n] = active[child];
        n = child;
      }
      active[n] = last;
    }
    return active[0];
  };
}

function drawWave() {
  const strip = $("strip"), v = state.current, w = strip.clientWidth, h = strip.clientHeight - VIDEO_LANE - LANE_GAP;
  if (!w || h <= 0) return;
  const dpr = window.devicePixelRatio || 1;
  if (waveCanvas.width !== Math.round(w * dpr) || waveCanvas.height !== Math.round(h * dpr)) {
    waveCanvas.width = Math.round(w * dpr);
    waveCanvas.height = Math.round(h * dpr);
  }
  waveCanvas.style.width = `${w}px`;
  waveCanvas.style.height = `${h}px`;
  waveCanvas.style.top = `${VIDEO_LANE + LANE_GAP}px`;
  const ctx = waveCanvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const wave = v && waves[v.id];
  if (!wave || !wave.peaks.length || !span()) return;
  const css = getComputedStyle(document.documentElement);
  const warn = css.getPropertyValue("--warn").trim() || "#e5a24a";
  const mine = state.project.clips.map((c, i) => ({c, i})).filter(({c}) => c.src === v.path);
  const clipAt = waveClipLookup(mine);
  const per = wave.per_sec, mid = h / 2, sp = span();
  // A faint wash under each clip's part, brighter for the selected one, like a clip's sound row in the Short.
  for (const {c, i} of mine) {
    const x0 = Math.max(0, (c.in - view.s) / sp * w), x1 = Math.min(w, (c.out - view.s) / sp * w);
    if (x1 <= x0) continue;
    ctx.fillStyle = i === state.sel ? "rgba(111,155,255,.22)" : "rgba(111,155,255,.1)";
    ctx.fillRect(x0, 0, x1 - x0, h);
  }
  for (let x = 0; x < w; x += BAR_STEP) {
    const t0 = view.s + (x / w) * sp, t1 = view.s + (Math.min(w, x + BAR_STEP) / w) * sp;
    const a = Math.floor(t0 * per), b = Math.min(wave.peaks.length - 1, Math.max(a, Math.ceil(t1 * per) - 1));
    const tm = (t0 + t1) / 2;
    const hit = clipAt(tm);
    const gain = hit ? (volumeOf(hit.c) === 0 ? 0 : Math.min(1, volumeOf(hit.c))) : 1;
    let peak = 0;
    if (gain !== 0) for (let k = a; k <= b; k++) if (wave.peaks[k] > peak) peak = wave.peaks[k];
    const bar = Math.max(1.5, (peak / 255) * gain * (h - 2));
    ctx.fillStyle = !hit ? "rgba(232,224,210,.22)" : gain === 0 ? "rgba(232,224,210,.2)" : "rgba(232,224,210,.78)";
    ctx.fillRect(x, mid - bar / 2, BAR_W, bar);
    if (hit && gain === 0) {
      ctx.fillStyle = warn;
      ctx.fillRect(x, mid - 0.75, BAR_STEP, 1.5);
    }
  }
}
new ResizeObserver(drawWave).observe($("strip"));

function renderTimeline() {
  if (state.mode === "short") return;
  const v = state.current;
  const strip = $("strip");
  strip.replaceChildren(waveCanvas);
  strip.classList.toggle("empty", !v);
  renderNav();
  if (!v) return;
  strip.appendChild(sceneMarks());
  state.project.clips.forEach((c, i) => {
    if (c.src !== v.path) return;
    const d = document.createElement("div");
    d.className = "sel-range" + (i === state.sel ? "" : " dim");
    placeRange(d, c);
    d.tabIndex = 0;
    d.setAttribute("aria-label", `Mark for clip ${i + 1}`);
    if (c.thumb) d.append(Object.assign(document.createElement("img"), {alt: "", src: c.thumb}));
    d.append(Object.assign(document.createElement("b"), {textContent: i + 1}), Object.assign(document.createElement("span"), {className: "rlen num", textContent: `${outLen(c).toFixed(1)}s`}));
    d.onclick = e => { e.stopPropagation(); select(i); video.currentTime = c.in; };
    d.ondragover = e => { if (isEffectDrag(e)) { e.preventDefault(); d.classList.add("fx-over"); } };
    d.ondragleave = () => d.classList.remove("fx-over");
    d.ondrop = e => {
      if (!isEffectDrag(e)) return;
      e.preventDefault();
      d.classList.remove("fx-over");
      dropEffect(e, i);
    };
    if (i === state.sel) {
      // The sound's own level line and readout sit in the sound lane, under the picture.
      const sound = document.createElement("div");
      sound.className = "aud-sel";
      placeRange(sound, c);
      sound.append(volumeLine(c, i, sound), clipChip(c));
      d._mate = sound;
      strip.appendChild(sound);
      for (const side of ["in", "out"]) {
        const h = document.createElement("i");
        h.className = `h ${side}`;
        h.title = side === "in" ? "Drag to trim the start" : "Drag to trim the end";
        h.onpointerdown = e => startTrim(e, i, side, d);
        h.onclick = e => e.stopPropagation();
        d.appendChild(h);
      }
    }
    strip.appendChild(d);
  });
  if (state.pendingIn !== null) {
    const fill = document.createElement("div");
    fill.className = "range pending";
    fill.id = "pendfill";
    strip.append(fill);
  }
  const ph = document.createElement("div");
  ph.className = "playhead";
  ph.id = "playhead";
  ph.onpointerdown = scrubClip;
  strip.appendChild(ph);
  placePlayhead();
  if (typeof paintSuggestionRange === "function") paintSuggestionRange();
  drawWave();
}

const volumeTop = v => `${(1 - Math.min(v, MAX_VOLUME) / MAX_VOLUME) * 100}%`;

function chipText(c) {
  const parts = [`Sound ${percent(volumeOf(c))}`];
  if (speedOf(c) !== 1) parts.push(`${speedOf(c)}x`);
  return parts.join(", ");
}

function clipChip(c) {
  const chip = document.createElement("span");
  chip.className = "chip";
  chip.textContent = chipText(c);
  return chip;
}

function volumeLine(c, i, rangeEl) {
  const line = document.createElement("i");
  line.className = "vol" + (volumeOf(c) === 0 ? " off" : "");
  line.style.top = volumeTop(volumeOf(c));
  line.title = "Drag up or down to change this clip's sound. Double-click for normal.";
  line.onclick = e => e.stopPropagation();
  line.ondblclick = () => setClipField(i, {volume: 1});
  line.onpointerdown = e => {
    e.preventDefault();
    e.stopPropagation();
    line.setPointerCapture(e.pointerId);
    const rect = rangeEl.getBoundingClientRect();
    const onMove = ev => {
      const volume = clampVolume((1 - Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height))) * MAX_VOLUME);
      const cur = state.project.clips[i];
      if (volume === volumeOf(cur)) return;
      const next = {...cur, volume};
      state.project = {...state.project, clips: state.project.clips.map((x, n) => (n === i ? next : x))};
      line.style.top = volumeTop(volume);
      line.classList.toggle("off", volume === 0);
      rangeEl.querySelector(".chip").textContent = chipText(next);
      applyLiveSound(next);
      drawWave();
    };
    const onUp = () => {
      line.removeEventListener("pointermove", onMove);
      line.removeEventListener("pointerup", onUp);
      line.removeEventListener("pointercancel", onUp);
      changed();
    };
    line.addEventListener("pointermove", onMove);
    line.addEventListener("pointerup", onUp);
    line.addEventListener("pointercancel", onUp);
  };
  return line;
}

function placeRange(el, c) {
  el.style.left = `${pos(c.in)}%`;
  el.style.width = `${Math.max(0.4, (c.out - c.in) / span() * 100)}%`;
  if (el._mate) placeRange(el._mate, c);
}

function renderNav() {
  const nav = $("nav");
  nav.hidden = !zoomed();
  if (nav.hidden) return;
  const thumb = $("navThumb");
  thumb.style.left = `${view.s / dur() * 100}%`;
  thumb.style.width = `${span() / dur() * 100}%`;
}

const SNAP_PX = 8;

function snapPoints(i) {
  const v = state.current;
  const edges = state.project.clips.flatMap((c, n) => (n !== i && c.src === v.path ? [c.in, c.out] : []));
  return [0, v.duration, ...edges, ...sceneList()];
}

function nearest(points, t) {
  return points.reduce((best, p) => (best === null || Math.abs(p - t) < Math.abs(best - t) ? p : best), null);
}

function startTrim(e, i, side, el) {
  e.preventDefault();
  e.stopPropagation();
  const handle = e.currentTarget, v = state.current, rect = $("strip").getBoundingClientRect();
  handle.setPointerCapture(e.pointerId);
  trimming = true;
  const points = snapPoints(i), reach = SNAP_PX / rect.width * span();
  const guide = document.createElement("i");
  guide.className = "snapline";
  guide.hidden = true;
  $("strip").appendChild(guide);
  const onMove = ev => {
    const raw = timeFromX(ev.clientX, rect), near = nearest(points, raw);
    const snapped = !ev.altKey && near !== null && Math.abs(near - raw) <= reach;
    const t = snapped ? near : Math.round(raw / FRAME) * FRAME;
    guide.hidden = !snapped;
    if (snapped) guide.style.left = `${pos(near)}%`;
    const cur = state.project.clips[i];
    const next = side === "in"
      ? {...cur, in: Math.min(Math.max(t, 0), cur.out - MIN_CLIP)}
      : {...cur, out: Math.max(Math.min(t, v.duration), cur.in + MIN_CLIP)};
    state.project = {...state.project, clips: state.project.clips.map((c, n) => (n === i ? next : c))};
    placeRange(el, next);
    drawWave();
    video.currentTime = side === "in" ? next.in : Math.max(next.out - FRAME, next.in);
    updateTime();
  };
  const onUp = () => {
    handle.removeEventListener("pointermove", onMove);
    handle.removeEventListener("pointerup", onUp);
    handle.removeEventListener("pointercancel", onUp);
    trimming = false;
    guide.remove();
    changed(false, `trim:${i}`);
    if (side !== "in") return;
    const at = state.project.clips[i].in;
    if (video.seeking) video.addEventListener("seeked", () => retakeThumb(i, at), {once: true});
    else retakeThumb(i, at);
  };
  handle.addEventListener("pointermove", onMove);
  handle.addEventListener("pointerup", onUp);
  handle.addEventListener("pointercancel", onUp);
}
let trimming = false;

// The new first frame, taken only while the video still shows it, and folded into the trim's undo step.
function retakeThumb(i, at) {
  const c = state.project.clips[i];
  if (!c || c.in !== at || !state.current || state.current.path !== c.src || Math.abs(video.currentTime - at) > FRAME) return;
  const thumb = captureThumb();
  if (!thumb || thumb === c.thumb) return;
  state.project = {...state.project, clips: state.project.clips.map((x, n) => (n === i ? {...x, thumb} : x))};
  changed(false, `trim:${i}`);
}

function toggleMute() {
  const c = state.project.clips[state.sel];
  if (!c) return toast("Select a clip first");
  setClipField(state.sel, {volume: volumeOf(c) === 0 ? 1 : 0});
  toast(volumeOf(c) === 0 ? `Clip ${state.sel + 1} sound on` : `Clip ${state.sel + 1} muted`);
}

function trimSel(side) {
  const c = state.project.clips[state.sel], v = state.current;
  if (!c || !v) return toast("Select a clip first");
  if (c.src !== v.path) return toast("Open that clip's video first");
  const t = video.currentTime;
  if (side === "in" ? t > c.out - MIN_CLIP : t < c.in + MIN_CLIP) return toast(side === "in" ? "In must be before out" : "Out must be after in");
  const next = side === "in" ? {...c, in: t, thumb: captureThumb() || c.thumb} : {...c, out: t};
  state.project = {...state.project, clips: state.project.clips.map((x, n) => (n === state.sel ? next : x))};
  changed();
}

// Playback runs on every animation frame. Leave unchanged DOM values alone,
// especially while paused, so text nodes and SVG icons are not rebuilt at 60Hz.
function setPlaybackValue(target, key, value) {
  if (target[key] !== value) target[key] = value;
}

function placePlayhead() {
  const ph = $("playhead");
  if (ph && state.current && state.current.duration) setPlaybackValue(ph.style, "left", `${pos(video.currentTime)}%`);
  const top = $("phRuler"), shown = Boolean(state.current && state.current.duration);
  setPlaybackValue(top, "hidden", !shown);
  if (shown) setPlaybackValue(top.style, "left", `calc(14px + (100% - 28px) * ${pos(video.currentTime) / 100})`);
  const fill = $("pendfill");
  if (fill && state.pendingIn !== null) {
    const end = state.pendingOut !== null ? state.pendingOut : video.currentTime;
    const a = Math.max(Math.min(state.pendingIn, end), view.s), b = Math.min(Math.max(state.pendingIn, end), view.e);
    setPlaybackValue(fill.style, "left", `${pos(a)}%`);
    setPlaybackValue(fill.style, "width", `${Math.max(0, pos(b) - pos(a))}%`);
  }
}

function renderRuler() {
  if (state.mode === "short") return;
  const ruler = $("ruler");
  ruler.innerHTML = "";
  const v = state.current;
  if (!v || !v.duration) return;
  const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];
  const step = steps.find(s => span() / s <= 5) || 1800;
  const at = s => {
    const e = document.createElement("span");
    e.style.left = `${pos(s)}%`;
    const m = Math.floor(s / 60), sec = s - m * 60;
    e.textContent = `${m}:${String(Math.floor(sec)).padStart(2, "0")}`;
    return e;
  };
  for (let s = Math.ceil(view.s / step) * step; s < view.e - step * 0.35; s += step) ruler.appendChild(at(s));
  const end = at(view.e);
  end.style.left = "100%";
  ruler.appendChild(end);
}

// Only a card dragged within the tray reorders it; Saved clips, sounds and files carry their own types.
const TRAY_MIME = "application/x-tray";
function renderTray() {
  if (state.mode === "short") return renderBank();
  const tray = $("tray");
  tray.innerHTML = "";
  const clips = state.project.clips;
  if (!clips.length) {
    tray.replaceChildren();
    return;
  }
  const isSaved = momentLookup(state.favorites);
  const clearDrop = () => tray.querySelectorAll(".drop-before,.drop-after").forEach(e => e.classList.remove("drop-before", "drop-after"));
  const previousCache = renderTray.cache || new WeakMap();
  const cache = renderTray.cache = new WeakMap();
  clips.forEach((c, i) => {
    const v = byPath(c.src), saved = isSaved(c);
    const key = [i, i === state.sel, i === state.arrived, v, v?.name, saved,
      c.src, c.in, c.out, c.thumb, c.caption, outLen(c)];
    const previous = previousCache.get(c);
    if (previous && key.every((value, n) => value === previous.key[n])) {
      cache.set(c, previous);
      tray.appendChild(previous.node);
      return;
    }
    const d = document.createElement("div");
    d.className = "crow plain" + (i === state.sel ? " sel" : "") + (i === state.arrived ? " new" : "");
    d.tabIndex = 0;
    d.draggable = true;
    const pic = c.thumb ? `<img alt="" src="${c.thumb}">` : "";
    const where = v ? `${esc(v.name.replace(/\.[^.]+$/, ""))} at ${mmss(c.in)}` : "Missing video";
    d.innerHTML = `<div class="pic">${pic}<span class="dur num">${outLen(c).toFixed(1)}s</span></div>` +
      `<div class="cap"><p${c.caption ? "" : ' class="none"'}>${c.caption ? esc(c.caption) : "No caption yet"}</p><small class="num">${saved ? '<svg class="i"><use href="#star"/></svg>' : ""}${where}</small></div>` +
      `<div class="hovbar">` +
      `<button class="act del star${saved ? " on" : ""}" data-act="fav" aria-label="Save clip ${i + 1} to favorites" title="Save to favorites"><svg class="i"><use href="#star"/></svg></button>` +
      `<button class="act del" data-act="dup" aria-label="Duplicate clip ${i + 1}" title="Duplicate clip"><svg class="i"><use href="#copy"/></svg></button>` +
      `<button class="act del" data-act="del" aria-label="Remove clip ${i + 1}" title="Remove clip"><svg class="i"><use href="#trash"/></svg></button></div>`;
    d.querySelector('[data-act="fav"]').onclick = e => { e.stopPropagation(); toggleFavorite(i); };
    d.querySelector('[data-act="dup"]').onclick = e => { e.stopPropagation(); duplicateClip(i); };
    d.querySelector('[data-act="del"]').onclick = e => { e.stopPropagation(); removeClip(i); };
    d.onclick = () => select(i, true);
    d.onkeydown = e => {
      if (e.target === d && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select(i, true); }
      if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); move(i, i + (e.key === "ArrowUp" ? -1 : 1)); }
    };
    d.ondragstart = e => { e.dataTransfer.setData(TRAY_MIME, String(i)); e.dataTransfer.effectAllowed = "move"; };
    d.ondragover = e => {
      if (isEffectDrag(e)) {
        e.preventDefault();
        return d.classList.add("fx-over");
      }
      if (!e.dataTransfer.types.includes(TRAY_MIME)) return;
      e.preventDefault();
      clearDrop();
      const r = d.getBoundingClientRect();
      d.classList.add(e.clientY < r.top + r.height / 2 ? "drop-before" : "drop-after");
    };
    d.ondragleave = () => d.classList.remove("drop-before", "drop-after", "fx-over");
    d.ondrop = e => {
      e.preventDefault();
      if (isEffectDrag(e)) {
        d.classList.remove("fx-over");
        return dropEffect(e, i);
      }
      const raw = e.dataTransfer.getData(TRAY_MIME);
      const r = d.getBoundingClientRect();
      const after = e.clientY >= r.top + r.height / 2;
      clearDrop();
      if (!raw) return;
      const from = Number(raw);
      let to = i + (after ? 1 : 0);
      if (from < to) to -= 1;
      move(from, to);
    };
    cache.set(c, {key, node: d});
    tray.appendChild(d);
  });
  const active = tray.querySelector(".crow.sel");
  if (active) active.scrollIntoView({block: "nearest"});
}

// Quick transitions that suit Shorts. Keep in step with TRANSITIONS in make_short.py.
const TRANSITIONS = [["flash", "Flash"], ["dip", "Dip to black"], ["swipe_left", "Swipe left"], ["swipe_up", "Swipe up"],
                     ["zoom", "Zoom"], ["zoom_in", "Zoom in"], ["zoom_punch", "Zoom punch"], ["zoom_out", "Zoom out"], ["whip", "Whip"], ["pixelize", "Pixelize"], ["iris", "Iris"], ["streak", "Streak"], ["clock", "Clock wipe"], ["glitch", "Glitch"]];
const TRANSITION_NAMES = Object.fromEntries(TRANSITIONS);
const transitionOf = c => c.transition || "none";
const tlenOf = c => c.tlen || 0.3;
const TRANSITION_MIME = "application/x-transition";
const isTransitionDrag = e => Array.from(e.dataTransfer.types || []).includes(TRANSITION_MIME);

// Seconds a clip overlaps the one before it in its lane. Mirrors seam_overlaps in make_short.py.
function seamOverlap(prev, c, previousLength, currentLength) {
  if (!prev || transitionOf(c) === "none") return 0;
  const d = Math.min(tlenOf(c), (currentLength ?? outLen(c)) / 2, (previousLength ?? outLen(prev)) / 2);
  return d >= 0.05 ? Math.round(d * 1000) / 1000 : 0;
}

// Seconds the first clip of a lane takes to appear out of black. Mirrors intro_length in make_short.py.
function introLength(c) {
  if (transitionOf(c) === "none") return 0;
  const d = Math.min(tlenOf(c), outLen(c) / 2);
  return d >= 0.05 ? Math.round(d * 1000) / 1000 : 0;
}

const effectOf = c => c.effect || "none";
const EFFECT_MIME = "application/x-effect";
const isEffectDrag = e => Array.from(e.dataTransfer.types || []).includes(EFFECT_MIME);
function firstInLane(i) {
  const clips = state.project.clips;
  return !clips.slice(0, i).some(c => laneOf(c) === laneOf(clips[i]));
}

function applyPatch(i, patch, label) {
  if (patch.transition !== undefined) {
    if (!state.project.clips[i]) return toast("Select a clip first");
    setClipField(i, patch);
    if (patch.transition === "none") return toast("Hard cut");
    return toast(firstInLane(i) ? `${label} from black into clip ${i + 1}` : `${label} into clip ${i + 1}`);
  }
  if (!state.project.clips[i]) return toast("Select a clip first");
  setClipField(i, patch);
  toast(`${label} on clip ${i + 1}`);
}

function dropEffect(e, i) {
  try {
    const {patch, label} = JSON.parse(e.dataTransfer.getData(EFFECT_MIME));
    applyPatch(i, patch, label);
  } catch {
    toast("Couldn't apply that effect");
  }
}

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const MAX_VOLUME = 1.5, VOLUME_STEP = 0.05;
const clampVolume = v => Number(Math.min(MAX_VOLUME, Math.max(0, Math.round(v / VOLUME_STEP) * VOLUME_STEP)).toFixed(2));
const percent = v => `${Math.round(v * 100)}%`;

function setClipField(i, patch, key) {
  state.project = {...state.project, clips: state.project.clips.map((c, n) => (n === i ? {...c, ...patch} : c))};
  changed(false, key);
}

function applyLiveSound(c) {
  if (!state.clipStop) return;
  video.volume = Math.min(1, volumeOf(c));
  video.muted = previewMuted || playVolume(c) === 0;
}

function nudgeVolume(dir) {
  const c = state.project.clips[state.sel];
  if (!c) return toast("Select a clip first");
  const volume = clampVolume(volumeOf(c) + dir * 0.1);
  setClipField(state.sel, {volume}, `volume:${state.sel}`);
  applyLiveSound({...c, volume});
}

function bumpSpeed(dir) {
  const c = state.project.clips[state.sel];
  if (!c) return toast("Select a clip first");
  const at = SPEEDS.reduce((best, s, n) => (Math.abs(s - speedOf(c)) < Math.abs(SPEEDS[best] - speedOf(c)) ? n : best), 0);
  const speed = SPEEDS[Math.min(SPEEDS.length - 1, Math.max(0, at + dir))];
  setClipField(state.sel, {speed});
  toast(`Clip ${state.sel + 1} at ${speed === 1 ? "normal speed" : `${speed}x`}`);
}

function setCaptionAt(at, text, key) {
  state.project = {...state.project, clips: state.project.clips.map((c, n) => (n === at ? {...c, caption: text, ...(isSynced(c) ? {words: retime(c.heard || c.words, text)} : {})} : c))};
  changed(true, key);
}

function captionField(i) {
  const box = document.createElement("div");
  box.className = "capbox";
  const input = document.createElement("input");
  input.className = "capin";
  input.placeholder = "Caption on this clip (optional)";
  input.setAttribute("aria-label", `Caption for clip ${i + 1}`);
  input.value = state.project.clips[i].caption || "";
  const setCaption = (text, key, at = i) => setCaptionAt(at, text, key);
  input.oninput = () => setCaption(input.value, `caption:${i}`);
  input.onchange = () => render();
  input.onkeydown = e => { if (e.key === "Enter") input.blur(); };
  if (isSynced(state.project.clips[i])) return box.appendChild(input), box;
  const suggest = document.createElement("button");
  suggest.type = "button";
  suggest.className = "suggest";
  suggest.textContent = "Suggest";
  suggest.title = "Listen to this clip and write a caption from what is said";
  suggest.onclick = async () => {
    const c = state.project.clips[i], project = state.project.name;
    suggest.disabled = true;
    suggest.textContent = "Listening";
    try {
      let job = await api("/api/transcribe", "POST", {src: c.src, in: c.in, out: c.out});
      while (job.state === "working") {
        suggest.title = job.message;
        suggest.textContent = job.message.startsWith("Downloading") ? "Getting model" : "Listening";
        await new Promise(r => setTimeout(r, 1000));
        job = await api(`/api/transcribe/${job.id}`);
      }
      if (job.state !== "done") throw new Error(job.message || "Couldn't write a caption");
      // Listening can take a while; the clips may have been moved, trimmed or swapped for another project meanwhile.
      const at = state.project.name === project ? state.project.clips.findIndex(x => x.src === c.src && x.in === c.in && x.out === c.out) : -1;
      if (at < 0) throw new Error("That clip changed while listening, so the caption wasn't added");
      setCaption(job.text, "", at);
      render();
      toast("Caption suggested. Edit it as you like");
    } catch (err) {
      toast(err.message);
      suggest.disabled = false;
      suggest.textContent = "Suggest";
    }
  };
  box.append(input, suggest);
  return box;
}

function fitField(i) {
  const c = state.project.clips[i], fill = c.fit === "fill";
  const seg = pickRow(`Framing for clip ${i + 1}`, c.fit || "fit", [["fit", "Fit", "Show the whole picture"], ["fill", "Fill", "Crop to fill the frame"]],
    value => setClipField(i, {fit: value}));
  const rows = [numberRow("Framing", seg)];
  if (fill) rows.push(zoomSlider(i, "Crop position", "pan", 0, 1, 0.01, c.pan === undefined ? 0.5 : c.pan, v => `${Math.round(v * 100)}%`));
  return rows;
}

const zoomOf = c => (c && c.zoom) || 1;

function zoomSlider(i, label, key, min, max, step, value, show) {
  const row = document.createElement("label");
  row.className = "zoomrow";
  const name = document.createElement("span");
  name.textContent = label;
  const input = document.createElement("input");
  Object.assign(input, {type: "range", min, max, step, value});
  input.setAttribute("aria-label", `${label} for clip ${i + 1}`);
  const out = document.createElement("output");
  out.className = "num";
  out.textContent = show(value);
  input.oninput = () => {
    const v = Number(input.value);
    out.textContent = show(v);
    state.project = {...state.project, clips: state.project.clips.map((x, n) => (n === i ? {...x, [key]: v} : x))};
    changed(true, `${key}:${i}`);
  };
  row.append(name, input, out);
  return row;
}

function zoomField(i) {
  const c = state.project.clips[i], zoom = zoomOf(c);
  const box = document.createElement("div");
  box.className = "zoombox";
  const pct = v => `${Math.round(v * 100)}%`;
  const zoomRow = zoomSlider(i, "Zoom", "zoom", 0.25, 4, 0.05, zoom, v => `${v.toFixed(2).replace(/0$/, "")}x`);
  const where = [zoomSlider(i, "Left to right", "zx", 0, 1, 0.01, c.zx === undefined ? 0.5 : c.zx, pct),
                 zoomSlider(i, "Top to bottom", "zy", 0, 1, 0.01, c.zy === undefined ? 0.5 : c.zy, pct)];
  const reset = document.createElement("button");
  reset.className = "mini";
  reset.textContent = "Reset zoom";
  reset.onclick = () => setClipField(i, {zoom: 1, zx: 0.5, zy: 0.5});
  const sync = z => {
    box.classList.toggle("flat", z === 1);
    [...where.map(r => r.querySelector("input")), reset].forEach(el => { el.disabled = z === 1; });
  };
  zoomRow.querySelector("input").addEventListener("input", e => sync(Number(e.target.value)));
  sync(zoom);
  box.append(zoomRow, ...where, reset);
  return box;
}

function removeClip(i) {
  if (i < 0 || i >= state.project.clips.length) return;
  state.project = {...state.project, clips: state.project.clips.filter((_, n) => n !== i)};
  state.sel = Math.min(state.sel, state.project.clips.length - 1);
  changed();
}

function splitClip() {
  const clips = state.project.clips, t = video.currentTime;
  const hit = i => state.current && clips[i] && clips[i].src === state.current.path && t > clips[i].in + 0.1 && t < clips[i].out - 0.1;
  const i = hit(state.sel) ? state.sel : clips.findIndex((_, n) => hit(n));
  if (i < 0) return toast("Move the playhead inside a clip to split it");
  const c = clips[i];
  if (rampOf(c) !== "none") return toast("Set this clip to Normal speed before splitting it");
  const first = {...c, out: t, freeze: 0, fadeOut: 0};
  const second = {...c, in: t, caption: "", thumb: captureThumb() || c.thumb, fadeIn: 0, transition: "none"};
  if (isSynced(c)) {
    first.caption = spokenText(first);
    second.caption = spokenText(second);
  }
  state.project = {...state.project, clips: [...clips.slice(0, i), first, second, ...clips.slice(i + 1)]};
  state.sel = i + 1;
  changed();
}

function duplicateClip(i) {
  const c = state.project.clips[i];
  if (!c) return;
  state.project = {...state.project, clips: [...state.project.clips.slice(0, i + 1), {...c}, ...state.project.clips.slice(i + 1)]};
  state.sel = i + 1;
  changed();
}

function move(from, to) {
  const clips = state.project.clips.slice();
  if (to < 0 || to >= clips.length || from === to) return;
  const [moved] = clips.splice(from, 1);
  clips.splice(to, 0, moved);
  state.project = {...state.project, clips};
  state.sel = to;
  changed();
}

function render() {
  updateHistoryButtons();
  paintMarks();
  renderLibrary();
  renderTimeline();
  renderRuler();
  renderTray();
  const t = total(), ok = t <= SHORT_LIMIT;
  $("total").textContent = `${t.toFixed(1)}s`;
  $("lhTotal").textContent = state.project.clips.length;
  const v = $("verdict");
  v.textContent = ok ? "Under 60s" : "Over 60s";
  v.className = ok ? "good" : "bad";
  if (preview.on) layoutCard();
  renderShortOptions();
  renderFavs();
  renderShortMode();
  paintRenderProgress();
  if (typeof ensureVoices === "function") ensureVoices();
}

function select(i, seekToStart = false) {
  state.sel = i;
  const c = state.project.clips[i];
  const v = c && byPath(c.src);
  if (seekToStart && v) state.clipStop = null;
  if (v && (!state.current || state.current.id !== v.id)) openVideo(v, c.in);
  else if (c) {
    ensureVisible(c.in, c.out);
    if (seekToStart && v) {
      video.currentTime = c.in;
      updateTime();
    }
  }
  render();
}

function showOverlay(text, pct) {
  $("overlay").classList.add("on");
  $("ovText").textContent = text;
  $("ovBar").style.width = `${pct || 0}%`;
}
const hideOverlay = () => $("overlay").classList.remove("on");

let loadToken = 0;
// m:ss for lists and headers, rounded down: 83.4 is 1:23
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

function labelSource(v) {
  $("srcName").textContent = v.name;
  $("srcMeta").textContent = `${v.h}p, ${mmss(v.duration)}`;
}

async function openVideo(v, seekTo = 0) {
  if (streaming()) leaveLive();
  const token = ++loadToken;
  video.pause();
  state.current = v;
  state.pendingIn = null;
  state.pendingOut = null;
  fitView();
  labelSource(v);
  render();
  if (!v.ready) {
    showOverlay("Preparing a preview so this plays in the browser", 0);
    try {
      let st = await api(`/api/proxy/${v.id}`, "POST");
      while (st.state === "working") {
        showOverlay(st.queued ? "Waiting for another preview to finish" : `Preparing preview, ${st.pct}%`, st.pct);
        if (token !== loadToken) return;
        st = await api(`/api/proxy/${v.id}?wait=1`);
      }
      if (st.state !== "ready") throw new Error(st.message || "preview failed");
      v.ready = true;
    } catch (err) {
      if (token === loadToken) showOverlay(`Couldn't prepare a preview: ${err.message}`);
      return false;
    }
  }
  if (token !== loadToken) return false;
  hideOverlay();
  const el = video;
  const loaded = await new Promise(resolve => {
    el.onloadedmetadata = () => resolve(true);
    el.onerror = () => resolve(false);
    el.dataset.id = v.id;
    el.dataset.base = "0";
    el.src = `/media/${v.id}`;
  });
  el.onloadedmetadata = el.onerror = null;
  if (token !== loadToken) return false;
  if (!loaded) {
    showOverlay("Couldn't load this video. It may have been moved or deleted");
    return false;
  }
  video.currentTime = seekTo;
  updateTime();
  loadWave(v);
  loadScenes(v);
  return true;
}

function updateTime() {
  if (state.mode === "short") return;
  const d = video.duration || (state.current && state.current.duration) || 0;
  setPlaybackValue($("tcNow"), "textContent", fmt(video.currentTime));
  setPlaybackValue($("tcTot"), "textContent", fmt(d));
  placePlayhead();
  const t = video.currentTime, here = state.current && state.project.clips.find(c => c.src === state.current.path && c.caption && t >= c.in && t < c.out);
  setPlaybackValue($("srcSub"), "textContent", here ? here.caption : "");
  const icon = $("playBtn").querySelector("use");
  const href = video.paused ? "#c-play" : "#c-pause";
  if (icon.getAttribute("href") !== href) icon.setAttribute("href", href);
}

function seekBy(dt) {
  if (streaming()) return liveSeek(dt);
  if (!state.current) return;
  video.currentTime = Math.min(Math.max(0, video.currentTime + dt), video.duration || Infinity);
  if (zoomed() && (video.currentTime < view.s || video.currentTime > view.e)) { ensureVisible(video.currentTime, video.currentTime); redrawView(); }
  updateTime();
}
function resetPlayback() {
  for (const el of videos) {
    el.playbackRate = 1;
    el.volume = 1;
    el.muted = previewMuted;
  }
}
function togglePlay() {
  if (streaming()) return liveToggle();
  if (!state.current) return toast("Pick a video first");
  state.clipStop = null;
  resetPlayback();
  video.paused ? video.play().catch(() => {}) : video.pause();
}

function captureThumb() {
  if (!video.videoWidth) return "";
  const c = document.createElement("canvas");
  c.width = 192;
  c.height = Math.round(192 * video.videoHeight / video.videoWidth);
  c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.7);
}

// A mark a hair off a scene cut is the cut: the clip then starts on the first frame of the shot, or ends on its last.
const MARK_SNAP = 0.25;
function markAt() {
  const t = video.currentTime, cut = nearest(sceneList(), t);
  return cut !== null && Math.abs(cut - t) <= MARK_SNAP ? {t: cut, cut: true} : {t, cut: false};
}

function markIn() {
  if (streaming()) return mark("start");
  if (!state.current) return toast("Pick a video first");
  state.pendingThumb = captureThumb();
  const at = markAt();
  state.pendingIn = at.t;
  state.pendingOut = null;
  render();
  toast(`In at ${fmt(at.t)}${at.cut ? ", on the scene cut" : ""}. Now mark out`);
}
function markOut() {
  if (streaming()) return mark("end");
  if (!state.current) return toast("Pick a video first");
  if (state.pendingIn === null) return toast("Mark in first");
  const at = markAt(), out = at.t;
  if (out - state.pendingIn < 0.2) return toast("Out must be after in");
  state.pendingOut = out;
  render();
  toast(`Out at ${fmt(out)}${at.cut ? ", on the scene cut" : ""}. Press the scissors to clip`);
}
// The scissors: turn the marked part into a clip. It lands at the top of the list.
function clipIt() {
  if (streaming() || state.pendingIn === null || state.pendingOut === null) return;
  const clip = {src: state.current.path, in: state.pendingIn, out: state.pendingOut, note: "", caption: "", speed: 1, volume: 1, fit: "fit", pan: 0.5, effect: "none", ramp: "none", freeze: 0, thumb: state.pendingThumb || captureThumb()};
  state.project = {...state.project, clips: [clip, ...state.project.clips]};
  requestCut(clip);
  state.pendingIn = null;
  state.pendingOut = null;
  state.sel = 0;
  state.arrived = 0;
  changed();
  state.arrived = -1;
}
function paintMarks() {
  const {pendingIn: a, pendingOut: b} = state;
  const ready = !streaming() && a !== null && b !== null;
  const btn = $("clipIt");
  btn.disabled = !ready;
  btn.title = ready ? `Clip the marked ${(b - a).toFixed(1)}s (Enter)` : "Mark in and out first";
  btn.setAttribute("aria-label", ready ? `Clip the marked part, ${(b - a).toFixed(1)} seconds` : "Clip the marked part");
  $("markIn").title = a !== null && !streaming() ? `Mark in (I), set at ${fmt(a)}` : "Mark in (I)";
  $("markOut").title = b !== null && !streaming() ? `Mark out (O), set at ${fmt(b)}` : "Mark out (O)";
}

function playRange(clip, onDone, guard) {
  const v = byPath(clip.src);
  if (!v) return toast("That video is missing from the library");
  const start = skipSeek => {
    if (guard && !guard()) return;
    if (!skipSeek) video.currentTime = clip.in;
    video.playbackRate = speedAt(clip, clip.in);
    video.volume = Math.min(1, volumeOf(clip));
    video.muted = previewMuted || playVolume(clip) === 0;
    state.clipStop = {out: clip.out, onDone, clip};
    video.play().catch(() => {});
  };
  const ready = spare();
  if (ready.dataset.pre === `${v.id}@${clip.in}` && ready.readyState >= 2 && !ready.seeking) {
    adopt(ready, v);
    return start(true);
  }
  if (state.current && state.current.id === v.id && video.readyState >= 1) return start();
  openVideo(v, clip.in).then(opened => { if (opened) start(); });
}

function swapTo(el) {
  video.pause();
  video.classList.add("off");
  el.classList.remove("off");
  el.dataset.pre = "";
  video = el;
}

function loadFileInto(el, file, then) {
  el.dataset.id = file.id;
  el.dataset.base = file.base;
  el.addEventListener("loadedmetadata", then, {once: true});
  el.src = file.url;
}

// The Short overlaps a clip with the next one by the next clip's transition, so the preview leaves a clip that much early.
// Without this the playhead runs to the end of the clip and then jumps back to where the next clip begins on the timeline.
function leaveAt(clip) {
  const next = state.project.clips[nextTop(preview.idx)];
  const overlap = inShort() && next ? seamOverlap(clip, next) : 0;
  return overlap ? clip.out - overlap * speedAt(clip, clip.out - 0.001) : clip.out;
}

// Play one clip of the Short in the preview players, from its own file when it has one.
async function previewRange(clip, onDone, guard, from) {
  // Play from whatever is ready now: a player that already holds this clip's file or source, else the clip's own file when
  // it is saved, else the source. The file is made in the background for next time; waiting for it froze the playhead
  // for the whole encode after every trim.
  const other = spare(), held = fileLoadedIn(video, clip) ? video : fileLoadedIn(other, clip) ? other : null;
  const file = held ? fileLoadedIn(held, clip) : clipFile(clip) || await clipFileSoon(clip);
  if (!file) return toast("Couldn't get that clip ready to play");
  if (held) requestCut(clip);
  const begin = from === undefined ? clip.in : from;
  const start = skipSeek => {
    if (guard && !guard()) return;
    if (!skipSeek) video.currentTime = Math.max(0, begin - baseOf(video));
    video.playbackRate = speedAt(clip, begin);
    video.volume = Math.min(1, volumeOf(clip));
    video.muted = previewMuted || playVolume(clip) === 0;
    state.clipStop = {out: leaveAt(clip), onDone, clip};
    preview.live = true;
    if (preview.hold) video.pause();
    else video.play().catch(() => {});
    playTransition(clip, from === undefined);
  };
  const ready = spare();
  if (from === undefined && ready.dataset.pre === `${file.id}@${clip.in}` && ready.readyState >= 2 && !ready.seeking) {
    swapTo(ready);
    return start(true);
  }
  if (held && held !== video) swapTo(held);
  if (video.dataset.id === file.id && video.readyState >= 1) return start();
  loadFileInto(video, file, () => { if (!guard || guard()) start(); });
}

function preloadPreview(clip) {
  const file = clipFile(clip), el = spare();
  if (!file) return;
  const token = ++preloadToken;
  el.pause();
  const seek = () => {
    if (token !== preloadToken) return;
    el.dataset.pre = `${file.id}@${clip.in}`;
    el.currentTime = Math.max(0, clip.in - file.base);
  };
  el.dataset.pre = "";
  if (el.dataset.id === file.id && el.readyState >= 1) return seek();
  loadFileInto(el, file, seek);
}

function adopt(el, v) {
  video.pause();
  video.classList.add("off");
  el.classList.remove("off");
  el.dataset.pre = "";
  video = el;
  loadToken += 1;
  if (!state.current || state.current.id !== v.id) {
    state.current = v;
    state.pendingIn = null;
    state.pendingOut = null;
    fitView();
  }
  labelSource(v);
  loadWave(v);
  loadScenes(v);
  render();
}

let preloadToken = 0;
const FRAMES = {wide: [1920, 1080], square: [1080, 1080], tall: [1080, 1350]};
// Glitch bursts follow the same hash as glitch_burst in make_short.py, so the preview tears where the render does.
const GLITCH_SLOT = 0.08, GLITCH_ODDS = 0.22;
const glitchRand = (n, k) => Math.abs(Math.sin(n * 12.9898 + k * 78.233) * 43758.5453) % 1;
function glitchAt(t) {
  const n = Math.floor(t / GLITCH_SLOT);
  if (glitchRand(n, 0) >= GLITCH_ODDS) return null;
  const w = 0.2 + 0.3 * glitchRand(n, 3);
  return {split: 0.012 + 0.03 * glitchRand(n, 1), y: glitchRand(n, 2) * 0.8, h: 0.04 + 0.1 * glitchRand(n, 4), w, x: glitchRand(n, 5) * (1 - 2 * w), n};
}

function effectPose(clip, vid = video) {
  const id = effectOf(clip);
  const pose = {zoom: 1, dx: 0, dy: 0, flash: 0, gray: false, vignette: false, glitch: null};
  if (id === "none") return pose;
  if (id === "bw") { pose.gray = true; return pose; }
  if (id === "vignette") { pose.vignette = true; return pose; }
  const len = movingLen(clip), t = Math.min(len, outTimeAt(clip, tnow(vid)));
  if (id === "zoom_in") pose.zoom = 1 + 0.15 * t / len;
  else if (id === "zoom_out") pose.zoom = 1.15 - 0.15 * t / len;
  else if (id === "punch") pose.zoom = 1 + 0.2 * Math.pow(Math.max(0, 1 - t / 0.35), 2);
  else if (id === "shake") Object.assign(pose, {zoom: 1.06, dx: 0.012 * Math.sin(t * 37), dy: 0.008 * Math.sin(t * 41 + 1)});
  else if (id === "flash") pose.flash = Math.max(0, 1 - t / 0.25);
  else if (id === "glitch") pose.glitch = glitchAt(t);
  return pose;
}

// CSSOM may normalize colors and spacing. Remember both the requested and actual
// value so stable frames skip writes while outside style edits are still noticed.
const playbackStyleValues = new WeakMap();
function setPlaybackStyle(style, key, value) {
  let values = playbackStyleValues.get(style);
  const previous = values?.get(key), current = style[key];
  if (previous && previous.value === value && previous.actual === current) return;
  if (current !== value) style[key] = value;
  if (!values) { values = new Map(); playbackStyleValues.set(style, values); }
  values.set(key, {value, actual: style[key]});
}

let monitorFxOn = false;

function monitorClip() {
  const v = state.current;
  if (!v) return null;
  const t = video.currentTime, hit = i => {
    const c = state.project.clips[i];
    return c && c.src === v.path && t >= c.in && t < c.out && effectOf(c) !== "none" ? c : null;
  };
  const selected = hit(state.sel);
  if (selected) return selected;
  for (let i = 0; i < state.project.clips.length; i++) {
    const clip = hit(i);
    if (clip) return clip;
  }
  return null;
}

function clearMonitorFx() {
  if (!monitorFxOn) return;
  monitorFxOn = false;
  for (const el of videos) {
    setPlaybackStyle(el.style, "transform", "");
    setPlaybackStyle(el.style, "filter", "");
  }
  const fx = $("fxOverlay");
  setPlaybackStyle(fx.style, "background", "");
  setPlaybackStyle(fx.style, "boxShadow", "");
}

function applyMonitorFx() {
  const clip = preview.on ? null : monitorClip();
  if (!clip) return clearMonitorFx();
  const pose = effectPose(clip), fx = $("fxOverlay");
  monitorFxOn = true;
  setPlaybackStyle(video.style, "transform", `translate(${pose.dx * 100}%, ${pose.dy * 100}%) scale(${pose.zoom})`);
  setPlaybackStyle(video.style, "filter", pose.gray ? "grayscale(1)" : "");
  const layers = [];
  if (pose.flash > 0) layers.push(`linear-gradient(rgba(255,255,255,${pose.flash}), rgba(255,255,255,${pose.flash}))`);
  if (pose.vignette) layers.push("radial-gradient(ellipse at center, transparent 45%, rgba(0,0,0,.75))");
  setPlaybackStyle(fx.style, "background", layers.join(","));
  const gpx = pose.glitch ? Math.round(pose.glitch.split * 400) : 0;
  setPlaybackStyle(fx.style, "boxShadow", pose.glitch ? `inset ${gpx}px 0 rgba(255,45,85,.55), inset -${gpx}px 0 rgba(0,229,255,.55)` : "");
}

// Swap a band with its neighbour, like the render does, then sprinkle a little grain.
function tearBand(g, W, H) {
  const bw = Math.round(g.w * W), bh = Math.round(g.h * H), x = Math.round(g.x * W), y = Math.round(g.y * H);
  const keep = mctx.getImageData(x, y, bw, bh);
  mctx.drawImage(mirror, x + bw, y, bw, bh, x, y, bw, bh);
  mctx.putImageData(keep, x + bw, y);
  mctx.fillStyle = "rgba(255,255,255,.18)";
  for (let i = 0; i < 40; i++) mctx.fillRect(glitchRand(g.n, 10 + i) * W, glitchRand(g.n, 60 + i) * H, 2 + glitchRand(g.n, 100 + i) * 6, 1);
}

function fadeAmount(clip) {
  const d = state.project.fade || 0;
  if (!d) return 0;
  const len = outLen(clip), fade = Math.min(d, len / 3), t = clipPos(clip);
  const edge = Math.min(t, len - t);
  return edge >= fade ? 0 : 1 - Math.max(0, edge) / fade;
}
const preview = {on: false, run: 0, idx: 0, done: false, elapsed: 0, live: false};
const phoneEl = document.querySelector(".theater .phone");
const CARD = {PAD: 36, AVATAR: 112, GAP: 28, SUB_GAP: 44};
// Keep in step with FORMATS, HOOK_TOP and CAPTION_INSET in make_short.py.
const FORMATS = {"9:16": [1080, 1920], "4:5": [1080, 1350], "1:1": [1080, 1080], "16:9": [1920, 1080]};
const HOOK_TOP = {"9:16": 250}, DEFAULT_HOOK_TOP = 40, CAPTION_INSET = {"9:16": 360}, DEFAULT_CAPTION_INSET = 70;
const formatOf = () => (FORMATS[state.project.format] ? state.project.format : "9:16");
const canvasOf = () => FORMATS[formatOf()];
const fillsCard = () => true;
const LAYOUTS = {
  title: {header: false, hookPx: 76, align: "left"},
  center: {header: false, hookPx: 80, align: "center"},
  profile: {header: true, hookPx: 52, align: "left"},
  bare: {header: false, hookPx: 0, align: "left"},
};
const layoutOf = () => LAYOUTS[state.project.layout] || LAYOUTS.title;
new ResizeObserver(() => {
  $("thCtrl").style.width = `${Math.max(280, phoneEl.offsetWidth)}px`;
  $("card1080").style.transform = `scale(${phoneEl.clientWidth / canvasOf()[0]})`;
}).observe(phoneEl);

function wrapHook(text, px) {
  const ctx = document.createElement("canvas").getContext("2d");
  ctx.font = `bold ${px}px Arial, Helvetica, sans-serif`;
  const lines = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const trial = `${line} ${word}`.trim();
    if (ctx.measureText(trial).width <= canvasOf()[0] - 2 * CARD.PAD || !line) line = trial;
    else { lines.push(line); line = word; }
  }
  if (line) lines.push(line);
  return lines;
}

// The hook is edited where it is shown: click it in the preview, type, and Enter or a click away keeps it.
{
  const el = $("cHook");
  const commit = () => {
    const text = el.innerText.replace(/\s+/g, " ").trim();
    if (text !== (state.project.hook || "")) {
      state.project = {...state.project, hook: text};
      changed(true, "hook");
    }
    layoutCard();
  };
  el.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); el.blur(); }
    else if (e.key === "Escape") { el.textContent = state.project.hook || ""; el.blur(); }
  });
  el.addEventListener("paste", e => {
    e.preventDefault();
    document.execCommand("insertText", false, e.clipboardData.getData("text/plain").replace(/\s+/g, " "));
  });
  el.addEventListener("blur", commit);
}

// The 1080-wide card is scaled down to the phone, and --k is how many card pixels one screen pixel covers, so the
// frame tools stay a constant size. The phone can change size after the layout (format, window, panels), so this
// runs on its own whenever it does.
function fitCardScale() {
  const [W] = canvasOf(), shown = Math.max(1, phoneEl.clientWidth);
  $("card1080").style.transform = `scale(${shown / W})`;
  $("card1080").style.setProperty("--k", String(W / shown));
}
new ResizeObserver(fitCardScale).observe(phoneEl);

function layoutCard() {
  const [W, H] = canvasOf();
  const {PAD, AVATAR, GAP} = CARD;
  const first = state.project.clips[0];
  const src = first && byPath(first.src);
  const shape = FRAMES[state.project.frame];
  const cw0 = shape ? shape[0] : (src && src.w) || 1920, ch0 = shape ? shape[1] : (src && src.h) || 1080;
  const spec = layoutOf(), lineH = Math.round(spec.hookPx * 1.25);
  const lines = state.project.hook && spec.hookPx ? wrapHook(state.project.hook, spec.hookPx) : [];
  const TOP_MIN = lines.length || spec.header ? HOOK_TOP[formatOf()] || DEFAULT_HOOK_TOP : 0;
  const BOTTOM_SAFE = 0;
  const headerH = spec.header ? AVATAR + GAP : 0, textBlock = lines.length ? lines.length * lineH + GAP : 0;
  const maxH = H - BOTTOM_SAFE - TOP_MIN - headerH - textBlock, maxW = W;
  let cw, ch;
  if (fillsCard()) {
    cw = Math.floor(maxW / 2) * 2;
    ch = Math.floor(maxH / 2) * 2;
  } else {
    const scale = Math.min(maxW / cw0, maxH / ch0);
    cw = Math.floor(cw0 * scale / 2) * 2;
    ch = Math.floor(ch0 * scale / 2) * 2;
  }
  const total = headerH + textBlock + ch;
  const top = Math.max(TOP_MIN, Math.floor((H - BOTTOM_SAFE - total) / 2));
  const place = (el, x, y, w, h) => Object.assign(el.style, {left: `${x}px`, top: `${y}px`, width: w ? `${w}px` : "", height: h ? `${h}px` : ""});
  Object.assign($("card1080").style, {width: `${W}px`, height: `${H}px`});
  phoneEl.style.aspectRatio = `${W} / ${H}`;
  fitCardScale();
  requestAnimationFrame(fitCardScale);
  for (const id of ["cAvatar", "cName", "cHandle"]) $(id).hidden = !spec.header;
  place($("cAvatar"), PAD, top, AVATAR, AVATAR);
  place($("cName"), PAD + AVATAR + 24, top + 8);
  place($("cHandle"), PAD + AVATAR + 24, top + 62);
  place($("cHook"), PAD, top + headerH, W - 2 * PAD);
  Object.assign($("cHook").style, {fontSize: `${spec.hookPx}px`, lineHeight: `${lineH}px`, textAlign: spec.align});
  if (document.activeElement !== $("cHook")) $("cHook").textContent = lines.join("\n");
  $("cHook").contentEditable = spec.hookPx ? "plaintext-only" : "false";
  place(mirror, Math.floor((W - cw) / 2), top + headerH + textBlock, cw, ch);
  if (mirror.width !== cw / 2 || mirror.height !== ch / 2) { mirror.width = cw / 2; mirror.height = ch / 2; }
  const capBottom = top + headerH + textBlock + ch - (CAPTION_INSET[formatOf()] || DEFAULT_CAPTION_INSET);
  $("cCap").dataset.at = "";
  capHome = {left: PAD, bottom: capBottom, width: W - 2 * PAD};
  placeCaption(state.project.clips[preview.idx]);
  $("cSafe").hidden = formatOf() !== "9:16";
  place($("cSafe"), 0, H - BOTTOM_SAFE, W, BOTTOM_SAFE);
  card1080Info = {top, cw, ch, lines: lines.length, clipY: top + headerH + textBlock};
}
let card1080Info = null, capHome = null;
const DEFAULT_CAPTION_SIZE = 50;
const captionSize = () => state.project.capSize || DEFAULT_CAPTION_SIZE;
// Caption text scales with the size setting; the outline keeps the same proportion as the render's.
function applyCaptionSize(scale = 1, look = DEFAULT_LOOK, hi = DEFAULT_HIGHLIGHT) {
  const l = CAP_LOOKS[look] || CAP_LOOKS[DEFAULT_LOOK], size = Math.round(captionSize() * l.size * scale), pad = Math.round(size * l.outline);
  Object.assign($("cCap").style, {
    fontSize: `${size}px`, lineHeight: `${Math.round(size * 1.14)}px`, fontFamily: l.font, fontWeight: l.weight, textTransform: l.upper ? "uppercase" : "none",
    color: `#${l.fill}`, webkitTextStroke: l.box ? "0" : `${Math.max(l.shadow ? 3 : 6, Math.round(size * l.outline * 2))}px #${l.edge}`,
    background: l.box ? `#${l.edge}` : "transparent", padding: l.box ? `${pad}px` : "0",
    textShadow: l.shadow ? "0 4px 8px rgba(0,0,0,.65)" : "none"});
  $("cCap").style.setProperty("--hi", `#${hi}`);
}

const capMoved = c => Boolean(c) && c.capX !== undefined && c.capX !== null && c.capY !== undefined && c.capY !== null;

// A caption keeps the position, size and turn of the one before it until a clip sets its own, as the render does. A clip that
// only carries a caption over has none of its own.
function capStyleOf(clip) {
  const clips = state.project.clips, upto = clips.indexOf(clip);
  const style = {at: null, scale: 1, rot: 0, look: DEFAULT_LOOK, hi: DEFAULT_HIGHLIGHT};
  // Track caption carry as we walk, instead of searching backwards again for
  // every blank clip on every preview frame. Timed captions do not carry.
  let carried = false;
  for (let n = 0; n <= upto; n++) {
    const c = clips[n];
    if (!isTop(c)) continue;
    if (c.caption) carried = !isSynced(c);
    else if (c.capStop) carried = false;
    else if (carried) continue;
    if (capMoved(c)) style.at = [c.capX, c.capY];
    if (c.capScale !== undefined && c.capScale !== null) style.scale = c.capScale;
    if (c.capRot !== undefined && c.capRot !== null) style.rot = c.capRot;
    if (c.capLook) style.look = c.capLook;
    if (c.capHi) style.hi = c.capHi;
  }
  return style;
}

// The caption sits on the clip, near its bottom, unless a point was set by dragging it in the preview.
function placeCaption(clip) {
  const el = $("cCap");
  if (!capHome) return;
  const [W, H] = canvasOf();
  // Clip and style edits replace the list; geometry and selection still update each frame.
  const clips = state.project.clips;
  let cached = placeCaption.styleCache;
  if (!cached || cached.clips !== clips || cached.clip !== clip) {
    cached = placeCaption.styleCache = {clips, clip,
      style: clip ? capStyleOf(clip) : {at: null, scale: 1, rot: 0, look: DEFAULT_LOOK, hi: DEFAULT_HIGHLIGHT}};
  }
  const st = cached.style;
  const key = `${st.at ? st.at.join(",") : "home"}|${st.scale}|${st.rot}|${st.look}|${st.hi}|${W}|${captionSize()}`;
  if (el.dataset.at !== key) {
    el.dataset.at = key;
    applyCaptionSize(st.scale, st.look, st.hi);
    const shared = {width: "max-content", maxWidth: `${capHome.width}px`};
    if (st.at) Object.assign(el.style, shared, {left: `${st.at[0] * W}px`, top: `${st.at[1] * H}px`, transform: `translate(-50%, -50%) rotate(${st.rot}deg)`, transformOrigin: "50% 50%"});
    else Object.assign(el.style, shared, {left: `${W / 2}px`, top: `${capHome.bottom}px`, transform: `translate(-50%, -100%) rotate(${st.rot}deg)`, transformOrigin: "50% 100%"});
  }
  syncCapSel(st);
}

// The selection frame follows the caption: same box, same turn, with handles to resize and rotate it.
function syncCapSel(st) {
  const el = $("cCap"), sel = $("capSel");
  const show = inShort() && Boolean(el.textContent);
  setPlaybackValue(sel, "hidden", !show);
  if (!show) return;
  const measure = () => ({left: `${el.offsetLeft}px`, top: `${el.offsetTop}px`, width: `${el.offsetWidth}px`, height: `${el.offsetHeight}px`,
    transform: el.style.transform, transformOrigin: el.style.transformOrigin});
  let box;
  if (typeof ResizeObserver === "function") {
    let cached = syncCapSel.geometry;
    if (!cached || cached.el !== el) {
      cached?.observer.disconnect();
      cached = {el, dirty: true};
      cached.observer = new ResizeObserver(() => { cached.dirty = true; });
      cached.observer.observe(el, {box: "border-box"});
      if (el.parentElement) cached.observer.observe(el.parentElement);
      syncCapSel.geometry = cached;
    }
    const key = [el.textContent, el.dataset?.cap, el.dataset?.at, el.className,
      el.style.cssText, state.project, capHome];
    if (cached.dirty || !cached.key || key.some((value, i) => value !== cached.key[i])) {
      cached.box = measure();
      cached.key = key;
      cached.dirty = false;
    }
    box = cached.box;
  } else box = measure();
  for (const [key, value] of Object.entries(box)) setPlaybackValue(sel.style, key, value);
  const style = st || capStyleOf(state.project.clips[preview.idx]);
  setPlaybackValue($("capRead"), "textContent", `${Math.round(style.scale * 100)}% \u00b7 ${Math.round(style.rot)}\u00b0`);
}

// Collect preview timing and clip counts together; rebuilt each frame so live edits are visible.
function previewTiming() {
  let total = 0, at = 0, start = 0, tops = 0, place = 0, prev = null, prevLen = 0;
  const lens = state.project.clips.map((c, i) => {
    if (!isTop(c)) return 0;
    const len = outLen(c), overlap = seamOverlap(prev, c, prevLen, len);
    total = total + len - overlap;
    at -= overlap;
    if (i === preview.idx) start = at;
    at += len;
    if (i < preview.idx) start = at;
    if (len) { tops++; if (i <= preview.idx) place++; }
    prev = c;
    prevLen = len;
    return len;
  });
  return {lens, total, start, tops, place};
}

function buildSegs() {
  if (state.mode === "short") return;
  const segs = $("segs");
  segs.innerHTML = "";
  state.project.clips.forEach((c, i) => {
    const b = document.createElement("button");
    b.className = "seg";
    b.style.flex = `${isTop(c) ? outLen(c) : 0} 1 0`;
    b.hidden = !isTop(c);
    b.setAttribute("aria-label", `Go to clip ${i + 1}`);
    b.title = `Clip ${i + 1}`;
    b.innerHTML = "<i></i>";
    b.onclick = () => startPreviewAt(i);
    segs.appendChild(b);
  });
}

const nextTop = i => {
  let n = i + 1;
  while (n < state.project.clips.length && !isTop(state.project.clips[n])) n += 1;
  return n;
};
const prevTop = i => {
  let n = i - 1;
  while (n >= 0 && !isTop(state.project.clips[n])) n -= 1;
  return n;
};

function startPreviewAt(i, from) {
  if (from === undefined) preview.hold = false;
  const clips = state.project.clips;
  const at = clips[i] && isTop(clips[i]) ? i : Math.max(prevTop(i), nextTop(-1));
  const run = ++preview.run;
  preview.done = false;
  preview.elapsed = 0;
  playPreviewClip(at, run, from);
}

function playPreviewClip(i, run, from) {
  if (run !== preview.run || !preview.on) return;
  const clip = state.project.clips[i];
  if (!clip) {
    preview.done = true;
    video.pause();
    return;
  }
  preview.idx = i;
  preview.live = false;
  // The Short station paints the playing clip every frame; only the clip station follows the selection.
  if (state.mode !== "short") {
    state.sel = i;
    render();
  }
  const next = nextTop(i);
  previewRange(clip, () => playPreviewClip(next, run), () => run === preview.run && preview.on, from);
  const upcoming = state.project.clips[next];
  if (upcoming) setTimeout(() => { if (run === preview.run && preview.on) preloadPreview(upcoming); }, 400);
}

function openPreview() {
  if (nextTop(-1) >= state.project.clips.length) return toast("Add a clip to the top lane first");
  preview.on = true;
  $("theater").hidden = false;
  layoutCard();
  buildSegs();
  startPreviewAt(nextTop(-1));
  $("thPlay").focus();
}
function closePreview() {
  preview.on = false;
  preview.run += 1;
  lowNow = [];
  for (const el of laneVids) el.pause();
  state.clipStop = null;
  video.pause();
  resetPlayback();
  $("theater").hidden = true;
}
function togglePreview() {
  preview.hold = false;
  if (preview.done) return startPreviewAt(nextTop(-1));
  video.paused ? video.play().catch(() => {}) : video.pause();
}
function stepPreview(dir) {
  const next = dir > 0 ? nextTop(preview.idx) : prevTop(preview.idx);
  if (next < 0) return startPreviewAt(nextTop(-1));
  if (next >= state.project.clips.length) return;
  startPreviewAt(next);
}

function updatePreview() {
  const revision = typeof editCount === "number" ? editCount : 0;
  const cached = updatePreview.timing;
  if (!cached || cached.project !== state.project || cached.clips !== state.project.clips
      || cached.idx !== preview.idx || cached.revision !== revision) {
    updatePreview.timing = {project: state.project, clips: state.project.clips, idx: preview.idx,
      revision, value: previewTiming()};
  }
  const {lens, total, start, tops, place} = updatePreview.timing.value;
  const clip = state.project.clips[preview.idx], pos = clip && !preview.done ? clipPos(clip) : 0;
  let elapsed = 0;
  if (preview.done) elapsed = total;
  else if (clip) elapsed = Math.max(0, start + (preview.live ? Math.min(pos, lens[preview.idx]) : 0));
  preview.elapsed = elapsed;
  if (state.mode !== "short") {
    document.querySelectorAll("#segs .seg").forEach((seg, i) => {
      const frac = !lens[i] ? 0 : preview.done || i < preview.idx ? 1 : i === preview.idx ? (preview.live ? Math.min(pos / lens[i], 1) : 0) : 0;
      setPlaybackValue(seg.firstChild.style, "width", `${frac * 100}%`);
      seg.classList.toggle("now", i === preview.idx && !preview.done);
    });
  }
  setPlaybackValue($("thElapsed"), "textContent", stampShort(elapsed));
  setPlaybackValue($("thTotal"), "textContent", stampShort(total));
  const cap = preview.done ? null : captionAt(clip, pos, !video.paused);
  paintCaption($("cCap"), cap);
  paintLiveCap(clip, preview.idx, cap);
  placeCaption(clip);
  // Placement already syncs the selection once caption geometry is available.
  if (!capHome) syncCapSel();
  setPlaybackValue($("thLabel"), "textContent", `Clip ${Math.min(place, tops)} of ${tops}`);
  const icon = preview.done ? "#replay" : video.paused ? "#c-play" : "#c-pause";
  const use = $("thPlay").querySelector("use");
  if (use.getAttribute("href") !== icon) use.setAttribute("href", icon);
  const label = preview.done ? "Replay" : video.paused ? "Play" : "Pause";
  if ($("thPlay").getAttribute("aria-label") !== label) $("thPlay").setAttribute("aria-label", label);
}

function tick() {
  const cs = state.clipStop;
  if (cs) {
    if (!cs.holding && rampOf(cs.clip) !== "none") video.playbackRate = speedAt(cs.clip, tnow());
    // A file that runs out a hair before the clip's out point still ends the clip, or the Short would stall here.
    if (tnow() >= cs.out || (video.ended && !cs.holding)) {
      const hold = freezeOf(cs.clip) * 1000;
      if (hold && !cs.holding) {
        state.clipStop = {...cs, holding: performance.now()};
        video.pause();
      } else if (!hold || performance.now() - cs.holding >= hold) {
        state.clipStop = null;
        video.pause();
        if (cs.onDone) cs.onDone();
        else resetPlayback();
      }
    }
  }
  updateTime();
  syncLanes();
  const t = video.currentTime;
  if (zoomed() && !video.paused && !trimming && t > view.e && t < view.e + 0.5) {
    setView(t - span() * 0.1, t + span() * 0.9);
    redrawView();
  }
  if (preview.on) {
    updatePreview();
    syncSounds();
    paintPlayhead();
  } else stopSounds();
  syncVoices();
  applyMonitorFx();
  drawMirror();
  requestAnimationFrame(tick);
}
const mirror = $("mirror"), mctx = mirror.getContext("2d");
// Lanes below the first each ride on their own element and follow the top lane's clock, holding their last frame when they run out.
const laneVids = [makeSpareVideo(), makeSpareVideo(), makeSpareVideo()];
let lowNow = [];

// Which clip of a lane is on screen at this moment of the Short, and how far into it.
function laneAt(lane, t, playback = false) {
  if (playback) {
    const clips = state.project.clips;
    let cache = laneAt.cache;
    if (!cache || cache.project !== state.project || cache.clips !== clips || cache.count !== clips.length || cache.edit !== editCount) {
      cache = {project: state.project, clips, count: clips.length, edit: editCount, lanes: new Map()};
      for (const clip of clips) {
        const name = laneOf(clip);
        let row = cache.lanes.get(name);
        if (!row) cache.lanes.set(name, row = {clips: [], starts: [], ends: [], total: 0, valid: true});
        const length = outLen(clip);
        row.clips.push(clip);
        row.starts.push(row.total);
        row.total += length;
        row.ends.push(row.total);
        row.lastLength = length;
        if (length < 0 || !Number.isFinite(length) || !Number.isFinite(row.total)) row.valid = false;
      }
      laneAt.cache = cache;
    }
    const row = cache.lanes.get(lane);
    if (!row) return null;
    if (row.valid) {
      let lo = 0, hi = row.ends.length;
      while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if (t < row.ends[mid]) hi = mid; else lo = mid + 1;
      }
      return lo < row.clips.length ? {clip: row.clips[lo], pos: t - row.starts[lo], held: false}
        : {clip: row.clips[row.clips.length - 1], pos: row.lastLength, held: true};
    }
  }
  // Direct lookups stay fresh for in-place edits; malformed timing also uses
  // these original linear rules instead of assuming ordered cumulative ends.
  let at = 0, last = null;
  for (const c of state.project.clips) {
    if (laneOf(c) !== lane) continue;
    const len = outLen(c);
    if (t < at + len) return {clip: c, pos: t - at, held: false};
    at += len;
    last = c;
  }
  return last ? {clip: last, pos: outLen(last), held: true} : null;
}

function syncLanes() {
  if (!preview.on && laneAt.cache) laneAt.cache = null;
  lowNow = [];
  laneVids.forEach((el, n) => {
    const lane = LANES[n + 1];
    if (!preview.on || n + 1 >= laneCount()) { if (!el.paused) el.pause(); return; }
    lowNow[n] = syncLane(el, lane);
  });
}

function syncLane(el, lane) {
  const hit = laneAt(lane, preview.elapsed || 0, true);
  const file = hit && (fileLoadedIn(el, hit.clip) || clipFile(hit.clip));
  if (!file) { if (!el.paused) el.pause(); return null; }
  const c = hit.clip;
  if (el.dataset.id !== file.id) {
    if (!el.paused) el.pause();
    el.dataset.id = file.id;
    el.dataset.base = file.base;
    el.src = file.url;
  }
  if (el.readyState < 1) return hit;
  setPlaybackValue(el, "volume", Math.min(1, volumeOf(c)));
  setPlaybackValue(el, "muted", previewMuted || playVolume(c) === 0);
  const want = Math.min(c.out, c.in + Math.min(hit.pos, movingLen(c)) * speedOf(c));
  const cs = state.clipStop, running = !video.paused || Boolean(cs && cs.holding);
  setPlaybackValue(el, "playbackRate", speedOf(c));
  // Stop a hair before the end of a saved clip file, where some browsers draw nothing.
  const seekTo = t => { el.currentTime = Math.max(0, Math.min(t - file.base, (el.duration || Infinity) - 0.06)); };
  if (hit.held || want >= c.out - 0.02 || !running) {
    if (!el.paused) el.pause();
    if (Math.abs(tnow(el) - want) > 0.1 && !el.seeking) seekTo(want);
    return hit;
  }
  if (Math.abs(tnow(el) - want) > 0.4) seekTo(want);
  if (el.paused) el.play().catch(() => {});
  return hit;
}

// Where each lane sits in the frame, as fractions of its width and height: split is two rows, three is one over two, four is a grid.
// The project's rowSplit (top row height) and colSplit (three's bottom pair) move the seams; four stays equal.
const SPLIT_RANGE = [0.2, 0.8];
const seamOf = v => (Number.isFinite(v) ? Math.min(SPLIT_RANGE[1], Math.max(SPLIT_RANGE[0], v)) : 0.5);
function laneBoxes(k, project = state.project) {
  const row = seamOf(project.rowSplit), col = seamOf(project.colSplit);
  if (k === 2) return [[0, 0, 1, row], [0, row, 1, 1 - row]];
  if (k === 3) return [[0, 0, 1, row], [0, row, col, 1 - row], [col, row, 1 - col, 1 - row]];
  if (k === 4) return [[0, 0, 0.5, 0.5], [0.5, 0, 0.5, 0.5], [0, 0.5, 0.5, 0.5], [0.5, 0.5, 0.5, 0.5]];
  return [[0, 0, 1, 1]];
}

// How far this clip is faded to black at this moment, from its own fade in and fade out.
function ownFade(clip, vid) {
  const fi = clip.fadeIn || 0, fo = clip.fadeOut || 0;
  if (!fi && !fo) return 0;
  const len = outLen(clip), cap = len / 2, t = Math.min(len, outTimeAt(clip, tnow(vid)));
  const a = fi ? Math.max(0, 1 - t / Math.min(fi, cap)) : 0;
  const b = fo ? Math.max(0, 1 - (len - t) / Math.min(fo, cap)) : 0;
  return Math.max(a, b);
}

function paintClip(vid, clip, W, H) {
  const fill = Boolean(clip && fitOf(clip) === "fill"), pan = clip && clip.pan !== undefined ? clip.pan : 0.5;
  const pick = fill ? Math.max : Math.min;
  const zoomOut = fill && zoomOf(clip) < 1;
  const r = pick(W / vid.videoWidth, H / vid.videoHeight) * (zoomOut ? zoomOf(clip) : 1);
  const w = vid.videoWidth * r, h = vid.videoHeight * r;
  const zx0 = clip && clip.zx !== undefined ? clip.zx : 0.5, zy0 = clip && clip.zy !== undefined ? clip.zy : 0.5;
  const x = fill ? (W - w) * (zoomOut && w <= W ? zx0 : pan) : (W - w) / 2;
  const y = fill ? (H - h) * (zoomOut && h <= H ? zy0 : pan) : (H - h) / 2;
  const pose = clip ? effectPose(clip, vid) : null;
  const cx = W / 2, cy = H / 2;
  mctx.save();
  if (pose) {
    mctx.translate(cx + pose.dx * W, cy + pose.dy * H);
    mctx.scale(pose.zoom, pose.zoom);
    mctx.translate(-cx, -cy);
  }
  const zoom = zoomOf(clip);
  if (zoom > 1 || (zoom < 1 && !fill)) {
    const follow = trackedFocus(clip, tnow(vid));
    const zx = follow ? follow[0] : clip.zx === undefined ? 0.5 : clip.zx, zy = follow ? follow[1] : clip.zy === undefined ? 0.5 : clip.zy;
    mctx.translate(-(W - W / zoom) * zx * zoom, -(H - H / zoom) * zy * zoom);
    mctx.scale(zoom, zoom);
  }
  const graded = gradedVideo(vid, clip);
  mctx.drawImage(graded, x, y, w, h);
  if (pose && pose.glitch) {
    const shift = Math.max(2, W * pose.glitch.split);
    mctx.globalAlpha = 0.5;
    mctx.drawImage(graded, x + shift, y, w, h);
    mctx.drawImage(graded, x - shift, y, w, h);
    mctx.globalAlpha = 1;
  }
  mctx.restore();
  if (pose && pose.glitch) tearBand(pose.glitch, mirror.width, mirror.height);
  if (pose && pose.gray) {
    mctx.globalCompositeOperation = "saturation";
    mctx.fillStyle = "#808080";
    mctx.fillRect(0, 0, W, H);
    mctx.globalCompositeOperation = "source-over";
  }
  if (pose && pose.vignette) {
    const g = mctx.createRadialGradient(cx, cy, Math.min(cx, cy) * 0.5, cx, cy, Math.hypot(cx, cy));
    g.addColorStop(0, "rgba(0,0,0,0)");
    g.addColorStop(1, "rgba(0,0,0,.75)");
    mctx.fillStyle = g;
    mctx.fillRect(0, 0, W, H);
  }
  if (pose && pose.flash > 0) {
    mctx.fillStyle = `rgba(255,255,255,${pose.flash})`;
    mctx.fillRect(0, 0, W, H);
  }
  const faded = clip ? ownFade(clip, vid) : 0;
  if (faded > 0) {
    mctx.fillStyle = `rgba(0,0,0,${faded})`;
    mctx.fillRect(0, 0, W, H);
  }
}

// What the render puts behind the clip: the picture shrunk to a few pixels, stretched over the frame, blurred, flattened and darkened.
// The numbers follow BLUR_BG_SHRINK, gblur and BLUR_BG_DIM in make_short.py, scaled to this canvas; the dim is a little stronger than
// -0.08 because ffmpeg applies it to luma and a canvas to RGB, and 24 is what lands on the render's brightness.
const BLUR_BG = {shrink: 120, sigma: 40, width: 1080, dim: 24};
const blurSteps = [16, 4, 1].map(k => document.createElement("canvas"));

// A canvas drawn straight down to a few pixels only samples the picture, so it is shrunk in steps, like an area average.
function shrunkFrame() {
  const tw = Math.max(1, Math.round(1080 / BLUR_BG.shrink)), th = Math.max(1, Math.round(1920 / BLUR_BG.shrink));
  let from = video;
  blurSteps.forEach((canvas, i) => {
    const k = [16, 4, 1][i];
    if (canvas.width !== tw * k || canvas.height !== th * k) { canvas.width = tw * k; canvas.height = th * k; }
    const ctx = canvas.getContext("2d");
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(from, 0, 0, canvas.width, canvas.height);
    from = canvas;
  });
  return from;
}

function drawBlurBackground(w, h) {
  const tiny = shrunkFrame();
  mctx.save();
  mctx.filter = `blur(${BLUR_BG.sigma * w / BLUR_BG.width}px) contrast(.7) saturate(1.1)`;
  mctx.drawImage(tiny, 0, 0, w, h);
  mctx.filter = "none";
  mctx.globalCompositeOperation = "difference";
  mctx.fillStyle = `rgb(${BLUR_BG.dim},${BLUR_BG.dim},${BLUR_BG.dim})`;
  mctx.fillRect(0, 0, w, h);
  mctx.restore();
}

function drawMirror() {
  // The canvas lives inside the Short preview; drawing it while hidden still
  // copies video frames every animation tick, even during ordinary source playback.
  if ($("theater").hidden || !video.videoWidth) { drawMirror.previous = null; return; }
  const players = preview.on && splitOn() ? [video, ...laneVids.slice(0, laneCount() - 1)] : [video];
  const idle = players.every(el => el.paused && !el.seeking && el.readyState >= 2)
    && !(state.clipStop && state.clipStop.holding) && !(typeof blendRun !== "undefined" && blendRun.from);
  if (idle) {
    // Project edits replace the project object. Media identity, decoded readiness,
    // seeks and canvas size also invalidate a paused picture.
    const key = [state.project, state.mode, preview.on, preview.idx, preview.done, preview.elapsed,
      mirror.width, mirror.height, ...players.flatMap((el, n) => [el, el.currentTime, el.currentSrc, el.src,
        el.videoWidth, el.videoHeight, el.readyState, el.dataset?.base, el.dataset?.id,
        n ? lowNow[n - 1]?.clip : state.project.clips[preview.idx]])];
    const previous = drawMirror.previous;
    if (previous && previous.length === key.length && key.every((value, i) => value === previous[i])) return;
    drawMirror.previous = key;
  } else drawMirror.previous = null;
  mctx.fillStyle = "#000";
  mctx.fillRect(0, 0, mirror.width, mirror.height);
  if (inShort() && !state.project.clips.length) return;
  const clip = preview.on ? state.project.clips[preview.idx] : null;
  if (preview.on && splitOn()) {
    const boxes = laneBoxes(laneCount()), W = mirror.width, H = mirror.height;
    const lanes = [[video, clip], ...laneVids.map((el, n) => [el, lowNow[n] && lowNow[n].clip])];
    boxes.forEach(([fx, fy, fw, fh], n) => {
      const [vid, c] = lanes[n];
      if (!c) return;
      const x = Math.round(fx * W), y = Math.round(fy * H), w = Math.round((fx + fw) * W) - x, h = Math.round((fy + fh) * H) - y;
      mctx.save();
      mctx.beginPath();
      mctx.rect(x, y, w, h);
      mctx.clip();
      mctx.translate(x, y);
      if (vid.videoWidth) paintClip(vid, c, w, h);
      mctx.restore();
    });
  } else {
    if (clip && state.project.blurBg) drawBlurBackground(mirror.width, mirror.height);
    paintClip(video, clip, mirror.width, mirror.height);
  }
  paintTransition();
  const cx = mirror.width / 2;
  if (clip && state.project.watermark !== false && state.channel.handle) {
    const corner = state.project.format === "16:9";
    mctx.font = `bold ${Math.round(mirror.width * (corner ? 0.016 : 0.042))}px Arial, Helvetica, sans-serif`;
    mctx.textAlign = corner ? "right" : "center";
    mctx.textBaseline = corner ? "bottom" : "middle";
    mctx.shadowColor = "rgba(0,0,0,.1)";
    mctx.shadowOffsetX = mctx.shadowOffsetY = 1;
    mctx.fillStyle = corner ? "rgba(255,255,255,.35)" : "rgba(255,255,255,.14)";
    if (corner) mctx.fillText(state.channel.handle, mirror.width * 0.985, mirror.height * 0.97);
    else mctx.fillText(state.channel.handle, cx, mirror.height * 0.88);
    mctx.shadowColor = "transparent";
  }
  const dip = clip ? fadeAmount(clip) : 0;
  if (dip > 0) {
    mctx.fillStyle = `rgba(0,0,0,${dip})`;
    mctx.fillRect(0, 0, mirror.width, mirror.height);
  }
}

let rendering = false, publishName = "", publishTimer;
const TITLE_LIMIT = 100;

function renderChecklist() {
  // Counted as the server counts it: trimmed, an emoji as one character.
  const len = [...$("pubTitle").value.trim()].length;
  const count = $("pubCount");
  count.textContent = `${len} of ${TITLE_LIMIT}`;
  count.classList.toggle("over", len > TITLE_LIMIT);
}

async function loadPublish(name) {
  // A save still waiting belongs to the Short that was open, so it goes out before the next one takes its place.
  if (publishTimer) {
    clearTimeout(publishTimer);
    publishTimer = null;
    await savePublish();
  }
  publishName = name;
  const data = await api(`/api/publish/${name}`);
  if (name !== publishName) return;
  $("pubTitle").value = data.title;
  $("pubDesc").value = data.description;
  $("pubSaved").textContent = "";
  $("rdPub").hidden = false;
  renderChecklist();
  ytRefresh();
}

async function savePublish() {
  if (!publishName) return;
  try {
    await api(`/api/publish/${publishName}`, "POST", {title: $("pubTitle").value, description: $("pubDesc").value});
    $("pubSaved").textContent = "Saved to the Short's folder";
    return true;
  } catch (err) {
    $("pubSaved").textContent = err.message;
    return false;
  }
}

function editPublish() {
  renderChecklist();
  $("pubSaved").textContent = "Saving";
  clearTimeout(publishTimer);
  publishTimer = setTimeout(() => { publishTimer = null; savePublish(); }, 600);
}

const copyText = (text, label) => navigator.clipboard.writeText(text).then(() => toast(`${label} copied`), () => toast("Couldn't copy, select the text instead"));

const setStage = stage => { $("renderDlg").dataset.stage = stage; };

// Rendering goes on in the background: the Shorts button on the rail shows how far it is, and when it is done that button carries
// a badge until the Shorts list is opened.
let renderJob = null;
function paintRenderProgress() {
  const pct = renderJob ? renderJob.pct : null, btn = $("renderBtn"), rail = $("railShorts");
  rail.setAttribute("aria-label", renderJob ? `Your Shorts, rendering ${pct}%` : "Your Shorts");
  rail.dataset.tip = renderJob ? `Rendering ${renderJob.name}, ${pct}%` : "Your Shorts";
  const hasClips = canon().clips.length > 0;
  btn.disabled = Boolean(renderJob) || !hasClips;
  btn.title = renderJob ? `Rendering ${pct}%` : hasClips ? "Export this Short in the background" : "Add a clip to the Short before exporting";
  btn.querySelector("span").textContent = renderJob ? `Rendering ${pct}%` : "Export Short";
  paintShortsBadge();
}

async function startRender() {
  if (rendering) return;
  // The Short's own timeline, which in Clip mode is not the list on screen.
  const timeline = canon().clips;
  if (!timeline.length) return toast("Add at least one clip to the Short first");
  const name = state.project.name, len = laneTotal("top", timeline);
  rendering = true;
  renderJob = {name, pct: 0};
  shorts.failed = null;
  paintRenderProgress();
  toast(len > SHORT_LIMIT ? `Pushed to render. This Short is ${len.toFixed(1)}s, over the 60s limit.` : "Sent to render");
  try {
    await save();
    let job = await api(`/api/render/${name}`, "POST", canon());
    while (job.state === "working") {
      renderJob = {name, pct: job.pct || 0};
      paintRenderProgress();
      await new Promise(r => setTimeout(r, 700));
      job = await api(`/api/render/${name}`);
    }
    if (job.state !== "done") throw new Error(job.message || "The render failed");
    shorts.unseen.add(name);
    toast(`${name} is ready in Shorts`);
  } catch (err) {
    shorts.failed = {name, message: err.message};
    toast(`Render failed: ${err.message}`);
  } finally {
    rendering = false;
    renderJob = null;
    paintRenderProgress();
    refreshShorts();
  }
}

const LAST_PROJECT_KEY = "clipbench.lastProject";
const rememberProject = name => { try { localStorage.setItem(LAST_PROJECT_KEY, name); } catch { /* it just isn't remembered */ } };
const lastProject = () => { try { return localStorage.getItem(LAST_PROJECT_KEY); } catch { return null; } };

async function loadProject(name) {
  const clean = name.trim();
  if (!/^[A-Za-z0-9_-]{1,60}$/.test(clean)) {
    toast("Use letters, numbers, dashes or underscores in the name");
    $("pname").value = state.project.name;
    return;
  }
  saveEditorSession();
  sessionReady = false;
  await flushSave();
  try {
    const data = await api(`/api/project/${clean}`);
    state.profileId = data.profile_id || 'default';
    try { localStorage.setItem('clipbench.profile', state.profileId); } catch {}
    if (preview.on) closePreview();
    video.pause();
    const stored = {name: clean, hiddenSources: Array.isArray(data.hiddenSources) ? data.hiddenSources.filter(path => typeof path === "string") : [], hook: data.hook || "", frame: data.frame || "auto", layout: data.layout || "title", format: data.format || "9:16", template: data.template || "full", capSize: data.capSize || 0, normalize: Boolean(data.normalize), watermark: data.watermark !== false, blurBg: Boolean(data.blurBg), fade: data.fade || 0, audio: data.audio || [], clips: data.clips || [], bank: data.bank || (data.clips || []).map(c => ({...c}))};
    state.project = orient(stored, state.mode);
    state.sel = state.project.clips.length ? 0 : -1;
    state.audioSel = null;
    resetHistory();
    dropVideo();
    await loadAssets();
    rememberProject(clean);
    await loadChannel();
    await restoreEditorSession();
    paintSaveState($("saved"), "saved");
  } catch (err) {
    toast(`Couldn't open ${clean}: ${err.message}`);
  }
  sessionReady = true;
  if (document.activeElement !== $("pname")) $("pname").value = state.project.name;
  render();
}

// While streaming Enter clips the selection, except on a control that has its own use for it.
const ownsEnter = el => Boolean(el.closest("button, a, [role=slider]")) && !["markIn", "markOut", "liveClip", "liveIn", "liveOut", "clipIt"].includes(el.id);
function typing(e) {
  return ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName) || e.target.isContentEditable;
}
document.addEventListener("keydown", e => {
  // A dialog sits over the editor, so its keys stay in the dialog.
  if (document.querySelector("dialog[open]")) return;
  const mod = e.metaKey || e.ctrlKey, k = e.key.toLowerCase();
  if (mod && !typing(e) && (!preview.on || state.mode === "short") && (k === "z" || k === "y")) {
    e.preventDefault();
    return (k === "y" || e.shiftKey) ? redo() : undo();
  }
  if (state.mode === "short" && e.altKey && !mod && !typing(e) && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
    e.preventDefault();
    return moveSelected(e.key === "ArrowLeft" ? -1 : 1);
  }
  if (typing(e) || e.metaKey || e.ctrlKey || e.altKey) return;
  if (streaming() && e.shiftKey && k === "m") { e.preventDefault(); return markLiveMoment(); }
  if (preview.on) {
    if (e.key === " " && e.target.tagName === "BUTTON") return;
    const pk = {" ": togglePreview, ArrowLeft: () => stepPreview(-1), ArrowRight: () => stepPreview(1)};
    if (state.mode === "short") Object.assign(pk, {ArrowUp: () => selectLane(-1), ArrowDown: () => selectLane(1), Delete: removeSelected, Backspace: removeSelected, s: splitInShort, d: duplicateSelected, m: () => $("thMute").click()});
    else pk.Escape = closePreview;
    const act = pk[e.key] || pk[e.key.toLowerCase()];
    if (act) { e.preventDefault(); act(); }
    return;
  }
  const step = e.shiftKey ? 1 : FRAME;
  const keys = {
    " ": togglePlay, i: markIn, o: markOut, s: splitClip, d: () => (inShort() && state.audioSel ? duplicateAudio(state.audioSel) : duplicateClip(state.sel)), j: () => seekBy(-5), l: () => seekBy(5),
    ArrowLeft: () => seekBy(-step), ArrowRight: () => seekBy(step),
    ...(!ownsEnter(e.target) ? {Enter: streaming() ? liveClip : clipIt} : {}),
    Tab: () => jumpScene(e.shiftKey ? -1 : 1), m: toggleMute, ArrowUp: () => nudgeVolume(1), ArrowDown: () => nudgeVolume(-1),
    ",": () => bumpSpeed(-1), ".": () => bumpSpeed(1), "[": () => trimSel("in"), "]": () => trimSel("out"),
    "=": () => zoomAt(0.5, anchorTime()), "+": () => zoomAt(0.5, anchorTime()), "-": () => zoomAt(2, anchorTime()),
    0: () => { fitView(); redrawView(); }, z: zoomToClip,
    Delete: () => removeClip(state.sel), Backspace: () => removeClip(state.sel),
  };
  if (e.key === "Tab" && e.target !== document.body) return;
  const fn = keys[e.key] || keys[e.key.toLowerCase()];
  if (fn) { e.preventDefault(); fn(); }
});

$("playBtn").onclick = togglePlay;
$("prevBtn").onclick = () => jumpScene(-1);
$("nextBtn").onclick = () => jumpScene(1);
$("clipIt").onclick = clipIt;
$("delBtn").onclick = () => removeClip(state.sel);
$("muteBtn").onclick = toggleMute;
$("markIn").onclick = markIn;
$("markOut").onclick = markOut;
$("splitBtn").onclick = splitClip;
$("strip").onclick = e => {
  if (!state.current) return;
  video.currentTime = timeFromX(e.clientX, $("strip").getBoundingClientRect());
  updateTime();
};
// Grab the playhead, or press on the ruler, and drag to scrub through the video.
function scrubClip(e) {
  if (!state.current || e.button) return;
  e.preventDefault();
  const move = ev => {
    video.currentTime = Math.min(timeFromX(ev.clientX, $("strip").getBoundingClientRect()), video.duration || Infinity);
    updateTime();
  };
  const stop = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
    window.removeEventListener("pointercancel", stop);
    document.body.classList.remove("scrubbing");
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop);
  window.addEventListener("pointercancel", stop);
  document.body.classList.add("scrubbing");
  move(e);
}
$("ruler").addEventListener("pointerdown", scrubClip);

const onTimelineWheel = e => {
  if (!state.current) return;
  e.preventDefault();
  const rect = $("strip").getBoundingClientRect();
  if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) panBy((e.deltaX || e.deltaY) / rect.width * span());
  else zoomAt(Math.exp(e.deltaY * (e.ctrlKey ? 0.012 : 0.004)), timeFromX(e.clientX, rect));
};
$("strip").parentElement.addEventListener("wheel", onTimelineWheel, {passive: false});
$("ruler").addEventListener("wheel", onTimelineWheel, {passive: false});
const nav = $("nav");
const navTo = ev => {
  const r = nav.getBoundingClientRect(), mid = Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)) * dur();
  setView(mid - span() / 2, mid + span() / 2);
  redrawView();
};
nav.onpointerdown = ev => { nav.setPointerCapture(ev.pointerId); navTo(ev); nav.onpointermove = navTo; };
nav.onpointerup = () => { nav.onpointermove = null; };
function renderShortOptions() {
  $("capSizeInput").value = captionSize();
  $("capSizeOut").textContent = `${captionSize()}`;
  $("normInput").checked = Boolean(state.project.normalize);
  $("wmInput").checked = state.project.watermark !== false;
  $("blurInput").checked = Boolean(state.project.blurBg);
}
$("capSizeInput").oninput = e => {
  const size = Number(e.target.value);
  $("capSizeOut").textContent = `${size}`;
  state.project = {...state.project, capSize: size};
  $("cCap").dataset.at = "";
  placeCaption(state.project.clips[preview.idx]);
  changed(true, "capsize");
};
$("wmInput").onchange = e => { state.project = {...state.project, watermark: e.target.checked}; changed(); };
$("blurInput").onchange = e => { state.project = {...state.project, blurBg: e.target.checked}; changed(); };
$("normInput").onchange = e => { state.project = {...state.project, normalize: e.target.checked}; changed(); };
$("undoBtn").onclick = undo;
$("redoBtn").onclick = redo;
$("closePreview").onclick = closePreview;
$("thPlay").onclick = togglePreview;
$("thPrev").onclick = () => stepPreview(-1);
$("thNext").onclick = () => stepPreview(1);
$("renderBtn").onclick = startRender;
$("pubTitle").oninput = editPublish;
$("pubDesc").oninput = editPublish;
$("copyTitle").onclick = () => copyText($("pubTitle").value, "Title");
$("copyDesc").onclick = () => copyText($("pubDesc").value, "Description");
$("rdPub").onsubmit = e => e.preventDefault();
$("rdAgain").onclick = () => { $("rdVideo").pause(); $("renderDlg").close(); startRender(); };
$("rdClose").onclick = $("rdX").onclick = () => { $("rdVideo").pause(); $("renderDlg").close(); };
$("renderDlg").addEventListener("close", () => $("rdVideo").pause());
// The project box opens a window of project cards: pick one, start a new one, or use the dots on a card.
let projectNames = [];
let pNaming = null; // {copy: source or null} while the name field is up
const PROJECT_NAME = /^[A-Za-z0-9_-]{1,60}$/;
const projDlg = $("projDlg"), pbox = $("pname");

const projectLength = clips => {
  try { return laneTotal("top", clips); } catch { return 0; }
};

// Each project's clip count and the length of its top lane, read from the project itself.
async function projectInfo() {
  const info = {};
  let cover = {};
  try { cover = Object.fromEntries((await api("/api/home-recent?all=1")).map(p => [p.name, p])); } catch { /* covers are optional */ }
  await Promise.all(projectNames.map(async name => {
    try {
      const data = name === state.project.name ? canon() : await api(`/api/project/${name}`);
      const clips = data.clips?.length ? data.clips : (data.bank || []);
      info[name] = {clips: clips.length, length: projectLength(clips), thumb: cover[name]?.thumb || null, updated: cover[name]?.updated_at || 0};
    } catch { info[name] = null; }
  }));
  return info;
}

function projectCard(name, info) {
  const here = name === state.project.name;
  const card = document.createElement("article");
  card.className = "projrow";
  if (here) card.setAttribute("aria-current", "true");
  card.tabIndex = 0;
  const made = (typeof shorts !== "undefined" ? shorts.rows : []).find(s => s.name === name);
  const pic = made ? `/short-thumb/${encodeURIComponent(name)}.jpg?v=${Math.floor(made.rendered_at)}` : info?.thumb;
  const mini = pic ? `<img alt="" loading="lazy" src="${pic}">` : '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/><path d="M3 9h18"/></svg>';
  const count = info ? `${info.clips} clip${info.clips === 1 ? "" : "s"}` : "";
  const when = info?.updated ? new Date(info.updated * 1000).toLocaleDateString(undefined, {month: "short", day: "numeric"}) : "";
  const onYoutube = made && made.upload.state === "done";
  card.innerHTML = `<div class="pmini">${mini}</div>` +
    `<div class="pmeta"><p>${esc(name)}</p><small>${esc([count, when, onYoutube ? "On YouTube" : ""].filter(Boolean).join(" · "))}</small></div>` +
    `<button class="pdots" aria-label="More for ${esc(name)}" aria-haspopup="menu" aria-expanded="false"><svg class="i"><use href="#dots"/></svg></button>`;
  card.onclick = () => chooseProject(name);
  card.onkeydown = e => { if (e.target === card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); chooseProject(name); } };
  const dots = card.querySelector(".pdots");
  dots.onclick = e => { e.stopPropagation(); toggleCardMenu(card, dots, name); };
  return card;
}

function closeCardMenu() {
  projDlg.querySelectorAll(".pcmenu").forEach(m => { m.previousElementSibling?.setAttribute?.("aria-expanded", "false"); m.remove(); });
  projDlg.querySelectorAll('.pdots[aria-expanded="true"]').forEach(d => d.setAttribute("aria-expanded", "false"));
}

// The card's menu. More actions go here as they come: it is just a list of [label, icon, run, danger].
function toggleCardMenu(card, dots, name) {
  const open = dots.getAttribute("aria-expanded") === "true";
  closeCardMenu();
  if (open) return;
  dots.setAttribute("aria-expanded", "true");
  const actions = [
    ...(name === state.project.name ? [] : [["Open", "#r-shorts", () => chooseProject(name)]]),
    ["Duplicate", "#copy", () => startNaming(name)],
    ["Delete", "#trash", () => askDelete(name), true],
  ];
  const menu = document.createElement("div");
  menu.className = "pcmenu";
  menu.setAttribute("role", "menu");
  for (const [label, icon, run, danger] of actions) {
    const b = document.createElement("button");
    b.setAttribute("role", "menuitem");
    if (danger) b.className = "danger";
    b.innerHTML = `<svg class="i"><use href="${icon}"/></svg>${label}`;
    b.onclick = e => { e.stopPropagation(); closeCardMenu(); run(); };
    menu.append(b);
  }
  dots.after(menu);
  const at = dots.getBoundingClientRect(), room = innerHeight - at.bottom - 8;
  menu.style.left = `${Math.max(8, at.right - menu.offsetWidth)}px`;
  menu.style.top = `${room >= menu.offsetHeight ? at.bottom + 4 : at.top - menu.offsetHeight - 4}px`;
  menu.querySelector("button").focus();
}

// Shown where the rows would be, so it sits right under the search instead of at the bottom of the flyout.
function noProjects(typed) {
  const box = document.createElement("div");
  box.className = "pnone";
  const say = document.createElement("p");
  say.textContent = typed ? `No project called “${typed}”.` : "No projects yet. Choose New project to start.";
  box.append(say);
  if (typed) {
    const row = document.createElement("div");
    row.className = "pnonerow";
    const clear = Object.assign(document.createElement("button"), {textContent: "Clear search"});
    clear.onclick = () => { showSearch(false); paintProjects(); };
    row.append(clear);
    if (PROJECT_NAME.test(typed)) {
      const make = Object.assign(document.createElement("button"), {textContent: `Create ${typed}`, className: "go"});
      make.onclick = () => { startNaming(null); $("pName").value = typed; checkName(); };
      row.append(make);
    }
    box.append(row);
  }
  return box;
}

async function paintProjects() {
  const q = $("pSearch").value.trim().toLowerCase();
  const info = await projectInfo();
  const here = state.project.name;
  const names = [...new Set(projectNames)].filter(n => n.toLowerCase().includes(q)).sort((a, b) => (b === here) - (a === here));
  $("pGrid").replaceChildren(...(names.length ? names.map(n => projectCard(n, info[n])) : [noProjects($("pSearch").value.trim())]));
}

// The flyout drops out to the right of the sidebar, level with the project box.
function placeProjects() {
  const box = pbox.getBoundingClientRect(), side = pbox.closest(".side");
  const edge = side ? side.getBoundingClientRect().right : box.right;
  const h = Math.min(420, innerHeight - 24);
  projDlg.style.left = `${Math.round(Math.max(12, Math.min(edge + 8, innerWidth - Math.min(360, innerWidth - 24) - 12)))}px`;
  projDlg.style.top = `${Math.round(Math.max(12, Math.min(box.top, innerHeight - h - 12)))}px`;
}

// Keep the title and close action visible while switching the search/name field.
function headerMode(mode) {
  $("pTitle").textContent = mode === "name" ? (pNaming?.copy ? "Copy project" : "New project") : "Projects";
  $("pSearchBtn").hidden = $("pNew").hidden = mode !== "icons";
  $("pSearchBox").hidden = mode !== "search";
  $("pNameBox").hidden = mode !== "name";
  $("pGrid").hidden = mode === "name";
  if (mode !== "search") $("pSearch").value = "";
  if (mode !== "name") $("pNameHint").textContent = "";
}

function showSearch(on) {
  headerMode(on ? "search" : "icons");
  if (on) $("pSearch").focus();
}

function endNaming() {
  pNaming = null;
  headerMode("icons");
}

function openProjectModal() {
  pNaming = null;
  headerMode("icons");
  if (!projDlg.open) projDlg.show();
  placeProjects();
  paintProjects();
}

// The copy's name starts as name-copy, then name-copy2, name-copy3.
function copyName(name) {
  const base = name.replace(/-copy\d*$/, "").slice(0, 50);
  for (let n = 1; ; n++) {
    const next = `${base}-copy${n > 1 ? n : ""}`;
    if (!projectNames.includes(next)) return next;
  }
}

function startNaming(copy) {
  pNaming = {copy};
  headerMode("name");
  const input = $("pName"), label = copy ? `Name the copy of ${copy}` : "Name your project";
  input.placeholder = label;
  input.setAttribute("aria-label", label);
  $("pNameGo").textContent = copy ? "Copy" : "Create";
  input.value = copy ? copyName(copy) : "";
  input.focus();
  input.select();
  checkName();
}

function checkName() {
  const typed = $("pName").value.trim();
  const hint = $("pNameHint");
  const ok = PROJECT_NAME.test(typed);
  hint.textContent = !typed ? "" : !ok ? "Use letters, numbers, dashes or underscores" : projectNames.includes(typed) ? `${typed} already exists. Enter opens it` : "";
  hint.classList.toggle("err", Boolean(typed) && !ok);
  $("pNameBox").classList.toggle("bad", Boolean(typed) && !ok);
  $("pNameGo").disabled = !ok;
}

function submitName() {
  const typed = $("pName").value.trim();
  if (!PROJECT_NAME.test(typed)) return toast("Use letters, numbers, dashes or underscores");
  const copy = pNaming && pNaming.copy;
  pNaming = null;
  projDlg.close();
  if (projectNames.includes(typed)) loadProject(typed);
  else if (copy) duplicateProject(copy, typed);
  else createProject(typed);
}

let returnToProjectsAfterDelete = false;
function askDelete(name) {
  const made = (typeof shorts !== "undefined" ? shorts.rows : []).find(s => s.name === name);
  $("pConfirmTitle").textContent = `Delete ${name}?`;
  $("pConfirmText").textContent = `Its clips, sounds and edits are removed.${made ? " The rendered Short and anything on YouTube stay." : ""} Your videos stay on disk.`;
  returnToProjectsAfterDelete = true;
  projDlg.close();
  $("pConfirm").showModal();
  $("pConfirmGo").onclick = () => deleteProject(name);
  $("pConfirmNo").focus();
}

async function deleteProject(name) {
  returnToProjectsAfterDelete = false;
  $("pConfirm").close();
  const wasOpen = name === state.project.name;
  if (wasOpen) {
    clearTimeout(saveTimer);
    if (save.running) await save.running;
    clearTimeout(saveTimer);
    unsaved = false;
  }
  else await flushSave();
  try {
    await api("/api/project-delete", "POST", {name});
  } catch (err) {
    return toast(`Couldn't delete ${name}: ${err.message}`);
  }
  projectNames = projectNames.filter(n => n !== name);
  if (wasOpen) {
    const next = projectNames[projectNames.length - 1];
    if (next) await loadProject(next);
    else {
      try { localStorage.removeItem(LAST_PROJECT_KEY); localStorage.removeItem(`clipbench.session:${name}`); } catch {}
      sessionReady = false;
      if (preview.on) closePreview();
      video.pause();
      window.location.assign("/");
      return;
    }
  }
  toast(`Deleted ${name}`);
  if (projDlg.open) paintProjects();
}

// A new project starts empty: no clips, no sounds, the default look.
async function createProject(name, persist = true) {
  await flushSave();
  if (preview.on) closePreview();
  video.pause();
  state.project = {name, hook: "", frame: "auto", layout: "title", format: "9:16", template: "full", capSize: 0, normalize: false, watermark: true, fade: 0, audio: [], clips: [], other: []};
  state.sel = -1;
  state.audioSel = null;
  resetHistory();
  dropVideo();
  pbox.value = name;
  if (persist) await save();
  await loadAssets();
  if (persist) rememberProject(name);
  paintSaveState($("saved"), "saved");
  render();
}

// The copy has the same clips, sounds and settings, and from here on is its own project.
async function duplicateProject(source, name) {
  await flushSave();
  try {
    const data = await api(`/api/project/${source}`);
    await api(`/api/project/${name}`, "PUT", {...data, name});
    await api("/api/project-copy", "POST", {from: source, to: name});
    projectNames = [...projectNames, name];
  } catch (err) {
    return toast(`Couldn't copy ${source}: ${err.message}`);
  }
  await loadProject(name);
  paintSaveState($("saved"), "saved");
}

function chooseProject(name) {
  projDlg.close();
  pbox.value = name;
  if (name === state.project.name) return;
  loadProject(name);
}

pbox.readOnly = true;
pbox.onkeydown = e => { if (["Enter", " ", "ArrowDown"].includes(e.key)) { e.preventDefault(); openProjectModal(); } };
const toggleProjects = () => { if (projDlg.open) projDlg.close(); else openProjectModal(); };
pbox.onclick = toggleProjects;
$("pchev").onclick = toggleProjects;
$("pNew").onclick = () => startNaming(null);
$("pPickerClose").onclick = () => projDlg.close();
$("pSearch").oninput = paintProjects;
$("pName").oninput = checkName;
$("pName").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); submitName(); } };
$("pNameGo").onclick = submitName;
$("pNameCancel").onclick = endNaming;
$("pConfirmNo").onclick = () => $("pConfirm").close();
$("pConfirm").addEventListener("close", () => { if (returnToProjectsAfterDelete) { returnToProjectsAfterDelete = false; openProjectModal(); } });
$("pSearchBtn").onclick = () => showSearch(true);
$("pSearchX").onclick = () => { showSearch(false); paintProjects(); };
projDlg.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  e.stopPropagation();
  if (!$("pNameBox").hidden) endNaming();
  else if (!$("pSearchBox").hidden) { showSearch(false); paintProjects(); }
  else projDlg.close();
});
projDlg.addEventListener("click", e => { if (!e.target.closest(".pdots, .pcmenu")) closeCardMenu(); });
// A non-modal flyout: a press anywhere outside it closes it.
document.addEventListener("pointerdown", e => { if (projDlg.open && !e.target.closest("#projDlg, .pbox")) projDlg.close(); }, true);
window.addEventListener("resize", () => { if (projDlg.open) placeProjects(); });
projDlg.addEventListener("close", () => { closeCardMenu(); pbox.value = state.project.name; });
$("addBtn").onclick = () => $("srcPick").click();
$("srcPick").onchange = e => { dropFiles(Array.from(e.target.files)); e.target.value = ""; };
let downloading = false, downloadFailed = false;
function paintDownloadState() {
  $("dlGo").disabled = downloading;
  $("dlGo").textContent = downloading ? "Downloading…" : downloadFailed ? "Retry download" : "Download";
  $("dlUrl").readOnly = downloading;
  $("dlDlg").setAttribute("aria-busy", String(downloading));
}
function showDownload(text, pct, isError) {
  $("dlStatus").textContent = text;
  $("dlStatus").classList.toggle("err", Boolean(isError));
  const known = typeof pct === "number" && Number.isFinite(pct);
  const bar = $("dlBar");
  bar.hidden = !text || Boolean(isError) || !downloading;
  bar.classList.toggle("indeterminate", !known);
  if (known) {
    const value = Math.max(0, Math.min(100, pct));
    $("dlFill").style.width = `${value}%`;
    bar.setAttribute("aria-valuenow", String(Math.round(value)));
  } else bar.removeAttribute("aria-valuenow");
  bar.setAttribute("aria-valuetext", text || "Not downloading");
}

async function startDownload() {
  if (downloading) return;
  const url = $("dlUrl").value.trim(), project = state.project.name;
  if (!url) {
    $("dlUrl").setAttribute("aria-invalid", "true");
    $("dlUrl").focus();
    return showDownload("Paste a video link to get started", null, true);
  }
  downloading = true;
  downloadFailed = false;
  paintDownloadState();
  showDownload("Preparing the download…", null);
  try {
    let job = await api("/api/download", "POST", {url, project});
    while (job.state === "working") {
      const pct = typeof job.pct === "number" ? job.pct : null;
      const message = job.message || "Downloading video";
      showDownload(`${message}${pct !== null ? ` · ${Math.round(pct)}%` : ""}`, pct);
      await new Promise(r => setTimeout(r, 800));
      job = await api(`/api/download/${job.id}`);
    }
    if (job.state !== "done") throw new Error(job.message || "The download failed. Check the link and try again");
    if (state.project.name === project) {
      showDownload("Opening the video…", 100);
      await refreshLibrary();
      const v = state.library.find(x => x.path === job.file);
      if (v) openVideo(v);
    }
    $("dlDlg").close();
    $("dlUrl").value = "";
    showDownload("", null);
    toast(state.project.name === project ? "Download finished" : `Download finished in ${project}`);
  } catch (err) {
    downloadFailed = true;
    showDownload(err.message || "Couldn't download this video. Check the link and try again", null, true);
  } finally {
    downloading = false;
    paintDownloadState();
  }
}
$("dlBtn").onclick = () => { $("dlDlg").showModal(); $("dlUrl").focus(); };
$("dlUrl").addEventListener("input", () => {
  $("dlUrl").removeAttribute("aria-invalid");
  if (!downloading && $("dlStatus").classList.contains("err")) {
    downloadFailed = false;
    showDownload("", null);
    paintDownloadState();
  }
});
$("dlGo").onclick = startDownload;
$("dlUrl").onkeydown = e => { if (e.key === "Enter" && !downloading) startDownload(); };
$("dlClose").onclick = () => $("dlDlg").close();

function setSideTab(which) {
  $("favPanel").hidden = which !== "fav";
  $("audioPanel").hidden = which !== "audio";
  $("mediaPanel").hidden = which !== "media";
  $("dlBtn").hidden = which !== "media";
  $("tabMedia").setAttribute("aria-selected", which === "media");
  $("tabFav").setAttribute("aria-selected", which === "fav");
  $("tabAudio").setAttribute("aria-selected", which === "audio");
  if (which === "media") renderLibrary();
  else if (which === "fav") renderFavs();
}
$("tabMedia").onclick = () => setSideTab("media");
$("tabFav").onclick = () => setSideTab("fav");

const sameMoment = (a, b) => a.src === b.src && Math.abs(a.in - b.in) < 0.05 && Math.abs(a.out - b.out) < 0.05;
// Restrict moment comparisons to the same source while preserving the trim tolerance.
function momentFinder(clips) {
  const sources = new Map();
  clips.forEach((c, index) => {
    let group = sources.get(c.src);
    if (!group) sources.set(c.src, group = []);
    group.push({clip: c, index});
  });
  return c => sources.get(c.src)?.find(({clip}) => sameMoment(clip, c))?.index ?? -1;
}

function momentLookup(clips) {
  const find = momentFinder(clips);
  return c => find(c) >= 0;
}

async function saveFavorites(next) {
  const before = state.favorites;
  state.favorites = next;
  renderFavs();
  renderTray();
  try {
    const payload = referencedThumbs(next);
    const response = await api(`/api/favorites${projectQuery()}`, "PUT", payload);
    state.favorites = referencedThumbs(state.favorites, rememberThumbnails(payload, response));
  } catch (err) {
    state.favorites = before;
    renderFavs();
    renderTray();
    toast(`Couldn't update Saved: ${err.message}`);
  }
}
function toggleFavorite(i) {
  const c = state.project.clips[i];
  if (!c) return;
  const has = state.favorites.some(f => sameMoment(f, c));
  saveFavorites(has ? state.favorites.filter(f => !sameMoment(f, c)) : [...state.favorites, {...c}]);
  toast(has ? "Removed from Saved" : "Saved. Find it in the Saved tab");
}
function addFavorite(f) {
  if (!byPath(f.src) && !cutIds.has(cutKey(f))) return toast("That clip's video is gone and it was never saved as a file");
  if (state.mode === "short") {
    state.sel = insertClip(f, "top");
    changed();
    return restartPreviewAt(state.sel);
  }
  state.project = {...state.project, clips: [...state.project.clips, {...f}]};
  state.sel = state.project.clips.length - 1;
  changed();
}
let favFilter = "";
function renameFavorite(f, label) {
  const clean = label.trim().slice(0, 60);
  if (clean === (f.label || "")) return;
  saveFavorites(state.favorites.map(x => (x === f ? {...x, label: clean} : x)));
}
function renderFavs() {
  const box = $("favList"), bar = $("favBar");
  if (!state.favorites.length) favFilter = $("favSearch").value = "";
  // A search still filtering the list keeps its box, so it can be cleared.
  bar.hidden = state.favorites.length < 6 && !favFilter;
  $("favCount").textContent = state.favorites.length ? `${state.favorites.length} saved` : "";
  if ($("favPanel").hidden) return;
  box.innerHTML = "";
  if (!state.favorites.length) {
    box.innerHTML = '<div class="favempty"><svg class="i"><use href="#star"/></svg><b>Nothing saved yet</b><span>Star a clip in your Short to keep it here for every Short you make.</span></div>';
    return;
  }
  const words = favFilter.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = state.favorites.filter(f => {
    const v = byPath(f.src), hay = `${f.label || ""} ${v ? v.name : ""} ${f.caption || ""}`.toLowerCase();
    return words.every(w => hay.includes(w));
  });
  if (!shown.length) {
    box.innerHTML = `<div class="favempty"><b>No match</b><span>Nothing saved matches "${esc(favFilter)}".</span></div>`;
    return;
  }
  const isUsed = momentLookup(state.project.clips);
  const previousCache = renderFavs.cache || new WeakMap();
  const cache = renderFavs.cache = new WeakMap();
  shown.forEach(f => {
    const playable = Boolean(byPath(f.src)) || cutIds.has(cutKey(f)), used = isUsed(f);
    const title = f.label || clipName(f);
    const key = [playable, used, title, f.src, f.in, f.out, f.thumb, f.label, outLen(f), volumeOf(f)];
    const previous = previousCache.get(f);
    if (previous && key.every((value, n) => value === previous.key[n])) {
      cache.set(f, previous);
      box.appendChild(previous.node);
      return;
    }
    const d = document.createElement("div");
    d.className = "fav" + (playable ? "" : " gone");
    d.draggable = playable;
    d.ondragstart = e => {
      e.dataTransfer.setData(CLIP_MIME, JSON.stringify({src: f.src, in: f.in, out: f.out, note: f.label || "", thumb: f.thumb || "", volume: f.volume}));
      e.dataTransfer.effectAllowed = "copy";
    };
    d.innerHTML = `<div class="pic">${f.thumb ? `<img alt="" src="${f.thumb}">` : ""}<span class="len num">${outLen(f).toFixed(1)}s</span>` +
      `${used ? '<span class="used">In Short</span>' : ""}` +
      `<button class="favadd" aria-label="Add ${esc(title)} to the Short"${playable ? "" : " disabled"}><svg class="i"><use href="#plus"/></svg>Add to Short</button>` +
      `<button class="favmute${volumeOf(f) === 0 ? " on" : ""}" aria-label="${volumeOf(f) === 0 ? "Turn the sound on for" : "Mute"} ${esc(title)}" aria-pressed="${volumeOf(f) === 0}" title="${volumeOf(f) === 0 ? "Muted. Click for sound" : "Mute this clip"}"><svg class="i"><use href="${volumeOf(f) === 0 ? "#mute" : "#vol"}"/></svg></button>` +
      `<button class="favdel" aria-label="Remove ${esc(title)} from Saved" title="Remove from Saved"><svg class="i"><use href="#trash"/></svg></button></div>` +
      `<input class="favname" value="${esc(f.label || "")}" placeholder="${esc(title)}" aria-label="Clip name" maxlength="60" spellcheck="false">` +
      `<small class="num">${playable ? fmt(f.in) + " to " + fmt(f.out) : "Video removed before it was saved"}</small>`;
    d.querySelector(".favadd").onclick = () => addFavorite(f);
    d.querySelector(".favmute").onclick = () => saveFavorites(state.favorites.map(x => (x === f ? {...x, volume: volumeOf(x) === 0 ? 1 : 0} : x)));
    d.querySelector(".favdel").onclick = () => saveFavorites(state.favorites.filter(x => x !== f));
    const name = d.querySelector(".favname");
    name.onkeydown = e => { if (e.key === "Enter") name.blur(); if (e.key === "Escape") { name.value = f.label || ""; name.blur(); } };
    name.onchange = () => renameFavorite(f, name.value);
    cache.set(f, {key, node: d});
    box.appendChild(d);
  });
}
$("favSearch").oninput = e => { favFilter = e.target.value; renderFavs(); };

let currentTab = "clip";
function setTab(which) {
  currentTab = which;
  $("panelClip").hidden = which !== "clip";
  $("panelDetails").hidden = which !== "details";
  $("panelShort").hidden = which !== "short";
  $("panelShorts").hidden = which !== "shorts";
  $("tabClip").setAttribute("aria-selected", which === "clip");
  $("tabDetails").setAttribute("aria-selected", which === "details");
  $("tabShort").setAttribute("aria-selected", which === "short");
  $("tabShorts").setAttribute("aria-selected", which === "shorts");
  if (which === "shorts") refreshShorts();
  if (which === "details" && state.mode === "clip") renderSourceClipDetails();
}
$("tabClip").onclick = () => setTab("clip");
$("tabShort").onclick = () => setTab("short");
$("tabShorts").onclick = () => setTab("shorts");
function watchPlayers(list) {
  list.forEach(el => {
    el.addEventListener("play", updateTime);
    el.addEventListener("pause", updateTime);
  });
}
watchPlayers(videos);

// The open project's sources and Saved clips, fetched again whenever the project changes.
async function loadAssets() {
  await refreshLibrary();
  state.favorites = await api(`/api/favorites${projectQuery()}`).catch(() => []);
  let renderPending = false;
  const cutReady = id => {
    if (!id || renderPending) return;
    renderPending = true;
    requestAnimationFrame(() => { renderPending = false; renderFavs(); });
  };
  for (const f of state.favorites) if (!cutIds.has(cutKey(f))) requestCut(f).then(cutReady);
  renderFavs();
}

async function refreshLibrary() {
  state.library = await api(`/api/library${projectQuery()}`);
  if (state.current) state.current = state.library.find(v => v.id === state.current.id) || null;
  render();
  if (typeof refreshUnheard === "function") refreshUnheard();
}

// The server cuts every existing clip in the background; show how far along it is.
async function watchCuts() {
  const el = $("cutStatus");
  for (let n = 0; n < 600; n++) {
    let p;
    try { p = await api("/api/cuts/progress"); } catch { return; }
    const busy = p.total > 0 && p.done < p.total;
    el.hidden = !busy;
    if (busy) el.textContent = `Preparing clips, ${p.done} of ${p.total}`;
    else if (p.total || n > 4) return;
    await new Promise(r => setTimeout(r, 1500));
  }
}

// Browser-local view state is separate from saved project content and undo history.
let sessionReady = false;
const sessionKey = () => `clipbench.session:${state.project.name}`;
function saveEditorSession() {
  if (!sessionReady) return;
  const c = state.project.clips[state.sel];
  const data = {version: 1, mode: state.mode, source: state.current?.path || null,
    selected: c ? {src: c.src, in: c.in, out: c.out, index: state.sel} : null,
    time: Number.isFinite(tnow()) ? tnow() : 0, playingClip: preview.on ? preview.idx : null,
    view: {...view}, zoom: tlZoom, scroll: stlBody.scrollLeft};
  try { localStorage.setItem(sessionKey(), JSON.stringify(data)); } catch { /* View persistence is optional. */ }
}
async function restoreEditorSession() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem(sessionKey()) || "null"); } catch {}
  if (!saved || saved.version !== 1) { sessionReady = true; return; }
  const mode = saved.mode === "short" ? "short" : "clip";
  // Set the orientation without initiating playback while restoring.
  if (state.mode !== mode) {
    if (preview.on) closePreview();
    usePreviewPlayers(mode === "short");
    state.project = orient(canon(), mode);
    state.mode = mode;
    resetHistory();
    setSideTab("media");
  }
  const selected = saved.selected;
  state.sel = selected ? state.project.clips.findIndex((c, i) => i === selected.index && c.src === selected.src && c.in === selected.in && c.out === selected.out) : -1;
  render();
  if (mode === "short") {
    preview.hold = true;
    preview.on = true;
    $("theater").hidden = false;
    layoutCard(); buildSegs(); fitPhone();
    const i = Number.isInteger(saved.playingClip) ? saved.playingClip : state.sel;
    const c = state.project.clips[i];
    if (c) startPreviewAt(i, Math.min(c.out, Math.max(c.in, Number(saved.time) || c.in)));
    tlZoom = Math.min(12, Math.max(1, Number(saved.zoom) || 1));
    renderShortTl(); syncZoomUi();
    stlBody.scrollLeft = Math.max(0, Number(saved.scroll) || 0);
  } else {
    const source = byPath(saved.source);
    if (source) {
      await openVideo(source, Math.min(source.duration || Infinity, Math.max(0, Number(saved.time) || 0)));
      if (saved.view && Number.isFinite(saved.view.s) && Number.isFinite(saved.view.e) && saved.view.s >= 0 && saved.view.e > saved.view.s && saved.view.e <= source.duration) {
        view = {...saved.view}; redrawView();
      }
    }
  }
  sessionReady = true;
}
window.addEventListener("pagehide", saveEditorSession);
document.addEventListener("visibilitychange", () => { if (document.hidden) saveEditorSession(); });
setInterval(() => { if (!document.hidden) saveEditorSession(); }, 2000);

// The title card and the watermark labels name the connected YouTube channel, or say what to connect when none is.
function paintChannel() {
  const {name = "", handle = ""} = state.channel;
  $("cName").textContent = name;
  $("cHandle").textContent = handle;
  for (const el of document.querySelectorAll(".wmHandle")) el.textContent = handle || "your channel handle (connect YouTube to set it)";
}

async function loadChannel() {
  const status = await api("/api/youtube").catch(() => null);
  state.channel = (status && status.channel) || {};
  paintChannel();
}

async function init() {
  try {
    const names = await api("/api/projects");
    projectNames = names;
    const request = new URLSearchParams(location.search);
    if (names.length && request.get("new") !== "1") {
      const preferred = request.get("project") || lastProject();
      const open = names.includes(preferred) ? preferred : names[names.length - 1];
      $("pname").value = open;
      await loadProject(open);
    } else {
      await loadAssets();
    }
  } catch (err) {
    toast(`Couldn't reach the server: ${err.message}`);
  }
  sessionReady = true;
  render();
  const entry = new URLSearchParams(location.search);
  if (entry.get("add") === "1" && entry.get("project") === state.project.name) {
    setMode("clip");
    $("addVideosContext").textContent = `Bring footage into “${state.project.name}” to start editing.`;
    $("addVideosDialog").showModal();
    entry.delete("add");
    history.replaceState(null, "", location.pathname + "?" + entry.toString());
  }
  if (new URLSearchParams(location.search).get("new") === "1") { openProjectModal(); startNaming(null); }
  requestAnimationFrame(tick);
  watchCuts();
  const watch = new URLSearchParams(location.search).get("watch");
  if (watch && /^https:\/\//.test(watch)) { history.replaceState(null, "", location.pathname); loadStreamer(watch); }
}
// Wait for the other scripts: init draws the page with functions they define.
document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", init) : init();

const goHome = async event => { event.preventDefault(); await flushSave(); location.assign("/"); };
$("editorHome").onclick = goHome;

$("addVideosClose").onclick = () => $("addVideosDialog").close();
$("addVideosChoose").onclick = () => { $("addVideosDialog").close(); $("srcPick").click(); };
