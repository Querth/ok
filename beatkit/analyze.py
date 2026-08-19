"""Analyse an audio file: tempo, key, chords per bar, bass line, drum pattern.

Everything here is measured from the audio itself -- nothing is assumed about
the track. The output is a plain dict (dumped to JSON) that render.py turns
into a MIDI file and a printable chord/notes chart.
"""

import json
import sys

import librosa
import numpy as np

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Kessler key profiles: how strongly each scale degree is weighted
# in a major and a minor key.
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Chord templates as semitone offsets from the root. Ordered roughly from
# simple to complex; the penalty below keeps us from always picking the
# chord with the most notes.
CHORD_SHAPES = {
    "": [0, 4, 7],
    "m": [0, 3, 7],
    "sus4": [0, 5, 7],
    "sus2": [0, 2, 7],
    "dim": [0, 3, 6],
    "7": [0, 4, 7, 10],
    "maj7": [0, 4, 7, 11],
    "m7": [0, 3, 7, 10],
}
# Larger chords explain more of the chroma by construction, so we discount them.
SHAPE_PENALTY = {"": 1.0, "m": 1.0, "sus4": 0.97, "sus2": 0.97, "dim": 0.95,
                 "7": 0.96, "maj7": 0.96, "m7": 0.96}


def _chord_templates():
    """Build a (name, unit-norm 12-vector) list covering every root and shape."""
    templates = []
    for root in range(12):
        for suffix, offsets in CHORD_SHAPES.items():
            vec = np.zeros(12)
            for off in offsets:
                vec[(root + off) % 12] = 1.0
            vec /= np.linalg.norm(vec)
            templates.append((PITCH_NAMES[root] + suffix, vec * SHAPE_PENALTY[suffix]))
    return templates


TEMPLATES = _chord_templates()


def detect_key(chroma):
    """Correlate the average chroma against all 24 rotated key profiles."""
    avg = chroma.mean(axis=1)
    if avg.sum() == 0:
        return "C major", 0.0
    avg = avg / avg.sum()

    best = (None, -2.0)
    for tonic in range(12):
        for profile, mode in ((KK_MAJOR, "major"), (KK_MINOR, "minor")):
            rotated = np.roll(profile, tonic)
            score = float(np.corrcoef(avg, rotated)[0, 1])
            if score > best[1]:
                best = (f"{PITCH_NAMES[tonic]} {mode}", score)
    return best[0], round(best[1], 3)


def detect_downbeat_offset(chroma, beat_frames, beats_per_bar=4):
    """Find beat 1 by testing which phase puts the biggest harmonic changes on bar lines.

    Chords overwhelmingly change at the start of a bar, so the correct phase is
    the one where chroma differs most across its bar boundaries.
    """
    if len(beat_frames) < beats_per_bar * 2:
        return 0

    # Average chroma over each beat, then measure change between consecutive beats.
    per_beat = []
    for i in range(len(beat_frames) - 1):
        f0, f1 = beat_frames[i], beat_frames[i + 1]
        seg = chroma[:, f0:f1].mean(axis=1) if f1 > f0 else np.zeros(12)
        norm = np.linalg.norm(seg)
        per_beat.append(seg / norm if norm > 1e-6 else seg)

    novelty = np.zeros(len(per_beat))
    for i in range(1, len(per_beat)):
        novelty[i] = np.linalg.norm(per_beat[i] - per_beat[i - 1])

    scores = np.zeros(beats_per_bar)
    for phase in range(beats_per_bar):
        hits = novelty[phase::beats_per_bar]
        scores[phase] = hits.mean() if len(hits) else 0.0
    return int(np.argmax(scores))


def refine_key(key, chords, bass):
    """Disambiguate relative major/minor, which share identical scale notes.

    Krumhansl scoring cannot separate e.g. C major from A minor, so decide by
    which tonic actually behaves like home: how often its own triad is played,
    and what the track lands on at the end.
    """
    tonic_name, mode = key.split()
    tonic = PITCH_NAMES.index(tonic_name)
    if mode == "major":
        alt, alt_mode = (tonic + 9) % 12, "minor"
    else:
        alt, alt_mode = (tonic + 3) % 12, "major"

    def home_score(pc, is_minor):
        want = PITCH_NAMES[pc] + ("m" if is_minor else "")
        score = 0.0
        for entry in chords:
            name = entry["chord"]
            if name == want:
                score += 2.0 * entry.get("confidence", 1.0)
            elif name.startswith(want) and not (is_minor is False and name[len(want):].startswith("m")):
                score += 1.0 * entry.get("confidence", 1.0)
        if chords and chords[-1]["chord"].startswith(want):
            score += 1.5          # ending on the tonic is a strong signal
        if chords and chords[0]["chord"].startswith(want):
            score += 1.0
        for note in bass:
            if note["midi"] % 12 == pc:
                score += 0.25
        return score

    current = home_score(tonic, mode == "minor")
    other = home_score(alt, alt_mode == "minor")
    if other > current:
        return f"{PITCH_NAMES[alt]} {alt_mode}"
    return key


