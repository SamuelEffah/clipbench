// Drag the top edge of the Short timeline to resize the timeline and controls; the lanes scroll when cut short.
// It can shrink to a compact strip, and grow to the larger of its natural height and the split layout height.
const TL_CAP_VH = 0.7, TL_FLOOR = 150;
const tlGrip = Object.assign(document.createElement("div"), {id: "tlGrip", title: "Drag to resize the timeline (double-click to reset)"});
tlGrip.setAttribute("role", "separator");
tlGrip.setAttribute("aria-orientation", "horizontal");
$("shortTl").prepend(tlGrip);

const tlStyle = document.body.style;
let splitSeen = 0, tlMaxLast = 0;

// The height the panel takes with no extra room.
function tlMinH() {
  const kept = tlStyle.getPropertyValue("--tlh");
  tlStyle.removeProperty("--tlh");
  const h = $("shortTl").offsetHeight;
  if (kept) tlStyle.setProperty("--tlh", kept);
  if (templateOf() === "split") splitSeen = h;
  return h;
}

// That height with the split layout chosen (as last seen, else estimated): each lane group the current layout lacks adds its share.
function tlMaxH(min) {
  const max = tlMaxRaw(min);
  tlMaxLast = max;
  return max;
}

function tlMaxRaw(min) {
  if (splitSeen) return Math.round(Math.min(innerHeight * TL_CAP_VH, Math.max(min, splitSeen)));
  const body = $("stlBody"), ruler = body.querySelector(".stl-rulerrow")?.offsetHeight || 0;
  const perLane = Math.max(0, body.scrollHeight - ruler) / laneCount();
  const extra = Math.max(0, SHAPES.split.k - laneCount()) * perLane;
  return Math.round(Math.min(innerHeight * TL_CAP_VH, min + extra));
}

function setTlHeight(px, max = tlMaxH(tlMinH())) {
  const h = Math.min(max, Math.max(TL_FLOOR, Math.round(px)));
  tlStyle.setProperty("--tlh", `${h}px`);
  return h;
}

let tlDrag = null;
tlGrip.addEventListener("pointerdown", e => {
  if (e.button !== 0) return;
  e.preventDefault();
  const min = tlMinH();
  tlDrag = {y: e.clientY, h: $("shortTl").offsetHeight, max: tlMaxH(min)};
  tlGrip.setPointerCapture(e.pointerId);
  tlGrip.classList.add("active");
});
tlGrip.addEventListener("pointermove", e => {
  if (tlDrag) setTlHeight(tlDrag.h + tlDrag.y - e.clientY, tlDrag.max);
});
const endTlDrag = () => { tlDrag = null; tlGrip.classList.remove("active"); };
tlGrip.addEventListener("pointerup", endTlDrag);
tlGrip.addEventListener("pointercancel", endTlDrag);
tlGrip.addEventListener("dblclick", () => tlStyle.removeProperty("--tlh"));
new ResizeObserver(() => {
  if (templateOf() === "split" && !tlStyle.getPropertyValue("--tlh") && $("shortTl").offsetHeight) splitSeen = $("shortTl").offsetHeight;
}).observe($("shortTl"));
