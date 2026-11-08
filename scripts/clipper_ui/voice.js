// Voice only: a clip keeps just the voice from its sound, with the music and effects taken out. It is separated on the server,
// which takes about as long as the clip is, and while that runs the clip's waveform on the timeline says so. The preview then
// hears the isolated voice in place of the clip's sound (audio.js: syncVoices). A clip whose range changes is isolated again
// on its own, because the voice is saved per range. Depends on app.js: state, api, toast, render, setClipField, changed.
const voiceWorking = new Set(), voiceFiles = new Map(), voiceFailed = new Set();
const voiceKey = c => `${c.src}|${c.in}|${c.out}`;
const hasVoiceOnly = c => Boolean(c && c.voice);
// Where the preview plays this clip's voice from, once it is isolated.
const voiceUrl = c => (hasVoiceOnly(c) && voiceFiles.get(voiceKey(c))) || null;
const voiceEstimate = c => `about ${Math.max(1, Math.round(c.out - c.in))}s`;

async function isolateVoice(ids, quiet = false) {
  const clips = state.project.clips, project = state.project.name;
  if (!quiet) for (const i of ids) if (clips[i]) voiceFailed.delete(voiceKey(clips[i]));
  const todo = ids.map(i => clips[i]).filter(c => c && !voiceFiles.has(voiceKey(c)) && !voiceWorking.has(voiceKey(c)) && !voiceFailed.has(voiceKey(c)));
  if (!todo.length) return;
  for (const c of todo) voiceWorking.add(voiceKey(c));
  if (!quiet) toast(`Isolating the voice, ${voiceEstimate(todo[0])}${todo.length > 1 ? " for the first clip" : ""}`);
  render();
  await Promise.all(todo.map(async c => {
    const key = voiceKey(c);
    let rendered = false;
    try {
      let job = await api("/api/voice", "POST", {src: c.src, in: c.in, out: c.out});
      while (job.state === "working") {
        await new Promise(r => setTimeout(r, 1000));
        job = await api(`/api/voice/${job.id}`);
      }
      if (job.state !== "done") throw new Error(job.message || "Couldn't isolate the voice");
      if (job.file) voiceFiles.set(key, job.file);
      const at = state.project.name === project ? state.project.clips.findIndex(x => voiceKey(x) === key) : -1;
      voiceWorking.delete(key);
      if (at >= 0 && !state.project.clips[at].voice) {
        setClipField(at, {voice: true});
        rendered = true;
      }
      if (!quiet) toast("Voice only. Music and effects are out of that clip");
    } catch (err) {
      voiceFailed.add(key);
      toast(err.message);
    } finally {
      voiceWorking.delete(key);
      if (!rendered) render();
    }
  }));
}

// A voice-only clip whose range changed, or that was saved before this page opened, gets its voice isolated again. Nothing
// happens for a clip that already failed; choosing Isolate voice again retries it.
function ensureVoices() {
  const clips = state.project.clips;
  const todo = clips.map((c, i) => i).filter(i => {
    const key = voiceKey(clips[i]);
    return hasVoiceOnly(clips[i]) && !voiceFiles.has(key) && !voiceWorking.has(key) && !voiceFailed.has(key);
  });
  if (todo.length) setTimeout(() => isolateVoice(todo, true), 0);
}

function useOriginalSound(ids) {
  const selected = new Set(ids);
  state.project = {...state.project, clips: state.project.clips.map((c, n) => (selected.has(n) && c.voice ? {...c, voice: false} : c))};
  changed();
  toast("Back to the original sound");
}

// What the context menu offers for the chosen clips: isolate the voice, or go back to the original sound when all have it.
function voiceMenuItem(ids) {
  const clips = ids.map(i => state.project.clips[i]).filter(Boolean);
  const isolated = clips.length && clips.every(hasVoiceOnly);
  return isolated ? {label: "Use the original sound", run: () => useOriginalSound(ids)} : {label: "Isolate voice", run: () => isolateVoice(ids)};
}
