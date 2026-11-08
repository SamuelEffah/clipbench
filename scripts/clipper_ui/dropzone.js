// Drop video files on the left panel to add them to Media, or to Saved when that tab is open.
const dropZone = {depth: 0, busy: false};
const hasFiles = e => Array.from(e.dataTransfer ? e.dataTransfer.types : []).includes("Files");
const isVideoFile = f => /\.(mp4|mov|m4v|mkv|webm|avi)$/i.test(f.name);

function uploadVideo(file, onProgress, broll = false) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/upload-video?name=${encodeURIComponent(file.name)}&project=${encodeURIComponent(state.project.name)}${broll ? "&broll=1" : ""}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = e => e.lengthComputable && onProgress(Math.round(e.loaded / e.total * 100));
    xhr.onerror = () => reject(new Error("The upload failed"));
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (err) { /* keep the empty object */ }
      xhr.status === 200 ? resolve(data) : reject(new Error(data.error || xhr.statusText));
    };
    xhr.send(file);
  });
}

function showUpload(text, pct) {
  const box = $("upStatus");
  box.hidden = text === null;
  if (text === null) return;
  $("upText").textContent = text;
  $("upFill").style.width = `${pct}%`;
}

function savedMoment(video, label) {
  return {src: video.path, in: 0, out: video.duration, note: "", caption: "", speed: 1, volume: 1, fit: "fit", pan: 0.5,
          effect: "none", ramp: "none", freeze: 0, thumb: `/video-thumb/${video.id}.jpg`, label};
}

// One way in for both kinds: songs and sound effects go to the audio library, videos to Sources.
async function dropFiles(files) {
  const sounds = files.filter(isAudioFile);
  if (sounds.length) await addAudioFiles(sounds);
  if (sounds.length < files.length) await dropVideos(files.filter(f => !isAudioFile(f)));
}

async function dropVideos(files) {
  const videos = files.filter(isVideoFile);
  const skipped = files.length - videos.length;
  if (!videos.length) return toast("Add video (mp4, mov, m4v, mkv, webm, avi) or audio (mp3, wav, m4a, aac, ogg, flac) files");
  if (dropZone.busy) return toast("Wait for the current upload to finish");
  dropZone.busy = true;
  const toSaved = !$("favPanel").hidden;
  const added = [];
  try {
    for (const [i, file] of videos.entries()) {
      const tag = videos.length > 1 ? ` (${i + 1} of ${videos.length})` : "";
      showUpload(`Uploading ${file.name}${tag}`, 0);
      const out = await uploadVideo(file, pct => showUpload(`Uploading ${file.name}${tag}, ${pct}%`, pct));
      added.push({path: out.path, label: file.name.replace(/\.[^.]+$/, "").slice(0, 60)});
    }
    await refreshLibrary();
    const readable = added.map(a => ({video: state.library.find(v => v.path === a.path), label: a.label})).filter(a => a.video);
    if (toSaved && readable.length) await saveFavorites([...state.favorites, ...readable.map(a => savedMoment(a.video, a.label))]);
    const bad = added.length - readable.length;
    const note = [skipped ? `${skipped} not a video` : "", bad ? `${bad} couldn't be read` : ""].filter(Boolean).join(", ");
    toast(readable.length ? `${readable.length} video${readable.length === 1 ? "" : "s"} added to ${toSaved ? "Saved" : "Media"}${note ? `, ${note}` : ""}` : `Nothing added: ${note}`);
  } catch (err) {
    if (added.length) await refreshLibrary();
    toast(err.message);
  } finally {
    dropZone.busy = false;
    showUpload(null);
  }
}

const sideEl = document.querySelector(".side");
sideEl.addEventListener("dragenter", e => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dropZone.depth += 1;
  sideEl.classList.add("dropping");
  $("dropWhere").textContent = "Drop videos or audio to add them as sources";
});
sideEl.addEventListener("dragover", e => { if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
sideEl.addEventListener("dragleave", e => {
  if (!hasFiles(e)) return;
  dropZone.depth = Math.max(0, dropZone.depth - 1);
  if (!dropZone.depth) sideEl.classList.remove("dropping");
});
sideEl.addEventListener("drop", e => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dropZone.depth = 0;
  sideEl.classList.remove("dropping");
  dropFiles(Array.from(e.dataTransfer.files));
});
// A file dropped outside the panel would make the browser navigate away from the editor.
for (const type of ["dragover", "drop"]) window.addEventListener(type, e => { if (hasFiles(e)) e.preventDefault(); });
