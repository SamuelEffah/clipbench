// Remove vocals from a song in the Music panel. Depends on app.js: $, api, toast; audio.js: audioFiles, refreshAudio; panels.js: isSong, paintMusic.
// Remove vocals: a song becomes "<song> (instrumental)" in the music list. One at a time on the server, so it's slow but gentle.
const voxBusy = new Set();
const hasInstrumental = (f, names) => names ? names.has(`${f.name} (instrumental)`) : audioFiles.some(o => o.name === `${f.name} (instrumental)`);
const canRemoveVocals = (f, names) => isSong(f) && !/\(instrumental\)$/.test(f.name) && !hasInstrumental(f, names);

async function removeVocals(f) {
  if (voxBusy.has(f.id)) return;
  voxBusy.add(f.id);
  paintMusic();
  toast("Taking the singing out. This takes a few minutes");
  try {
    let job = await api("/api/instrumental", "POST", {id: f.id});
    while (job.state === "working") {
      await new Promise(r => setTimeout(r, 3000));
      job = await api(`/api/instrumental/${job.id}`);
    }
    if (job.state !== "done") throw new Error(job.message || "Couldn't take the singing out");
    await refreshAudio();
    toast(`Added ${f.name} (instrumental)`);
  } catch (err) {
    toast(err.message);
  } finally {
    voxBusy.delete(f.id);
    paintMusic();
  }
}

// Take a song or sound out of the library. The file goes to the Trash, and any copy of it on this Short's timeline goes too.
async function deleteMusic(f) {
  try {
    await api(`/api/remove-audio/${f.id}`, "POST", {});
    if (audioOf().some(a => a.file === f.id)) {
      state.project = {...state.project, audio: audioOf().filter(a => a.file !== f.id)};
      state.audioSel = null;
      changed();
    }
    await refreshAudio();
    toast(`${f.name} moved to the Trash`);
  } catch (err) {
    toast(err.message);
  }
}

// One quiet menu button per row instead of a text button that squeezed the title.
function musicMenu(f, names) {
  const b = document.createElement("button");
  b.className = "mmore";
  b.setAttribute("aria-label", `More for ${f.name}`);
  b.title = "More";
  b.innerHTML = '<svg class="i"><use href="#dots"/></svg>';
  b.onclick = e => {
    e.stopPropagation();
    const r = b.getBoundingClientRect();
    const busy = voxBusy.has(f.id);
    openCtx(r.right, r.bottom + 4, [
      ...(canRemoveVocals(f, names) || busy ? [{label: busy ? "Taking the singing out" : "Make a copy with no vocals", off: busy, run: () => removeVocals(f)}, "-"] : []),
      {label: "Move to Trash", run: () => deleteMusic(f)},
    ]);
  };
  return b;
}
