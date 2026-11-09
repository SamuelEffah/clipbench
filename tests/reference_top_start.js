// The plain, unoptimised way to find where a top-lane clip starts, for the performance tests to check the fast paths against.
// Nothing in the editor needs it: previewTiming and the scrub lookup compute the same thing in one pass.
function topStart(idx) {
  let at = 0, prev = null;
  for (let n = 0; n <= idx; n++) {
    const c = state.project.clips[n];
    if (!c || !isTop(c)) continue;
    at -= seamOverlap(prev, c);
    if (n === idx) return at;
    at += outLen(c);
    prev = c;
  }
  return at;
}
