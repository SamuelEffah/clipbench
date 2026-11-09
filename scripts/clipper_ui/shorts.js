// The Shorts list: every rendered Short with its YouTube status. Depends on app.js: $, api, esc, toast, loadPublish, setStage, loadProject, state.
const shorts = {rows: [], timer: 0, unseen: new Set(), failed: null, stats: {pulled_at: null, message: "", needs_reconnect: false}};
// Only the Shorts made from the project that is open. When it has none, every project's, so none is out of reach.
const mineOf = rows => rows.filter(r => r.name === state.project.name);
const shownShorts = rows => { const mine = mineOf(rows); return mine.length ? mine : rows; };
const shortsHeading = rows => !rows.length ? "" : mineOf(rows).length ? `${mineOf(rows).length} rendered` : `${rows.length} from other projects`;

const sizeText = bytes => `${(bytes / 1048576).toFixed(1)} MB`;
function ago(seconds) {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 90) return "just now";
  const units = [[86400, "day"], [3600, "hour"], [60, "minute"]];
  for (const [n, label] of units) if (s >= n) { const v = Math.floor(s / n); return `${v} ${label}${v === 1 ? "" : "s"} ago`; }
  return "just now";
}

// "2h", "5d": the age in the least room that still reads.
function agoShort(seconds) {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  for (const [n, unit] of [[86400, "d"], [3600, "h"], [60, "m"]]) if (s >= n) return `${Math.floor(s / n)}${unit}`;
  return "now";
}

// "1.2K views": the count in the least room that still reads.
function viewsText(views) {
  const n = views >= 1e6 ? `${(views / 1e6).toFixed(1).replace(/\.0$/, "")}M` : views >= 1e4 ? `${Math.round(views / 1e3)}K` :
    views >= 1e3 ? `${(views / 1e3).toFixed(1).replace(/\.0$/, "")}K` : String(views);
  return `${n} view${views === 1 ? "" : "s"}`;
}

// "63% watched": how much of the Short viewers saw on average. Loops push it past 100, which reads as 100.
function watchedText(percent) {
  return percent === null || percent === undefined ? "" : `${Math.min(100, Math.round(percent))}% watched`;
}

function statusOf(up, stats) {
  if (up.state === "done" && stats && stats.gone) return {text: "Removed from YouTube", tone: "dim"};
  if (up.state === "done") return {text: `Uploaded as ${up.privacy || "private"}`, tone: "ok"};
  if (up.state === "uploading") return {text: `Uploading, ${up.pct || 0}%`, tone: "live"};
  if (up.state === "error") return {text: "Upload failed", tone: "warn", tip: up.message};
  return {text: "Not uploaded", tone: "dim"};
}

function shortCard(s) {
  // A video YouTube no longer lists was removed there, so the Short counts as not uploaded, whatever the record says.
  const gone = s.upload.state === "done" && Boolean(s.stats && s.stats.gone);
  const st = statusOf(s.upload, s.stats), up = gone ? {state: "none"} : s.upload;
  const key = JSON.stringify([s.name, s.folder, s.title, s.size, s.rendered_at, s.duration, s.has_project,
    state.project.name, up.state, up.message, up.studio_url, up.finished_at, s.stats && s.stats.views, s.stats && s.stats.avg_percent, gone]);
  const cache = shortCard.cache ||= new Map(), id = s.folder || s.name, previous = cache.get(id);
  // The count leads when there is one, since the line is cut short in a narrow panel and the count is what changes.
  const counted = s.stats && !gone;
  const line = [counted ? viewsText(s.stats.views) : null, counted ? watchedText(s.stats.avg_percent) : null, counted ? st.text.toLowerCase() : st.text, s.duration ? `${s.duration.toFixed(0)}s` : null, agoShort(s.rendered_at)].filter(Boolean).join(", ");
  if (previous && previous.key === key) {
    const card = previous.node;
    card._short = s;
    card.title = `${s.name}, ${sizeText(s.size)}, rendered ${ago(s.rendered_at)}`;
    card.querySelector(".smt").textContent = line;
    return card;
  }
  const card = document.createElement("article");
  card._short = s;
  card.className = "shortcard";
  card.title = `${s.name}, ${sizeText(s.size)}, rendered ${ago(s.rendered_at)}`;
  card.innerHTML = `<img class="sthumb" alt="" loading="lazy" src="/short-thumb/${encodeURIComponent(s.name)}.jpg?v=${Math.floor(s.rendered_at)}">` +
    `<div class="sbody"><p class="stitle${s.title ? "" : " none"}">${esc(s.title || s.name)}</p>` +
    `<p class="smeta num"><span class="sdot ${st.tone}"${st.tip ? ` title="${esc(st.tip)}"` : ""}></span><span class="smt">${esc(line)}</span></p>` +
    `<div class="slinks"></div></div>`;
  const main = document.createElement("button");
  main.className = `sgo${up.state === "done" || up.state === "uploading" ? "" : " export"}`;
  main.textContent = up.state === "done" ? "Details" : up.state === "uploading" ? "Progress" : up.state === "error" ? "Retry" : "Publish";
  main.onclick = () => openShort(card._short);
  card.append(main);
  const links = card.querySelector(".slinks");
  if (s.has_project && s.name !== state.project.name) {
    const edit = document.createElement("button");
    edit.className = "slink";
    edit.textContent = "Edit project";
    edit.onclick = async () => { $("pname").value = s.name; await loadProject(s.name); setTab("clip"); };
    links.append(edit);
  }
  if (up.state === "done" && up.studio_url) {
    links.append(Object.assign(document.createElement("a"), {className: "slink", href: up.studio_url, target: "_blank", rel: "noopener", textContent: "Open in Studio"}));
  }
  links.hidden = !links.children.length;
  cache.set(id, {key, node: card});
  return card;
}

