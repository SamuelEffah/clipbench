// Tighten talk: when a Short runs long, the pauses between what is said are cut before anything else is. Each pause cut
// splits its piece, so the words stay whole and only the quiet goes. Depends on app.js (api, toast, outLen) and
// autolayout.js (TOUCH, the piece shape {clip, found, from}).
const TALK_LAYOUTS = new Set(["single", "people"]);  // layouts that are someone talking; a webcam over gameplay keeps its quiet, the game is still running
const MIN_PIECE = 0.25;  // seconds; a stretch left beside a pause shorter than this would only flash by, so the piece is trimmed to the pause instead

const isTalk = piece => TALK_LAYOUTS.has(piece.found && piece.found.layout);
const runningTime = (pieces, lengthOf) => pieces.reduce((sum, p) => sum + lengthOf(p.clip), 0);

// A piece with its pauses taken out: one piece for each stretch left between them, the first keeping the caption, the
// rest marked as made by a pause cut so they are not counted as shot changes. `cuts` are [start, end] in order.
function splitOut(piece, cuts) {
  if (!cuts.length) return [piece];
  const ranges = [];
  let at = piece.clip.in;
  for (const [a, b] of cuts) {
    if (a - at >= MIN_PIECE) ranges.push([at, a]);
    at = Math.max(at, b);
  }
  if (piece.clip.out - at >= MIN_PIECE) ranges.push([at, piece.clip.out]);
  return ranges.map(([a, b], n) => ({...piece, pause: n > 0, clip: {...piece.clip, in: a, out: b, ...(n ? {caption: "", words: null} : {})}}));
}

// The pieces with enough pauses cut to bring their running time within `max`: the longest pauses first, from the talk
// pieces only. `pausesOf(piece)` lists [start, end] pauses in the piece's video. Pieces that already fit come back as they are.
function cutPauses(pieces, pausesOf, max, lengthOf = outLen) {
  let over = runningTime(pieces, lengthOf) - max;
  if (over <= 0.05) return pieces;
  const saves = (piece, a, b) => (b - a) / (piece.clip.speed || 1);
  const options = pieces.flatMap(piece => (isTalk(piece) ? pausesOf(piece) : [])
    .filter(([a, b]) => a >= piece.clip.in && b <= piece.clip.out)
    .map(([a, b]) => ({piece, a, b, saves: saves(piece, a, b)}))).sort((x, y) => y.saves - x.saves);
  const chosen = [];
  for (const option of options) {
    if (over <= 0.05) break;
    chosen.push(option);
    over -= option.saves;
  }
  if (!chosen.length) return pieces;
  return pieces.flatMap(piece => splitOut(piece, chosen.filter(o => o.piece === piece).map(o => [o.a, o.b]).sort((x, y) => x[0] - y[0])));
}

// The pauses of the spans that hold talk, asked of the server only when the Short runs past `max`. Returns a lookup from a
// piece to the pauses in its video. A span whose sound could not be read says so and gives no pauses, so the tail trim still lands the length.
async function pausesFor(pieces, spans, max, lengthOf = outLen) {
  const none = () => [];
  if (runningTime(pieces, lengthOf) <= max + 0.05) return none;
  const within = (p, s) => p.clip.src === s.src && p.clip.in >= s.in - TOUCH && p.clip.out <= s.out + TOUCH;
  const talking = spans.filter(s => pieces.some(p => isTalk(p) && within(p, s)));
  const found = await Promise.all(talking.map(s => api("/api/pauses", "POST", {src: s.src, in: s.in, out: s.out}).then(r => r.pauses || [], err => { toast(err.message || "Could not look for pauses"); return []; })));
  return piece => talking.flatMap((s, n) => (s.src === piece.clip.src ? found[n] : []));
}
