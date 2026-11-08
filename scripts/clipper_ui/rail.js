// Short station: the project and switch float over the preview, and the tools open from the rail. Depends on app.js: $.
let railOpen = null;

let railMode = false;
function railSync(short) {
  if (short !== railMode) {
    railMode = short;
    setPreviewMuted(short);
    document.querySelector(short ? ".work" : ".side").prepend(document.querySelector(".shellhead"));
    railClose();
  }
  if (short) {
    paintShortPanels();
    repaintDropdowns();
    updatePreview();
  }
}

function railShow(name) {
  if (name) closeDropdowns();
  railOpen = name;
  const pop = $("railPop");
  pop.hidden = !name;
  pop.querySelectorAll("section[data-panel]").forEach(s => { s.hidden = s.dataset.panel !== name; });
  document.querySelectorAll("#rail .rb[data-panel]").forEach(b => {
    const on = b.dataset.panel === name;
    b.setAttribute("aria-pressed", on);
    b.setAttribute("aria-expanded", on);
  });
  if (name) paintShortPanels();
}
const railClose = () => railShow(null);

document.querySelectorAll("#rail .rb[data-panel]").forEach(b => {
  b.onclick = e => { e.stopPropagation(); railShow(railOpen === b.dataset.panel ? null : b.dataset.panel); };
});
document.querySelectorAll("#railPop [data-close]").forEach(b => { b.onclick = railClose; });
$("railShorts").onclick = e => { e.stopPropagation(); railClose(); openShortsDialog(); };
document.addEventListener("keydown", e => { if (e.key === "Escape" && railOpen && !document.querySelector("dialog[open]")) railClose(); });

// The strip under the preview: transport and time sit in the middle, as in the Clips station.
const stampShort = t => `${String(Math.floor(t / 60)).padStart(2, "0")}:${(t % 60).toFixed(2).padStart(5, "0")}`;
$("sMid").prepend($("thPrev"), $("thPlay"), $("thNext"));
$("thPrev").classList.add("ti");
$("thNext").classList.add("ti");
$("thPlay").classList.add("ti", "big");
$("thPrev").querySelector("use").setAttribute("href", "#c-prev");
$("thNext").querySelector("use").setAttribute("href", "#c-next");
$("sTime").append($("thElapsed"), Object.assign(document.createElement("i"), {textContent: "/"}), $("thTotal"));
$("sSplit").onclick = splitInShort;
$("sTrash").onclick = () => removeSelected();

// Size and layout are two dropdowns under the preview. They open upward and name what each choice does.
const FORMAT_CHOICES = [
  ["9:16", "Vertical, for Shorts", '<rect x="8" y="3" width="8" height="18" rx="2"/>'],
  ["4:5", "Portrait post", '<rect x="6" y="4" width="12" height="16" rx="2"/>'],
  ["1:1", "Square", '<rect x="5" y="5" width="14" height="14" rx="2"/>'],
  ["16:9", "Widescreen", '<rect x="3" y="7" width="18" height="10" rx="2"/>'],
];
const LAYOUT_CHOICES = [
  ["fill", "Fill", '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>'],
  ["fit", "Fit", '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>'],
  ["split", "Split", '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M5 12h14"/>'],
  ["three", "Three", '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M5 12h14M12 12v9"/>'],
  ["four", "Four", '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M5 12h14M12 3v18"/>'],
];
const drawing = d => `<svg class="i" viewBox="0 0 24 24">${d}</svg>`;

function dropdown(id, label, choices, current, pick) {
  const wrap = document.createElement("span");
  wrap.className = "anchor";
  const btn = document.createElement("button");
  btn.className = "dd";
  btn.id = id;
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-expanded", "false");
  btn.setAttribute("aria-label", label);
  btn.title = label;
  const menu = document.createElement("div");
  menu.className = "dmenu";
  menu.setAttribute("role", "listbox");
  menu.hidden = true;
  const paint = () => {
    const now = choices.find(c => c[0] === current()) || choices[0];
    btn.innerHTML = `${drawing(now[3])}<span>${now[4]}</span><svg class="i cv"><use href="#chevdown"/></svg>`;
    menu.replaceChildren(...choices.map(([value, name, note, icon]) => {
      const item = document.createElement("button");
      item.className = "mi";
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", value === current());
      item.innerHTML = `${drawing(icon)}<span>${name}${note ? `<small>${note}</small>` : ""}</span><svg class="i ck"><use href="#c-check"/></svg>`;
      item.onclick = e => { e.stopPropagation(); closeDropdowns(); pick(value); };
      return item;
    }));
  };
  btn.onclick = e => {
    e.stopPropagation();
    const open = menu.hidden;
    railClose();
    closeDropdowns();
    paint();
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open);
  };
  wrap.append(btn, menu);
  wrap.repaint = paint;
  return wrap;
}
function closeDropdowns() {
  document.querySelectorAll(".dmenu").forEach(m => { m.hidden = true; });
  document.querySelectorAll(".dd").forEach(b => b.setAttribute("aria-expanded", "false"));
}

const layoutKey = () => (state.project.template === "full" ? "fill" : templateOf());
const fmtChoices = FORMAT_CHOICES.map(([v, note, icon]) => [v, v, note, icon, v]);
const layChoices = LAYOUT_CHOICES.map(([v, name, icon]) => [v, name, "", icon, `Layout: ${name}`]);
const pctl = document.createElement("div");
pctl.className = "pctl";
const fmtDd = dropdown("fmtBtn", "Video size", fmtChoices, formatOf, f => { state.project = {...state.project, format: f}; changed(); });
const layDd = dropdown("layBtn", "Layout", layChoices, layoutKey, t => {
  state.project = {...state.project, template: t};
  if (laneOf(state.project.clips[state.sel]) && LANES.indexOf(laneOf(state.project.clips[state.sel])) >= SHAPES[t].k) state.sel = state.project.clips.findIndex(c => isTop(c));
  changed();
  if (preview.on) startPreviewAt(nextTop(-1));
});
pctl.append(fmtDd, layDd);
$("theater").append(pctl);
function repaintDropdowns() { fmtDd.repaint(); layDd.repaint(); }
document.addEventListener("click", closeDropdowns);
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDropdowns(); });
