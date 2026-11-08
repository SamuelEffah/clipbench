// J, K and L playback on the Short: L plays forward and each press goes faster, J plays backward the same way, K stops.
// Faster and backward play move the playhead by seeking, so they are silent, like scrubbing.
// Depends on app.js, audio.js, snap.js: video, preview, seekShort, shortEnd, startPreviewAt, nextTop, toast.
const SHUTTLE_RATES = [1, 2, 4, 8];
const SHUTTLE_SEEK_MS = 90;
let shuttle = null;

const shuttleActive = () => shuttle !== null;

function stopShuttle() {
  if (!shuttle) return;
  cancelAnimationFrame(shuttle.raf);
  shuttle = null;
}

// How things stand: {dir, level} while shuttling or playing forward at normal speed, else null.
function shuttleLevel() {
  if (shuttle) return {dir: shuttle.dir, level: shuttle.level};
  return !video.paused && !preview.done ? {dir: 1, level: 0} : null;
}

function runShuttle(dir, level) {
  preview.hold = true;
  video.pause();
  const rate = SHUTTLE_RATES[level];
  shuttle = {dir, level, rate, pos: Math.min(preview.done ? shortEnd() : preview.elapsed || 0, shortEnd()), last: performance.now(), seekAt: 0, raf: 0};
  toast(`${dir < 0 ? "Back" : "Forward"} ${rate}x`);
  const step = now => {
    if (!shuttle) return;
    const s = shuttle, end = shortEnd();
    s.pos = Math.min(end, Math.max(0, s.pos + s.dir * s.rate * (now - s.last) / 1000));
    s.last = now;
    const atEdge = s.pos <= 0 || s.pos >= end;
    if (atEdge || (now - s.seekAt >= SHUTTLE_SEEK_MS && !video.seeking)) {
      seekShort(s.pos);
      s.seekAt = now;
    }
    if (atEdge) return stopShuttle();
    s.raf = requestAnimationFrame(step);
  };
  shuttle.raf = requestAnimationFrame(step);
}

// J (dir -1) or L (dir 1): start in that direction, or go one step faster when already going that way.
function shuttleKey(dir) {
  const now = shuttleLevel();
  const level = now && now.dir === dir ? Math.min(now.level + 1, SHUTTLE_RATES.length - 1) : 0;
  stopShuttle();
  if (dir > 0 && level === 0) {
    if (preview.done) startPreviewAt(nextTop(-1));
    else {
      preview.hold = false;
      video.play().catch(() => {});
    }
    return toast("Play");
  }
  runShuttle(dir, level);
}

// K: stop wherever it is.
function shuttleStop() {
  stopShuttle();
  preview.hold = true;
  video.pause();
}

// Anything else you do takes over from a running shuttle: a click, or a key that is not J or L.
document.addEventListener("pointerdown", stopShuttle, true);
document.addEventListener("keydown", e => {
  if (shuttle && e.key !== "j" && e.key !== "l") stopShuttle();
}, true);
