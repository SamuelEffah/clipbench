"""Where the beats fall in a track, so clips cut from music start and end on a hit instead of mid-phrase.

Onsets are found from the loudness track alone: the steps where it jumps up, kept when they stand well above
the usual jump. That needs no tempo estimate, so it cannot drift over a long track."""

ONSET_SPREAD = 1.0
MIN_GAP = 0.25


def onsets(peaks, per_sec):
    """Times, in seconds, of the strong upward jumps in loudness."""
    if len(peaks) < 3:
        return []
    jumps = [max(0, peaks[i] - peaks[i - 1]) for i in range(1, len(peaks))]
    mean = sum(jumps) / len(jumps)
    spread = (sum((j - mean) ** 2 for j in jumps) / len(jumps)) ** 0.5
    floor = mean + ONSET_SPREAD * spread
    found = []
    for i, jump in enumerate(jumps):
        if jump <= floor or (i and jumps[i - 1] > jump) or (i + 1 < len(jumps) and jumps[i + 1] > jump):
            continue
        at = (i + 1) / per_sec
        if found and at - found[-1] < MIN_GAP:
            continue
        found.append(round(at, 3))
    return found