// Why there are no fresh counts, when there is a reason: the sign-in predates the read permission, or the last pull failed.
function paintStatsNote() {
  const note = $("shortsNote"), {needs_reconnect, message} = shorts.stats;
  note.hidden = !needs_reconnect && !message;
  if (note.hidden) return;
  note.replaceChildren(needs_reconnect ? Object.assign(document.createElement("button"), {className: "slink", textContent: "Connect YouTube again to see views", onclick: ytConnect}) : message);
}

function paintShorts() {
  const list = $("shortsList");
  const rows = shownShorts(shorts.rows);
  $("shortsCount").textContent = shortsHeading(shorts.rows);
  paintStatsNote();
  if (!rows.length) {
    list.innerHTML = '<div class="shortsempty"><b>No Shorts yet</b><span>Push this project to render and it shows up here, ready to publish.</span></div>';
    return;
  }
  const cards = rows.map(shortCard);
  shortCard.cache = new Map(rows.map(r => [r.folder || r.name, shortCard.cache.get(r.folder || r.name)]));
  if (list.children.length !== cards.length || cards.some((card, i) => list.children[i] !== card)) list.replaceChildren(...cards);
}

async function refreshShorts(progressOnly = false) {
  clearTimeout(shorts.timer);
  if (document.hidden) { shorts.needsRefresh = true; return; }
  shorts.needsRefresh = false;
  try {
    const before = shorts.rows, pending = before.filter(r => r.upload.state === "uploading");
    let refreshed = false;
    if (progressOnly && pending.length && shorts.scannedAt !== undefined && Date.now() - shorts.scannedAt < 10000) {
      const query = new URLSearchParams(pending.map(r => ["name", r.name]));
      const uploads = await api(`/api/uploads/progress?${query}`);
      if (shorts.rows !== before) return;
      if (pending.every(r => uploads[r.name]?.state === "uploading")) {
        shorts.rows = before.map(r => uploads[r.name] ? {...r, upload: uploads[r.name]} : r);
        refreshed = true;
      }
    }
    // Validate file versions on completion and periodically discover external renders.
    if (!refreshed) {
      [shorts.rows, shorts.stats] = await Promise.all([api("/api/shorts"), api("/api/video-stats").catch(() => shorts.stats)]);
      shorts.scannedAt = Date.now();
    }
  } catch (err) {
    if (document.hidden) { shorts.needsRefresh = true; return; }
    $("shortsList").textContent = `Couldn't load Shorts: ${err.message}`;
    return;
  }
  if (document.hidden) { shorts.needsRefresh = true; return; }
  paintShorts();
  paintShortsBadge();
  clearTimeout(shorts.timer);
  if (currentTab === "shorts" && !$("shortsDlg").open && shorts.rows.some(r => r.upload.state === "uploading")) shorts.timer = setTimeout(() => refreshShorts(true), 1500);
}

async function openShort(s) {
  $("rdVideo").pause();
  $("rdTitle").textContent = `${s.name} is ready`;
  $("rdPath").textContent = `MP4 · ${sizeText(s.size)}`;
  $("rdPath").title = `shorts/${s.folder}/video.mp4`;
  const player = $("rdVideo");
  player.src = `/short/${s.name}.mp4?v=${Math.floor(s.rendered_at)}`;
  player.hidden = false;
  $("rdWait").hidden = true;
  $("rdBar").hidden = true;
  $("rdAgain").hidden = s.name !== state.project.name;
  setStage("check");
  $("renderDlg").showModal();
  try {
    await loadPublish(s.name);
  } catch (err) {
    toast(`Couldn't open this Short: ${err.message}`);
  }
}


