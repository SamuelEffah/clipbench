// Voice only: a clip keeps just the voice from its sound, with the music and effects taken out. It is separated on the server
// (a few seconds a clip), and while that runs the clip's waveform on the timeline says "Processing".
const voiceWorking = new Set();
const voiceKey = c => `${c.src}|${c.in}|${c.out}`;
const hasVoiceOnly = c => Boolean(c && c.voice);

async function isolateVoice(ids) {
  const clips = state.project.clips, project = state.project.name;
  const todo = ids.map(i => clips[i]).filter(c => c && !c.voice && !voiceWorking.has(voiceKey(c)));
  if (!todo.length) return;
  for (const c of todo) voiceWorking.add(voiceKey(c));
  render();
  await Promise.all(todo.map(async c => {
    let rendered = false;
    try {
      let job = await api("/api/voice", "POST", {src: c.src, in: c.in, out: c.out});
      while (job.state === "working") {
        await new Promise(r => setTimeout(r, 1000));
        job = await api(`/api/voice/${job.id}`);
      }
      if (job.state !== "done") throw new Error(job.message || "Couldn't isolate the voice");
      const at = state.project.name === project ? state.project.clips.findIndex(x => voiceKey(x) === voiceKey(c)) : -1;
      if (at >= 0) {
        voiceWorking.delete(voiceKey(c));
        setClipField(at, {voice: true});
        rendered = true;
      }
      toast("Voice only. Music and effects are out of that clip");
    } catch (err) {
      toast(err.message);
    } finally {
      voiceWorking.delete(voiceKey(c));
      if (!rendered) render();
    }
  }));
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