def detect_chords(chroma, beat_frames, downbeat, beats_per_bar=4, chords_per_bar=1):
    """Average chroma over each chord window and match it to a template."""
    beats_per_chord = max(1, beats_per_bar // chords_per_bar)
    chords = []
    start_indices = range(downbeat, len(beat_frames) - 1, beats_per_chord)

    for bar_index, start in enumerate(start_indices):
        end = min(start + beats_per_chord, len(beat_frames) - 1)
        f0, f1 = beat_frames[start], beat_frames[end]
        if f1 <= f0:
            continue

        window = chroma[:, f0:f1].mean(axis=1)
        norm = np.linalg.norm(window)
        if norm < 1e-6:
            chords.append({"index": bar_index, "chord": "N.C.", "confidence": 0.0})
            continue
        window = window / norm

        scores = [(float(np.dot(window, vec)), name) for name, vec in TEMPLATES]
        score, name = max(scores)
        chords.append({"index": bar_index, "chord": name, "confidence": round(score, 3)})
    return chords


def detect_bass(y, sr, beat_times, downbeat, beats_per_bar=4):
    """Track the lowest pitched voice, one note per bar."""
    y_low = librosa.effects.harmonic(y)
    notes = []
    for bar_index, start in enumerate(range(downbeat, len(beat_times) - 1, beats_per_bar)):
        end = min(start + beats_per_bar, len(beat_times) - 1)
        seg = y_low[int(beat_times[start] * sr):int(beat_times[end] * sr)]
        if len(seg) < 2048:
            continue
        try:
            f0 = librosa.yin(seg, fmin=38, fmax=260, sr=sr)
            f0 = f0[np.isfinite(f0) & (f0 > 0)]
            if len(f0) == 0:
                continue
            midi = int(round(librosa.hz_to_midi(float(np.median(f0)))))
        except Exception:
            continue
        # Pitch trackers routinely land an octave off on bass material. The
        # pitch class is what carries the harmony, so keep that and pin the
        # octave to C2-B2, where a bass part actually sits.
        midi = 36 + (midi % 12)
        notes.append({"index": bar_index, "midi": midi,
                      "name": librosa.midi_to_note(midi)})
    return notes


def detect_drums(y, sr, beat_times, downbeat, beats_per_bar=4, grid=16):
    """Find kick / snare / hat from onset strength in three mel bands.

    Each band is normalised against its own loudness first, so a quiet hi-hat
    is still comparable to a loud kick. A single hit then fires whichever
    voices its band profile matches -- a kick and a hat on the same 16th are
    two labels on one onset, not a contest between them.

    Returns a 16th-note grid for one bar, voted across every bar in the track,
    which is what makes the result robust to a few mis-read hits.
    """
    _, y_perc = librosa.effects.hpss(y)
    if len(beat_times) <= downbeat + beats_per_bar:
        return {"kick": [], "snare": [], "hat": []}

    # Mel band edges: lows (kick), mids (snare shell), highs (hats/cymbals).
    bands = librosa.onset.onset_strength_multi(y=y_perc, sr=sr, channels=[0, 16, 56, 128])
    norm = np.array([b / max(np.percentile(b, 95), 1e-9) for b in bands])

    frames = librosa.onset.onset_detect(onset_envelope=norm.sum(axis=0), sr=sr, backtrack=False)
    # Each voice is scored against the band that defines it.
    band_of = {"kick": 0, "snare": 1, "hat": 2}
    hits = []
    for frame in frames:
        low, mid, high = norm[0][frame], norm[1][frame], norm[2][frame]
        labels = []
        # A kick is low energy that clearly outweighs the top end.
        if low >= 0.45 and low > high * 1.2:
            labels.append("kick")
        # A snare has shell (mid) plus noise (high) sitting on real body (low).
        if mid >= 0.35 and low >= 0.35 and high >= low * 0.5:
            labels.append("snare")
        # A hat is top end with almost nothing in the mids.
        if high >= 0.45 and mid < high:
            labels.append("hat")
        if labels:
            hits.append((librosa.frames_to_time(frame, sr=sr), labels, frame))

    bar_starts = list(range(downbeat, len(beat_times) - beats_per_bar, beats_per_bar))
    votes = {name: np.zeros(grid) for name in band_of}
    energy = {name: np.zeros(grid) for name in band_of}
    bars_counted = 0

    for start in bar_starts:
        t0, t1 = beat_times[start], beat_times[start + beats_per_bar]
        if t1 <= t0:
            continue
        bars_counted += 1
        step = (t1 - t0) / grid
        for t, labels, frame in hits:
            if t0 <= t < t1:
                # Round, don't floor: a hit a hair early belongs to the step it
                # is aiming at, not the one before it.
                slot = int(round((t - t0) / step)) % grid
                for label in labels:
                    votes[label][slot] += 1
                    energy[label][slot] += norm[band_of[label]][frame]

    if bars_counted == 0:
        return {"kick": [], "snare": [], "hat": []}

    threshold = max(1.0, bars_counted * 0.35)
    pattern = {}
    for name, v in votes.items():
        steps = [int(i) for i in np.where(v >= threshold)[0]]
        # Mean band strength per step -- how hard that hit actually was.
        mean = np.divide(energy[name], v, out=np.zeros(grid), where=v > 0)
        pattern[name] = _drop_ringing(steps, mean)
    return pattern


def _drop_ringing(steps, strength):
    """Remove a hit that is really the previous hit's tail still ringing.

    A long kick decaying across a 16th boundary retriggers onset detection just
    as reliably as a real hit, so counting occurrences cannot tell them apart --
    a ringing tail fires every single bar. What separates them is force: the
    tail is always markedly weaker than the hit that caused it, while a genuine
    16th-note double (very common in trap) is played at comparable strength.
    """
    kept = []
    for step in steps:
        if kept and step == kept[-1] + 1 and strength[step] < strength[kept[-1]] * 0.6:
            continue
        kept.append(step)
    return kept


def extend_beats(beat_frames):
    """Extrapolate the beat grid back to the start of the track.

    librosa often locks on from the second or third beat, which silently drops
    the opening bar from the chord chart. Adding the missing beats at the
    established period recovers it.
    """
    if len(beat_frames) < 2:
        return beat_frames
    period = float(np.median(np.diff(beat_frames)))
    if period <= 0:
        return beat_frames
    lead = []
    frame = beat_frames[0] - period
    while frame >= 0:
        lead.append(int(round(frame)))
        frame -= period
    return np.concatenate([np.array(lead[::-1], dtype=int), beat_frames]) if lead else beat_frames


def analyze(path, beats_per_bar=4, chords_per_bar=1):
    y, sr = librosa.load(path, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    tempo = float(np.atleast_1d(tempo)[0])
    beat_frames = extend_beats(beat_frames)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # Chords come from the harmonic part so drums don't smear the chroma.
    y_harm = librosa.effects.harmonic(y)
    chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr)

    downbeat = detect_downbeat_offset(chroma, beat_frames, beats_per_bar)
    chords = detect_chords(chroma, beat_frames, downbeat, beats_per_bar, chords_per_bar)
    bass = detect_bass(y, sr, beat_times, downbeat, beats_per_bar)

    key, key_confidence = detect_key(chroma)
    key = refine_key(key, chords, bass)

    return {
        "source": path,
        "duration_sec": round(duration, 2),
        "tempo_bpm": round(tempo, 1),
        "time_signature": f"{beats_per_bar}/4",
        "key": key,
        "key_confidence": key_confidence,
        "beat_count": int(len(beat_times)),
        "downbeat_offset": downbeat,
        "chords": chords,
        "bass": bass,
        "drums": detect_drums(y, sr, beat_times, downbeat, beats_per_bar),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: analyze.py <audiofile> [out.json]")
    result = analyze(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 else "analysis.json"
    with open(out, "w") as fh:
        json.dump(result, fh, indent=2)
    print(f"{result['tempo_bpm']} BPM | {result['key']} | {len(result['chords'])} bars -> {out}")
