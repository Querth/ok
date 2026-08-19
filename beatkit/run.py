"""One-command entry point: audio file in, MIDI + PDF + JSON out.

    python3 beatkit/run.py mybeat.mp3
    python3 beatkit/run.py mybeat.mp3 --title "My Beat" --chords-per-bar 2
"""

import argparse
import json
import os

from analyze import analyze
from render import write_midi, write_pdf


def main():
    parser = argparse.ArgumentParser(description="Analyse a beat into an editable MIDI file and a chord/notes PDF.")
    parser.add_argument("audio", help="audio file (mp3, wav, m4a, flac, ogg...)")
    parser.add_argument("--title", help="title printed on the PDF")
    parser.add_argument("--outdir", default="output", help="where to write the results")
    parser.add_argument("--beats-per-bar", type=int, default=4)
    parser.add_argument("--chords-per-bar", type=int, default=1,
                        help="use 2 if the chords change on the half bar")
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.audio))[0]
    title = args.title or stem

    print(f"Analysing {args.audio} ...")
    result = analyze(args.audio, args.beats_per_bar, args.chords_per_bar)
    result["title"] = title

    base = os.path.join(args.outdir, stem)
    with open(f"{base}.json", "w") as fh:
        json.dump(result, fh, indent=2)
    write_midi(result, f"{base}.mid", args.beats_per_bar)
    write_pdf(result, f"{base}.pdf", title=title)

    progression = " | ".join(c["chord"] for c in result["chords"][:8])
    print(f"\n  Key    {result['key']}")
    print(f"  Tempo  {result['tempo_bpm']} BPM")
    print(f"  Bars   {len(result['chords'])}")
    print(f"  Chords {progression}{' ...' if len(result['chords']) > 8 else ''}")
    print(f"\nWrote {base}.mid, {base}.pdf, {base}.json")


if __name__ == "__main__":
    main()
