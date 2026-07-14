# dv-joiner

A small Python utility for joining timestamped DV video clips into modern MP4 files with FFmpeg.

It is designed for personal video archives where clips are spread across folders and filenames carry recording timestamps such as `clip-2002-03-13 08;37;36.dv`.

## What it does

1. Scans directories for `.dv` and `.DV` files
2. Parses recording dates and times from several filename formats
3. Sorts clips chronologically
4. Groups clips by folder, recording session, or a single combined output
5. Uses FFmpeg to encode H.264 video and AAC audio in an MP4 container
6. Deinterlaces typical PAL or NTSC DV footage with `yadif`

## Requirements

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/), including `ffprobe`

Install FFmpeg on macOS with Homebrew:

```bash
brew install ffmpeg
```

On Debian or Ubuntu:

```bash
sudo apt install ffmpeg
```

## Quick start

Start with a dry run to inspect ordering and grouping without encoding:

```bash
python3 dv_joiner.py /path/to/archive --recursive --per-folder --dry-run
```

Test a small batch:

```bash
python3 dv_joiner.py /path/to/archive --recursive --per-folder --limit 10 --preset fast
```

Run the full encode:

```bash
python3 dv_joiner.py /path/to/archive --recursive --per-folder
```

Output goes to a `joined/` directory under the source path unless `--output` is supplied.

## Common modes

### One MP4 per source folder

Useful when archive folders already represent tapes, days, or chapters:

```bash
python3 dv_joiner.py /path/to/archive --recursive --per-folder
```

### Group by recording session

The default mode starts a new output when the gap between clips exceeds 30 minutes:

```bash
python3 dv_joiner.py /path/to/archive --recursive --gap 30
```

### Join everything

```bash
python3 dv_joiner.py /path/to/archive --recursive --single
```

## Options

| Flag | Purpose |
| --- | --- |
| `--recursive`, `-r` | Search subdirectories |
| `--per-folder` | Produce one MP4 per source folder |
| `--single` | Join all discovered clips into one MP4 |
| `--gap N` | Start a new session after a gap of N minutes |
| `--limit N` | Process only the first N clips |
| `--dry-run` | Preview ordering, grouping, size, and output names |
| `--output PATH`, `-o PATH` | Choose the output directory |
| `--crf N` | Set H.264 quality. Lower values retain more detail |
| `--preset NAME` | Choose the FFmpeg encoding speed preset |

Run `python3 dv_joiner.py --help` for the complete CLI reference.

## Filename handling

The parser recognises several timestamp styles, including:

```text
clip-2002-03-13 08;37;36.dv
2002-03-15_14-30-22.dv
20020315_143022.dv
20020315_1430.dv
15-03-2002_14-30-22.dv
```

If no timestamp can be parsed, the script falls back to the file modification time and prints a warning.

## Encoding defaults

- Video: H.264 via `libx264`
- Quality: CRF 18
- Preset: `slow`
- Pixel format: `yuv420p`
- Deinterlacing: `yadif=mode=0`
- Audio: AAC, 192 kbps, 48 kHz
- Container: MP4 with `faststart`

Archival workflows differ. Keep the original DV files after conversion and test a representative sample before processing a large archive.