// The Shorts dialog from the Clips station: one row per Short with where it is and what to do next.
const AUTH_PROBLEM = /sign.?in|token|auth|expired|connect|credential/i;

// Put the project back as it was when this Short was rendered, so what you change next starts from what you saw.
async function restoreRendered(name) {
  let snap = null;
  try { snap = await api(`/api/rendered-project/${name}`); } catch { /* a Short rendered before snapshots keeps the project as it is */ }
  if (!snap) return toast("Opened the project as it is now. This Short was rendered before its timeline was kept");
  await flushSave();
  await api(`/api/project/${name}`, "PUT", {...snap, name});
  await loadProject(name);
  toast("Back to the timeline this Short was rendered from");
}

function dialogRow(s) {
  const gone = s.upload.state === "done" && Boolean(s.stats && s.stats.gone), up = gone ? {state: "none"} : s.upload;
  const failed = up.state === "error", uploading = up.state === "uploading", onYouTube = up.state === "done";
  const dot = failed ? "e" : uploading ? "r" : "";
  const seen = onYouTube && s.stats ? [viewsText(s.stats.views), watchedText(s.stats.avg_percent)].filter(Boolean) : [];
  const text = gone ? "Removed from YouTube" : failed ? `Upload failed. ${up.message || "Try again"}` : uploading ? `Uploading, ${up.pct || 0}%` : onYouTube && up.finished_at ? [...seen, ago(up.finished_at)].join(", ") : seen.join("");
  const key = JSON.stringify([s.name, s.folder, s.title, s.rendered_at, s.has_project,
    up.state, up.message, up.studio_url, up.finished_at, s.stats && s.stats.views, s.stats && s.stats.avg_percent, gone]);
  const cache = dialogRow.cache ||= new Map(), id = s.folder || s.name, previous = cache.get(id);
  if (previous && previous.key === key) {
    const row = previous.node;
    row._short = s;
    if (text) row.querySelector(".st").lastChild.nodeValue = text;
    if (uploading) {
      const progress = row.querySelector(".prog");
      progress.setAttribute("aria-valuenow", up.pct || 0);
      progress.querySelector("i").style.width = `${up.pct || 0}%`;
    }
    return row;
  }
  const row = document.createElement("div");
  row._short = s;
  row.className = "shrow";
  row.innerHTML = `<img class="sthumb" alt="" loading="lazy" src="/short-thumb/${encodeURIComponent(s.name)}.jpg?v=${Math.floor(s.rendered_at)}">` +
    `<div class="sdbody"><b>${esc(s.title || s.name)}</b>${text ? `<div class="st${failed ? " err" : ""}">${dot ? `<span class="dot ${dot}"></span>` : ""}${esc(text)}</div>` : ""}` +
    (uploading ? `<div class="prog" role="progressbar" aria-valuenow="${up.pct || 0}" aria-valuemin="0" aria-valuemax="100"><i style="width:${up.pct || 0}%"></i></div>` : "") + "</div><div class=\"acts\"></div>";
  const acts = row.querySelector(".acts");
  const add = (label, run, primary) => {
    const b = Object.assign(document.createElement("button"), {textContent: label, className: primary ? "export" : ""});
    b.onclick = run;
    acts.append(b);
  };
  if (failed) add(AUTH_PROBLEM.test(up.message || "") ? "Reconnect and retry" : "Retry", () => openShort(row._short), true);
  else if (uploading) add("Progress", () => openShort(row._short));
  else if (onYouTube) {
    add("Open", () => openShort(row._short));
    if (up.studio_url) acts.append(Object.assign(document.createElement("a"), {className: "btn", href: up.studio_url, target: "_blank", rel: "noopener", textContent: "Open in Studio"}));
  } else add("Upload", () => openShort(row._short), true);
  const thumb = row.querySelector(".sthumb");
  thumb.title = "Open this Short";
  thumb.onclick = () => openShort(row._short);
  if (s.has_project) {
    const reopen = Object.assign(document.createElement("button"), {textContent: "Reopen", title: "Open this Short's timeline to change it and render again"});
    reopen.onclick = async () => {
      $("shortsDlg").close();
      await restoreRendered(s.name);
      setMode("short");
    };
    acts.prepend(reopen);
  }
  cache.set(id, {key, node: row});
  return row;
}

