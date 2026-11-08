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

function voxButton(f, names) {
  if (!canRemoveVocals(f, names)) return null;
  const busy = voxBusy.has(f.id);
  const b = document.createElement("button");
  b.className = "voxbtn";
  b.textContent = busy ? "Working" : "No vocals";
  b.title = "Make a copy of this song without the singing";
  b.disabled = busy;
  b.onclick = () => removeVocals(f);
  return b;
}
