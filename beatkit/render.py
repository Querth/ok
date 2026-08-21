"""Turn an analysis dict into an editable MIDI file and a printable PDF chart.

The MIDI is a standard type-1 file with separate chord / bass / drum tracks, so
it imports into BandLab, GarageBand, FL Studio, Ableton, MuseScore, etc.
"""

import json
import sys

from mido import Message, MetaMessage, MidiFile, MidiTrack, bpm2tempo
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PITCH_INDEX = {n: i for i, n in enumerate(PITCH_NAMES)}
PITCH_INDEX.update({"Db": 1, "Eb": 3, "Gb": 6, "Ab": 8, "Bb": 10})

CHORD_SHAPES = {
    "": [0, 4, 7], "m": [0, 3, 7], "sus4": [0, 5, 7], "sus2": [0, 2, 7],
    "dim": [0, 3, 6], "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11], "m7": [0, 3, 7, 10],
}

TICKS_PER_BEAT = 480
KICK, SNARE, HAT = 36, 38, 42

MAJOR_STEPS = [0, 2, 4, 5, 7, 9, 11]
MINOR_STEPS = [0, 2, 3, 5, 7, 8, 10]
MAJOR_QUALITIES = ["", "m", "m", "", "", "m", "dim"]
MINOR_QUALITIES = ["m", "dim", "", "m", "m", "", ""]
ROMAN_MAJOR = ["I", "ii", "iii", "IV", "V", "vi", "vii°"]
ROMAN_MINOR = ["i", "ii°", "III", "iv", "v", "VI", "VII"]


def parse_chord(name):
    """'C#m7' -> (1, 'm7'). Returns None for 'N.C.' or anything unparseable."""
    if not name or name == "N.C.":
        return None
    root = name[:2] if len(name) > 1 and name[1] in "#b" else name[:1]
    if root not in PITCH_INDEX:
        return None
    suffix = name[len(root):]
    if suffix not in CHORD_SHAPES:
        return None
    return PITCH_INDEX[root], suffix


def chord_notes(name, base=60):
    """MIDI note numbers for a chord, voiced near middle C."""
    parsed = parse_chord(name)
    if parsed is None:
        return []
    root, suffix = parsed
    low = base + root
    if low > base + 11:
        low -= 12
    return [low + off for off in CHORD_SHAPES[suffix]]


def scale_of(key):
    """Notes and diatonic chords for a key like 'F# minor'."""
    parts = key.split()
    tonic = PITCH_INDEX.get(parts[0], 0)
    minor = len(parts) > 1 and parts[1].startswith("min")
    steps = MINOR_STEPS if minor else MAJOR_STEPS
    qualities = MINOR_QUALITIES if minor else MAJOR_QUALITIES
    romans = ROMAN_MINOR if minor else ROMAN_MAJOR

    notes = [PITCH_NAMES[(tonic + s) % 12] for s in steps]
    chords = [PITCH_NAMES[(tonic + s) % 12] + q for s, q in zip(steps, qualities)]
    return notes, chords, romans


def write_midi(analysis, path, beats_per_bar=4):
    """Write chords, bass and drums as three editable tracks."""
    mid = MidiFile(type=1, ticks_per_beat=TICKS_PER_BEAT)
    bar_ticks = TICKS_PER_BEAT * beats_per_bar

    meta = MidiTrack()
    meta.append(MetaMessage("set_tempo", tempo=bpm2tempo(analysis["tempo_bpm"]), time=0))
    meta.append(MetaMessage("time_signature", numerator=beats_per_bar, denominator=4, time=0))
    meta.append(MetaMessage("track_name", name=f"{analysis['key']} @ {analysis['tempo_bpm']} BPM", time=0))
    mid.tracks.append(meta)

    def add_track(name, program, channel, events):
        """events: list of (start_tick, note, duration, velocity)."""
        track = MidiTrack()
        track.append(MetaMessage("track_name", name=name, time=0))
        if channel != 9:
            track.append(Message("program_change", program=program, channel=channel, time=0))

        timeline = []
        for start, note, dur, vel in events:
            timeline.append((start, "note_on", note, vel))
            timeline.append((start + dur, "note_off", note, 0))
        timeline.sort(key=lambda e: (e[0], e[1] == "note_on"))

        clock = 0
        for abs_tick, kind, note, vel in timeline:
            track.append(Message(kind, note=note, velocity=vel,
                                 channel=channel, time=abs_tick - clock))
            clock = abs_tick
        mid.tracks.append(track)

    chord_events = []
    for entry in analysis["chords"]:
        start = entry["index"] * bar_ticks
        for note in chord_notes(entry["chord"]):
            # Leave a short gap so each chord retriggers cleanly.
            chord_events.append((start, note, bar_ticks - 20, 80))
    add_track("Chords", 0, 0, chord_events)

    bass_events = [(b["index"] * bar_ticks, b["midi"], bar_ticks - 20, 95)
                   for b in analysis.get("bass", [])]
    if not bass_events:
        # Fall back to chord roots so the bass track is never empty.
        for entry in analysis["chords"]:
            parsed = parse_chord(entry["chord"])
            if parsed:
                bass_events.append((entry["index"] * bar_ticks, 36 + parsed[0], bar_ticks - 20, 95))
    add_track("Bass", 33, 1, bass_events)

    drums = analysis.get("drums") or {}
    step_ticks = bar_ticks // 16
    drum_events = []
    bar_count = max((c["index"] for c in analysis["chords"]), default=0) + 1
    for bar in range(bar_count):
        for label, note, vel in (("kick", KICK, 110), ("snare", SNARE, 100), ("hat", HAT, 70)):
            for step in drums.get(label, []):
                drum_events.append((bar * bar_ticks + step * step_ticks, note, step_ticks, vel))
    add_track("Drums", 0, 9, drum_events)

    mid.save(path)
    return path


