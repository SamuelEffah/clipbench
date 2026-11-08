// Render one clip of the Short on its own, to check its captions, speed and effects without waiting for the whole render.
let clipPreviewing = false;

function showClipPreview(text, pct, isError) {
  $("cpStatus").textContent = text;
  $("cpWait").classList.toggle("err", Boolean(isError));
  $("cpPct").textContent = isError ? "!" : pct === null ? "" : `${pct}%`;
  $("cpBar").hidden = pct === null;
  if (pct !== null) $("cpFill").style.width = `${pct}%`;
}

async function renderSelectedClip() {
  if (clipPreviewing) return;
  const i = state.sel, clip = state.project.clips[i];
  if (!clip) return toast("Select a clip first");
  const name = state.project.name;
  clipPreviewing = true;
  $("clipPrevBtn").disabled = true;
  $("cpVideo").pause();
  $("cpVideo").hidden = true;
  $("cpWait").hidden = false;
  $("cpTitle").textContent = `Clip ${i + 1} of ${state.project.clips.length}`;
  showClipPreview("Starting", 0);
  if (!$("clipPrevDlg").open) $("clipPrevDlg").showModal();
  try {
    let job = await api(`/api/preview/${name}`, "POST", {project: canon(), index: i});
    while (job.state === "working") {
      showClipPreview(`${job.message}, ${job.pct}%`, job.pct);
      await new Promise(r => setTimeout(r, 600));
      job = await api(`/api/preview/${name}`);
    }
    if (job.state !== "done") throw new Error(job.message || "The preview failed");
    const player = $("cpVideo");
    player.src = `/preview/${name}.mp4?v=${job.stamp}`;
    player.hidden = false;
    $("cpWait").hidden = true;
    $("cpBar").hidden = true;
    if ($("clipPrevDlg").open) player.play().catch(() => {});
  } catch (err) {
    $("cpWait").hidden = false;
    showClipPreview(err.message, null, true);
  } finally {
    clipPreviewing = false;
    $("clipPrevBtn").disabled = false;
  }
}

$("clipPrevBtn").onclick = renderSelectedClip;
$("cpX").onclick = () => $("clipPrevDlg").close();
$("clipPrevDlg").addEventListener("close", () => $("cpVideo").pause());
