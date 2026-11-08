// A faint playhead under the pointer wherever the Short timeline is bare, with the time it is at, so you can see where a
// click would land. A click there puts the playhead at that exact moment; a drag there is still the marquee (selection.js).
// Depends on short.js: stlBody, stlPps, inShort; audio.js: scrubTime, timeTrack, seekShort, paintPlayhead; app.js: preview, openPreview.
const HOVER_BARE = ".stl-track, .stl-lane, #stlBody";
const HOVER_CLICK_PX = 3;
let hoverHead = null, hoverDown = null;

const hoverBlocked = () => document.body.classList.contains("scrubbing") || document.body.classList.contains("lane-dragging")
  || stlBody.classList.contains("trimming") || stlBody.classList.contains("making-room");
const hoverBare = target => Boolean(target && target.matches && target.matches(HOVER_BARE) && stlBody.contains(target));
const hoverStamp = t => `${Math.floor(t / 60)}:${(t - Math.floor(t / 60) * 60).toFixed(1).padStart(4, "0")}`;

function hideHoverHead() {
  if (hoverHead) hoverHead.remove();
  hoverHead = null;
}

function showHoverHead(e) {
  const track = timeTrack(stlBody);
  if (!track || !inShort() || hoverBlocked() || !hoverBare(e.target)) return hideHoverHead();
  const t = scrubTime(e);
  if (!hoverHead) {
    hoverHead = document.createElement("i");
    hoverHead.className = "stl-hoverhead";
    hoverHead.innerHTML = '<span class="hh-time num"></span>';
    stlBody.append(hoverHead);
  }
  hoverHead.style.left = `${track.offsetLeft + t * stlPps}px`;
  hoverHead.style.top = `${track.offsetTop - 6}px`;
  hoverHead.firstChild.textContent = hoverStamp(t);
}

// A press and release on the same bare spot moves the playhead there. Anything further is a marquee, left to selection.js.
function hoverHeadDown(e) {
  hoverDown = e.button === 0 && inShort() && !hoverBlocked() && hoverBare(e.target) ? {x: e.clientX, y: e.clientY, t: scrubTime(e)} : null;
}

function hoverHeadUp(e) {
  const down = hoverDown;
  hoverDown = null;
  if (!down || Math.abs(e.clientX - down.x) > HOVER_CLICK_PX || Math.abs(e.clientY - down.y) > HOVER_CLICK_PX) return;
  if (!preview.on) openPreview();
  if (!preview.on) return;
  seekShort(down.t);
  paintPlayhead();
}

stlBody.addEventListener("pointermove", showHoverHead);
stlBody.addEventListener("pointerleave", hideHoverHead);
stlBody.addEventListener("pointerdown", hoverHeadDown);
stlBody.addEventListener("pointerup", hoverHeadUp);