def write_pdf(analysis, path, title="Beat Analysis"):
    c = pdfcanvas.Canvas(path, pagesize=A4)
    width, height = A4
    margin = 18 * mm
    y = height - margin

    def line(text, size=10, gap=5.5 * mm, font="Helvetica"):
        nonlocal y
        c.setFont(font, size)
        c.drawString(margin, y, text)
        y -= gap

    # ---- header -------------------------------------------------------
    line(title, 20, 9 * mm, "Helvetica-Bold")
    c.setStrokeColorRGB(0.75, 0.75, 0.75)
    c.line(margin, y + 3 * mm, width - margin, y + 3 * mm)
    y -= 2 * mm

    line(f"Key: {analysis['key']}     Tempo: {analysis['tempo_bpm']} BPM     "
         f"Time: {analysis['time_signature']}", 11, 6 * mm, "Helvetica-Bold")
    if analysis.get("duration_sec"):
        line(f"Length: {analysis['duration_sec']}s     Bars detected: "
             f"{len(analysis['chords'])}", 9, 8 * mm)

    notes, diatonic, romans = scale_of(analysis["key"])

    # ---- chord chart --------------------------------------------------
    line("CHORD CHART", 13, 7 * mm, "Helvetica-Bold")
    per_row, box_w, box_h = 4, (width - 2 * margin) / 4, 15 * mm
    for i, entry in enumerate(analysis["chords"]):
        if i % per_row == 0:
            if y < margin + 40 * mm:
                c.showPage()
                y = height - margin
            y -= box_h
            row_y = y
        x = margin + (i % per_row) * box_w
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.rect(x, row_y, box_w, box_h)
        c.setFont("Helvetica-Bold", 15)
        c.drawCentredString(x + box_w / 2, row_y + box_h / 2 - 1 * mm, entry["chord"])
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(x + 2 * mm, row_y + box_h - 5 * mm, f"bar {entry['index'] + 1}")
        c.setFillColorRGB(0, 0, 0)
    y -= 10 * mm

    # ---- what to play -------------------------------------------------
    if y < margin + 70 * mm:
        c.showPage()
        y = height - margin

    line("NOTES IN EACH CHORD", 13, 7 * mm, "Helvetica-Bold")
    seen = []
    for entry in analysis["chords"]:
        if entry["chord"] not in seen and parse_chord(entry["chord"]):
            seen.append(entry["chord"])
    for name in seen:
        spelled = " - ".join(PITCH_NAMES[n % 12] for n in chord_notes(name))
        line(f"{name:<8} {spelled}", 10, 5 * mm)
    y -= 3 * mm

    line(f"SCALE — {analysis['key']}", 13, 7 * mm, "Helvetica-Bold")
    line("Notes:  " + "  ".join(notes), 10, 5 * mm)
    line("Chords: " + "  ".join(f"{r}={ch}" for r, ch in zip(romans, diatonic)), 9, 8 * mm)

    # ---- drum grid ----------------------------------------------------
    drums = analysis.get("drums") or {}
    if any(drums.values()):
        if y < margin + 50 * mm:
            c.showPage()
            y = height - margin
        line("DRUM PATTERN (one bar, 16th notes)", 13, 7 * mm, "Helvetica-Bold")
        cell = min(7 * mm, (width - 2 * margin - 22 * mm) / 16)
        for label in ("hat", "snare", "kick"):
            steps = set(drums.get(label, []))
            c.setFont("Helvetica", 9)
            c.drawString(margin, y, label.capitalize())
            for step in range(16):
                x = margin + 22 * mm + step * cell
                c.setStrokeColorRGB(0.8, 0.8, 0.8)
                c.rect(x, y - 2 * mm, cell, cell)
                if step in steps:
                    c.setFillColorRGB(0.1, 0.1, 0.1)
                    c.rect(x, y - 2 * mm, cell, cell, fill=1, stroke=0)
                    c.setFillColorRGB(0, 0, 0)
            y -= cell + 2 * mm
        y -= 4 * mm
        c.setFont("Helvetica", 8)
        c.drawString(margin, y, "Each square is a 16th note. Count: 1 e & a  2 e & a  3 e & a  4 e & a")
        y -= 8 * mm

    c.save()
    return path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: render.py <analysis.json> [basename]")
    with open(sys.argv[1]) as fh:
        data = json.load(fh)
    base = sys.argv[2] if len(sys.argv) > 2 else "beat"
    print(write_midi(data, f"{base}.mid"))
    print(write_pdf(data, f"{base}.pdf", title=data.get("title", "Beat Analysis")))
