// What you decided about each suggested moment, kept on the server per video: the marks come back after a reload, and the
// decisions, with what each moment looked like, are the record the ranking learns from. Depends on app.js (api, toast).
const MOMENT_KEYS = ["text", "why", "parts", "score"];  // the parts of a suggestion worth remembering alongside the decision

const reviewKey = s => `${s.in}:${s.out}`;

// The moment as it was when decided on, with the profile of its video.
function momentSnapshot(s, profile) {
  const kept = Object.fromEntries(MOMENT_KEYS.filter(k => s[k] !== undefined).map(k => [k, s[k]]));
  return profile && profile.kind ? {...kept, profile: profile.kind} : kept;
}

// The saved decisions on a video's moments, as a Map from moment key to "keep" or "skip". Empty when they could not be read.
async function loadReviews(v) {
  try {
    const {reviews = []} = await api(`/api/review/${v.id}`);
    return new Map(reviews.map(r => [reviewKey(r), r.decision]));
  } catch (err) {
    toast(err.message || "Couldn't read earlier decisions");
    return new Map();
  }
}

// Save a decision on a moment: "keep", "skip", or null to forget it.
async function saveReview(v, s, decision, profile) {
  try {
    await api(`/api/review/${v.id}`, "POST", {in: s.in, out: s.out, decision, moment: momentSnapshot(s, profile)});
  } catch (err) {
    toast(err.message || "Couldn't save the decision");
  }
}
