# Trans-Siberian DV Archive Project

**Status:** Ready to test

**Created:** 2026-02-15

**Chat:** [Original Claude conversation](https://claude.ai)

---

## Summary

Python script to join `.DV` video files from Craig & Anna's 2002 Trans-Siberian trip (Europe → Russia → Mongolia → China) into modern MP4 format. The raw footage is organised across 6 folders representing trip chapters, with filenames containing date/time stamps in the format `clip-2002-03-13 08;37;36.dv`.

## What the Script Does

1. Scans directories recursively for `.dv` / `.DV` files
2. Parses date/time from filenames (handles semicolons in `clip-YYYY-MM-DD HH;MM;SS.dv`)
3. Sorts files chronologically within each folder
4. Concatenates using ffmpeg's concat demuxer into H.264/AAC MP4
5. Deinterlaces PAL DV (720×576i @ 25fps) to progressive
6. Encodes at CRF 18 (visually lossless — ideal for home video archival)

## Folder Structure

The 6 source folders represent trip chapters, sorted alphabetically:

```
Europe-Russia-Mongolia-China-2002     → Chapter 1 (base)
Europe-Russia-Mongolia-China-2002-b   → Chapter 2
Europe-Russia-Mongolia-China-2002-c   → Chapter 3
Europe-Russia-Mongolia-China-2002-d   → Chapter 4
Europe-Russia-Mongolia-China-2002-e   → Chapter 5
Europe-Russia-Mongolia-China-2002-f   → Chapter 6
```

Each folder produces one MP4 output file.

## Prerequisites

- **Python 3.10+** (uses `match` union types)
- **ffmpeg** — `brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux)

## Quick Start

### Step 1 — Dry run (see what will happen, no encoding)

```bash
python3 dv_joiner.py /path/to/parent/folder --recursive --per-folder --dry-run
```

### Step 2 — Test with first 10 files (fast encode)

```bash
python3 dv_joiner.py /path/to/parent/folder --recursive --per-folder --limit 10 --preset fast
```

### Step 3 — Full encode (all 6 chapters)

```bash
python3 dv_joiner.py /path/to/parent/folder --recursive --per-folder
```

Output goes to a `joined/` subdirectory.

## Key Options

| Flag | What it does |
| --- | --- |
| `--recursive` / `-r` | Search all subdirectories |
| `--per-folder` | One MP4 per folder/chapter (recommended) |
| `--single` | Join everything into one giant MP4 |
| `--gap N` | Session grouping: split if >N minutes gap (default 30) |
| `--limit N` | Process only first N files (for testing) |
| `--dry-run` | Preview without encoding |
| `--crf N` | Quality: 0=lossless, 18=excellent (default), 23=good |
| `--preset` | Speed: ultrafast/fast/medium/slow(default)/veryslow |

## Technical Notes

- **DV format:** Raw DV from 2002 MiniDV/Digital8 recorders. PAL = 720×576 interlaced @ 25fps, ~3.6 MB/sec (~13 GB/hour)
- **Deinterlacing:** Uses yadif (mode 0) to convert interlaced fields to progressive frames
- **Output codec:** H.264 (libx264) with AAC audio at 192kbps, 48kHz — plays everywhere
- **Container:** MP4 with faststart flag for streaming compatibility
- **Filename parsing:** Handles semicolons as time separators (`08;37;36`), which is non-standard but matches the recorder's output
- **Folder ordering:** Base folder (no suffix) sorts before `-b` through `-f`

## Encoding Time Estimates

Rough guide for a modern Mac (M-series):

| Preset | Speed vs realtime | 1 hour of DV |
| --- | --- | --- |
| ultrafast | ~10x | ~6 min |
| fast | ~5x | ~12 min |
| slow (default) | ~2x | ~30 min |
| veryslow | ~0.8x | ~75 min |

## Future Enhancements

- Add chapter markers in the MP4 based on time gaps between clips
- Generate thumbnail contact sheet for each chapter
- Overlay date/location text on first frame of each clip
- Extract and geotag based on trip itinerary dates
