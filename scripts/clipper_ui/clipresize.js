// Drag the top edge of the controls and timeline in the Clips station to give them more room.
const CB_MAX_FALLBACK = 320;
// Same limits as the Short timeline (TL_FLOOR, TL_CAP_VH from tlresize.js); the strip grows or shrinks to fill. Double-click the edge to reset.
const cbGrip = Object.assign(document.createElement("div"), {id: "cbGrip", title: "Drag to resize the timeline (double-click to reset)"});
cbGrip.setAttribute("role", "separator");
cbGrip.setAttribute("aria-orientation", "horizontal");
document.querySelector(".bottom").prepend(cbGrip);

const cbHost = document.querySelector(".bottom"), cbStyle = document.body.style;

// The height the panel takes with no extra room.
function cbMinH() {
  const kept = cbStyle.getPropertyValue("--cbh");
  cbStyle.removeProperty("--cbh");
  const h = cbHost.offsetHeight;
  if (kept) cbStyle.setProperty("--cbh", kept);
  return h;
}

function setCbHeight(px, min, max) {
  const h = Math.min(max, Math.max(min, Math.round(px)));
  cbStyle.setProperty("--cbh", `${h}px`);
  return h;
}

let cbDrag = null;
cbGrip.addEventListener("pointerdown", e => {
  if (e.button !== 0) return;
  e.preventDefault();
  const natural = cbMinH();
  cbDrag = {y: e.clientY, h: cbHost.offsetHeight, min: TL_FLOOR, max: Math.max(natural, Math.min(Math.round(innerHeight * TL_CAP_VH), tlMaxLast || CB_MAX_FALLBACK))};
  cbGrip.setPointerCapture(e.pointerId);
  cbGrip.classList.add("active");
});
cbGrip.addEventListener("pointermove", e => {
  if (cbDrag) setCbHeight(cbDrag.h + cbDrag.y - e.clientY, cbDrag.min, cbDrag.max);
});
const endCbDrag = () => { cbDrag = null; cbGrip.classList.remove("active"); };
cbGrip.addEventListener("pointerup", endCbDrag);
cbGrip.addEventListener("pointercancel", endCbDrag);
cbGrip.addEventListener("dblclick", () => cbStyle.removeProperty("--cbh"));
