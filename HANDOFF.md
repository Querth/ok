# Handoff — beat transcription task

Context for a Claude Code session running **locally** (not sandboxed), picking
up work started in a remote session.

## The goal

The user is learning music. They want a beat turned into:

1. An **editable multi-track file** they can open in BandLab
2. A **PDF of the chords and notes** to play from

Source track: `https://www.youtube.com/watch?v=RrWFlqoWIHY`

## What already exists

`beatkit/` is built, committed and working (PR #1, branch
`claude/beat-analysis-chords-gv5ca4`). Point it at an audio file:

```bash
pip install librosa soundfile mido reportlab
python3 beatkit/run.py path/to/beat.mp3
```

Writes to `output/`: a type-1 `.mid` with separate Chords / Bass / Drums
tracks, a chord-chart `.pdf`, and the raw analysis as `.json`.

| file | role |
|---|---|
| `beatkit/analyze.py` | tempo, key, chords, bass, drums from audio |
| `beatkit/render.py` | MIDI writer + reportlab PDF |
| `beatkit/run.py` | CLI entry point |

Flags worth knowing: `--chords-per-bar 2` when harmony moves twice a bar,
`--beats-per-bar 3` for 3/4, `--title` for the PDF heading.

## What is blocked, and why — do not re-attempt

The remote session had **no network route to YouTube**. The egress proxy
returned a hard 403 on `www.youtube.com`, `youtu.be` and `i.ytimg.com`, and
also on every music-data site tried (Chordify, Tunebat, Songbpm, Genius,
Wikipedia). Searching the video ID surfaced nothing. So the track was never
heard or even identified.

**A local session probably does not have that restriction.** But note the audio
still has to arrive as a *file* — a page fetch does not yield audio, and
pulling media off YouTube is against its terms of service. The intended route
is the user recording or supplying the audio themselves.

## What to do next

1. **Get the audio.** Ask the user for the file, or have them record it
   (Audacity capturing system output, or a phone recording — the analyser
   tolerates phone quality).
2. **Run it:** `python3 beatkit/run.py <file> --title "<track name>"`
3. **Sanity-check the output before handing it over.** See below.
4. **Give the user the `.mid` and `.pdf`** and explain the BandLab import
   (Add Track → Instrument → drag the `.mid` in; the three tracks land
   separately). Drums are GM channel 10: 36 kick, 38 snare, 42 closed hat.

## Verification status — read this before trusting output

Validated against **one synthesised reference beat** with known ground truth
(90 BPM, A minor, `Am F C G`, kick on steps 0/8, snare on 4/12). It recovered
tempo to 89.1, the key, all eight bars of the progression, and both drum
voices exactly.

It has **never been run on real recorded music.** Expect real mixes to be
harder. Known weak points:

- **Tempo** can land on double or half the true value — if it looks wrong,
  halve or double it.
- **Chords** only cover the shapes in `CHORD_SHAPES` (maj, min, sus2, sus4,
  dim, 7, maj7, m7). Anything richer gets approximated to the nearest one.
- **Drums** are the least reliable output. A hi-hat under a loud kick gets
  masked, so hat steps that coincide with kicks are often missing.
- **Chord placement** assumes changes fall on bar lines.

Check the result by ear against the record and correct it. Say plainly which
parts are machine-guessed rather than presenting the chart as authoritative —
the user is a beginner and will practise whatever they are handed.