// A render that failed, until the list is closed.
function failedRow() {
  const row = document.createElement("div");
  row.className = "shrow";
  row.innerHTML = `<div class="sdbody"><b>${esc(shorts.failed.name)}</b><div class="st err"><span class="dot e"></span>Render failed. ${esc(shorts.failed.message)}</div></div>`;
  return row;
}

// The Short being rendered now, at the top of the list with how far it has got.
function renderingRow() {
  const row = document.createElement("div");
  row.className = "shrow";
  row.innerHTML = `<div class="sdbody"><b>${esc(renderJob.name)}</b><div class="st"><span class="dot r"></span>Rendering, ${renderJob.pct}%</div>` +
    `<div class="prog" role="progressbar" aria-valuenow="${renderJob.pct}" aria-valuemin="0" aria-valuemax="100"><i style="width:${renderJob.pct}%"></i></div></div>`;
  return row;
}

// The badge on the Shorts buttons: a fixed dot while one is rendering, then how many need a look: finished renders not yet
// opened, uploads going or failed, and a render that failed.
function paintShortsBadge() {
  const here = state.project.name, rendering = Boolean(renderJob && renderJob.name === here);
  const busy = !rendering && (shorts.unseen.has(here) || shorts.failed?.name === here ||
    shorts.rows.some(r => r.name === here && (r.upload.state === "uploading" || r.upload.state === "error")));
  const badge = $("railBadge");
  setPlaybackValue(badge, "textContent", rendering ? "" : busy ? "1" : "0");
  setPlaybackValue(badge, "hidden", !rendering && !busy);
  badge.classList.toggle("pulse", rendering);
}

async function openShortsDialog(progressOnly = false) {
  clearTimeout(shorts.dialogTimer);
  if (document.hidden) { shorts.needsRefresh = true; return; }
  shorts.unseen.clear();
  if (!$("shortsDlg").open) $("shortsDlg").showModal();
  if (!progressOnly) $("shList").replaceChildren(Object.assign(document.createElement("p"), {className: "sdempty", textContent: "Loading your Shorts"}));
  await refreshShorts(progressOnly);
  if (document.hidden || !$("shortsDlg").open) return;
  const list = $("shList"), rows = shownShorts(shorts.rows), here = state.project.name;
  $("shCount").textContent = mineOf(shorts.rows).length || !rows.length ? `${rows.length} Short${rows.length === 1 ? "" : "s"}` : `${rows.length} from other projects`;
  const failed = shorts.failed && shorts.failed.name === here ? [failedRow()] : [];
  const going = [...failed, ...(renderJob && renderJob.name === here ? [renderingRow()] : [])];
  const cards = rows.map(dialogRow);
  dialogRow.cache = new Map(rows.map(r => [r.folder || r.name, dialogRow.cache.get(r.folder || r.name)]));
  const nodes = [...going, ...cards];
  if (!nodes.length) nodes.push(Object.assign(document.createElement("p"), {className: "sdempty", textContent: "No Shorts yet for this project. Push it to render and it shows up here."}));
  if (list.children.length !== nodes.length || nodes.some((node, i) => list.children[i] !== node)) list.replaceChildren(...nodes);
  if ($("shortsDlg").open && (renderJob || rows.some(r => r.upload.state === "uploading"))) {
    clearTimeout(shorts.dialogTimer);
    shorts.dialogTimer = setTimeout(() => { if ($("shortsDlg").open) openShortsDialog(true); }, 2000);
  }
}
$("shClose").onclick = () => $("shortsDlg").close();
$("shortsDlg").addEventListener("close", () => {
  clearTimeout(shorts.dialogTimer);
  shorts.failed = null;
  paintShortsBadge();
  // While open, the dialog owns status polling for both views.
  if (!document.hidden && currentTab === "shorts" && shorts.rows.some(r => r.upload.state === "uploading")) return refreshShorts(true);
});
$("shortsDlg").addEventListener("click", e => { if (e.target === e.currentTarget) e.currentTarget.close(); });
// Background uploads keep running; their list and dialog need no hidden polling.
function shortsVisibility() {
  clearTimeout(shorts.timer);
  clearTimeout(shorts.dialogTimer);
  if (document.hidden) {
    if (shorts.rows.some(r => r.upload.state === "uploading")) shorts.needsRefresh = true;
    return;
  }
  if ($("shortsDlg").open) return openShortsDialog(true);
  if (currentTab === "shorts" || shorts.needsRefresh) return refreshShorts();
}
document.addEventListener("visibilitychange", shortsVisibility);
refreshShorts();
