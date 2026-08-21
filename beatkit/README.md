# beatkit — turn a beat into something you can play and edit

Point it at an audio file and it works out the tempo, the key, the chord
progression, the bass notes and the drum pattern, then writes:

| file | what it's for |
|---|---|
| `<name>.mid` | **Import this into BandLab** (or GarageBand, FL Studio, Ableton, MuseScore). Separate Chords / Bass / Drums tracks you can edit note by note. |
| `<name>.pdf` | Printable chord chart, the notes inside every chord, the scale to solo over, and the drum grid. |
| `<name>.json` | The raw analysis, if you want the numbers. |

## Use it

```bash
pip install librosa soundfile mido reportlab
python3 beatkit/run.py mybeat.mp3
```

Results land in `output/`. Useful flags:

- `--chords-per-bar 2` — if the chords change twice per bar rather than once
- `--title "Song Name"` — sets the heading on the PDF
- `--beats-per-bar 3` — for waltz-time material

## Getting the MIDI into BandLab

1. Open your BandLab project, then **Add Track** and choose **Instrument**.
2. Drag the `.mid` file onto the track area (or use **Import** and pick it
   from your computer).
3. The three tracks come in separately — assign a piano to Chords, a bass to
   Bass, and a drum kit to Drums.

The drum track is written on MIDI channel 10 using General MIDI notes
(36 kick, 38 snare, 42 closed hat), which is the mapping most drum
instruments expect.

## Running it on your own laptop

Nothing here needs the internet once installed, so this works anywhere.

**1. Get Python 3.9+** — `python3 --version` to check. If it is missing, install
it from python.org (tick "Add Python to PATH" on Windows).

**2. Get the code and the libraries:**

```bash
git clone https://github.com/Querth/ok.git
cd ok
pip install librosa soundfile mido reportlab
```

**3. Put your audio somewhere and run it:**

```bash
python3 beatkit/run.py ~/Music/mybeat.mp3
```

The chart and MIDI appear in `output/`. That is it.

**If mp3 loading complains**, install ffmpeg and try again — `brew install ffmpeg`
on macOS, `sudo apt install ffmpeg` on Ubuntu, or download it from ffmpeg.org on
Windows. Converting the file to `.wav` first also sidesteps the problem.

**Recording a track to analyse:** the simplest route is Audacity (free, all
platforms) set to record your computer's own output, or just your phone's voice
recorder held near the speakers. The analyser is fairly forgiving — a phone
recording is usually clean enough to get tempo and chords out of.

## How much to trust it

Machine listening is good at some of this and shaky at other parts:

- **Tempo** is reliable, but can land on double or half the real value
  (e.g. 140 reported for a 70 BPM track). If it feels wrong, halve or double it.
- **Key and chords** are solid on material with clear harmony. Dense, distorted
  or very bass-heavy mixes confuse the chroma, and the analyser only knows the
  chord shapes listed in `CHORD_SHAPES` — it will approximate anything more
  exotic.
- **Drums** are the least certain part. A hi-hat played underneath a loud kick
  is often masked, so the hat row can miss the steps where the kick lands.
- **Chord placement** assumes chords change on the bar line. If the progression
  moves faster, pass `--chords-per-bar 2`.

Treat the output as a very fast first transcription to correct by ear, not as
a finished score — checking it against the record is the part that teaches you
the most anyway.
