// The preview's transitions: blends the last frame of the clip that just ended with the clip now playing, the way the
// render's xfade does. Depends on app.js (mirror, mctx, inShort, prevTop, preview) and short.js (transitionOf, tlenOf).
// started stays 0 until the incoming clip has a picture on screen, so a clip that is slow to load still gets its blend.
const blendRun = {name: "", from: null, queued: 0, started: 0, dur: 0};
const BLEND_PATIENCE = 3000;
const scratch = document.createElement("canvas");
const scratch2 = document.createElement("canvas");
const tinyCanvas = document.createElement("canvas");

function sizeTo(c, W, H) {
  if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
  return c.getContext("2d");
}

// Remember the picture on screen now, which is the last frame of the clip that is ending.
function playTransition(clip, atStart = true) {
  const name = transitionOf(clip), first = prevTop(preview.idx) < 0;
  if (name === "none" || !inShort() || (first && !atStart) || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const g = sizeTo(scratch2, mirror.width, mirror.height);
  if (first) { g.fillStyle = "#000"; g.fillRect(0, 0, mirror.width, mirror.height); }
  else g.drawImage(mirror, 0, 0);
  Object.assign(blendRun, {name, from: scratch2, queued: performance.now(), started: 0, dur: tlenOf(clip) * 1000});
}

const hashBlock = (x, y, k) => { const v = Math.abs(Math.sin((x + y * 37 + k * 101) * 12.9898) * 43758.5453); return v - Math.floor(v); };

const mix = (g, img, alpha, W, H, filter = "none") => {
  g.save();
  g.globalAlpha = alpha;
  g.filter = filter;
  g.drawImage(img, 0, 0, W, H);
  g.restore();
};

// The outgoing picture grows toward the centre as it fades out while the incoming one settles from the same zoom.
// shape is how far through the zoom it is, 0 to 1, and matches the render's curve.
function zoomThrough(g, A, B, q, W, H, strength, shape) {
  const grow = 1 + strength * shape, settle = 1 + strength * (1 - shape);
  g.drawImage(A, (W - W * grow) / 2, (H - H * grow) / 2, W * grow, H * grow);
  g.save();
  g.globalAlpha = q;
  g.drawImage(B, (W - W * settle) / 2, (H - H * settle) / 2, W * settle, H * settle);
  g.restore();
}

// How each transition combines A (the outgoing frame) and B (the incoming one) at progress q, 0 to 1.
const BLENDS = {
  flash: (g, A, B, q, W, H) => { mix(g, q < 0.5 ? A : B, 1, W, H); g.fillStyle = `rgba(255,255,255,${1 - Math.abs(q - 0.5) * 2})`; g.fillRect(0, 0, W, H); },
  dip: (g, A, B, q, W, H) => { mix(g, q < 0.5 ? A : B, 1, W, H); g.fillStyle = `rgba(0,0,0,${1 - Math.abs(q - 0.5) * 2})`; g.fillRect(0, 0, W, H); },
  swipe_left: (g, A, B, q, W, H) => { g.drawImage(A, -q * W, 0, W, H); g.drawImage(B, (1 - q) * W, 0, W, H); },
  swipe_up: (g, A, B, q, W, H) => { g.drawImage(A, 0, -q * H, W, H); g.drawImage(B, 0, (1 - q) * H, W, H); },
  zoom: (g, A, B, q, W, H) => {
    const s = 1 + q * 0.6;
    g.drawImage(B, 0, 0, W, H);
    g.save();
    g.globalAlpha = 1 - q;
    g.drawImage(A, (W - W * s) / 2, (H - H * s) / 2, W * s, H * s);
    g.restore();
  },
  zoom_in: (g, A, B, q, W, H) => zoomThrough(g, A, B, q, W, H, 0.6, q),
  zoom_out: (g, A, B, q, W, H) => {
    const settle = 1 + 0.25 * (1 - q), shrink = 1 / (1 + 0.5 * q);
    g.drawImage(B, (W - W * settle) / 2, (H - H * settle) / 2, W * settle, H * settle);
    g.save();
    g.globalAlpha = 1 - q;
    g.drawImage(A, (W - W * shrink) / 2, (H - H * shrink) / 2, W * shrink, H * shrink);
    g.restore();
  },
  zoom_punch: (g, A, B, q, W, H) => zoomThrough(g, A, B, q, W, H, 1.4, 1 - Math.pow(1 - q, 3)),
  whip: (g, A, B, q, W, H) => {
    const blur = Math.sin(q * Math.PI) * W * 0.04;
    mix(g, A, 1, W, H, `blur(${blur}px)`);
    mix(g, B, q, W, H, `blur(${blur}px)`);
  },
  pixelize: (g, A, B, q, W, H) => {
    const block = Math.max(1, Math.round(1 + Math.sin(q * Math.PI) * 28));
    const tiny = sizeTo(tinyCanvas, Math.ceil(W / block), Math.ceil(H / block));
    const pass = (img, alpha) => {
      tiny.imageSmoothingEnabled = false;
      tiny.clearRect(0, 0, tinyCanvas.width, tinyCanvas.height);
      tiny.drawImage(img, 0, 0, tinyCanvas.width, tinyCanvas.height);
      g.save();
      g.globalAlpha = alpha;
      g.imageSmoothingEnabled = false;
      g.drawImage(tinyCanvas, 0, 0, W, H);
      g.restore();
    };
    pass(A, 1);
    pass(B, q);
  },
  iris: (g, A, B, q, W, H) => {
    g.drawImage(A, 0, 0, W, H);
    g.save();
    g.beginPath();
    g.arc(W / 2, H / 2, q * Math.hypot(W, H) / 2, 0, Math.PI * 2);
    g.clip();
    g.drawImage(B, 0, 0, W, H);
    g.restore();
  },
  clock: (g, A, B, q, W, H) => {
    g.drawImage(A, 0, 0, W, H);
    g.save();
    g.beginPath();
    g.moveTo(W / 2, H / 2);
    g.arc(W / 2, H / 2, Math.hypot(W, H), -Math.PI / 2, -Math.PI / 2 + q * Math.PI * 2);
    g.closePath();
    g.clip();
    g.drawImage(B, 0, 0, W, H);
    g.restore();
  },
  streak: (g, A, B, q, W, H) => {
    g.drawImage(A, 0, 0, W, H);
    const bands = 48, bh = H / bands;
    for (let i = 0; i < bands; i++) {
      const lead = hashBlock(i, 0, 3) * 0.4, reach = Math.min(1, Math.max(0, (q - lead * (1 - q)) / 0.6)) * W;
      if (reach > 0) g.drawImage(B, W - reach, i * bh, reach, bh + 1, W - reach, i * bh, reach, bh + 1);
    }
  },
  glitch: (g, A, B, q, W, H) => {
    g.drawImage(A, 0, 0, W, H);
    const rows = 24, cols = 8, k = Math.floor((1 - q) * 9);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (q > hashBlock(r, c, k)) {
          const x = Math.round(c * W / cols), y = Math.round(r * H / rows), w = Math.round((c + 1) * W / cols) - x, h = Math.round((r + 1) * H / rows) - y;
          g.drawImage(B, x, y, w, h, x, y, w, h);
        }
      }
    }
  },
};

const picturing = v => v.videoWidth > 0 && v.readyState >= 2 && !v.seeking;

// Called after the clip is drawn: replaces the picture with the blend until the transition has run its length.
function paintTransition() {
  if (!blendRun.from) return;
  const W = mirror.width, H = mirror.height, now = performance.now();
  if (blendRun.from.width !== W || blendRun.from.height !== H || now - blendRun.queued > BLEND_PATIENCE) { blendRun.from = null; return; }
  if (!blendRun.started) {
    if (!picturing(video)) { mctx.drawImage(blendRun.from, 0, 0, W, H); return; }
    blendRun.started = now;
  }
  const q = (now - blendRun.started) / blendRun.dur;
  const blend = BLENDS[blendRun.name];
  if (q >= 1 || !blend) { blendRun.from = null; return; }
  const keep = sizeTo(scratch, W, H);
  keep.clearRect(0, 0, W, H);
  keep.drawImage(mirror, 0, 0);
  mctx.save();
  mctx.fillStyle = "#000";
  mctx.fillRect(0, 0, W, H);
  blend(mctx, blendRun.from, scratch, q, W, H);
  mctx.restore();
}
