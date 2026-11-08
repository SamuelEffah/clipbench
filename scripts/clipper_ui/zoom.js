// Zooming and scrolling the Short timeline. Depends on short.js: stlBody, tlZoom, stlPps, stlBasePps, renderShortTl, clipStarts, chosen.
const ZOOM_MAX = 12;
const ZOOM_STEP = 1.5;
let panAt = 0;

const zoomValue = () => Math.round(Math.log(tlZoom) / Math.log(ZOOM_MAX) * 100);

function syncZoomUi() {
  const range = $("tlZoomRange"), value = zoomValue();
  range.value = value;
  range.style.setProperty("--fill", `${value}%`);
  $("tlZoomOut").disabled = tlZoom <= 1.001;
  $("tlZoomIn").disabled = tlZoom >= ZOOM_MAX - 0.001;
}

// Zoom around a point: the moment under the pointer stays under it.
function setZoom(next, clientX) {
  next = Math.min(ZOOM_MAX, Math.max(1, next));
  if (Math.abs(next - tlZoom) < 0.001) return;
  const box = stlBody.getBoundingClientRect(), x = clientX ?? box.left + box.width / 2;
  const track = timeTrack(stlBody);
  const t = track ? (x - track.getBoundingClientRect().left) / stlPps : 0;
  tlZoom = next;
  renderShortTl();
  const now = timeTrack(stlBody);
  if (now) stlBody.scrollLeft = now.offsetLeft + t * stlPps - (x - box.left);
  syncZoomUi();
}

function fitAll() {
  tlZoom = 1;
  renderShortTl();
  stlBody.scrollLeft = 0;
  syncZoomUi();
}

// Zoom so the chosen clips fill the width.
function fitSelection() {
  const clips = state.project.clips, ids = chosen();
  if (!ids.length) return fitAll();
  const starts = clipStarts(clips);
  const from = Math.min(...ids.map(i => starts[i])), to = Math.max(...ids.map(i => starts[i] + outLen(clips[i])));
  const want = (stlBody.clientWidth - 28) / (Math.max(0.5, to - from) * 1.1 * stlBasePps);
  tlZoom = Math.min(ZOOM_MAX, Math.max(1, want));
  renderShortTl();
  const track = timeTrack(stlBody);
  stlBody.scrollLeft = track ? track.offsetLeft + from * stlPps - stlBody.clientWidth * 0.05 : 0;
  syncZoomUi();
}

// While the Short plays, keep the playhead in view.
function followPlayhead(x) {
  if (tlZoom <= 1 || scrub || video.paused || Date.now() - panAt < 1500) return;
  const left = stlBody.scrollLeft, width = stlBody.clientWidth;
  if (x < left + 30 || x > left + width - 60) stlBody.scrollLeft = Math.max(0, x - width * 0.25);
}

stlBody.addEventListener("wheel", e => {
  if (!inShort()) return;
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault();
    setZoom(tlZoom * Math.exp(-e.deltaY * 0.01), e.clientX);
  } else if (tlZoom > 1 && !e.shiftKey && Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
    e.preventDefault();
    panAt = Date.now();
    stlBody.scrollLeft += e.deltaY;
  } else panAt = Date.now();
}, {passive: false});
stlBody.addEventListener("pointerdown", () => { panAt = Date.now(); });

$("tlZoomRange").oninput = e => setZoom(Math.pow(ZOOM_MAX, Number(e.target.value) / 100));
$("tlZoomOut").onclick = () => setZoom(tlZoom / ZOOM_STEP);
$("tlZoomIn").onclick = () => setZoom(tlZoom * ZOOM_STEP);
syncZoomUi();
