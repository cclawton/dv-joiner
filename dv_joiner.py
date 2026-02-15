#!/usr/bin/env python3
"""
DV Video File Joiner
====================
Joins .DV files from a MiniDV/Digital8 tape recorder into modern MP4 (H.264/AAC).
DV files from 2002 are typically:
  - 720x576 (PAL) or 720x480 (NTSC) at 25fps or 29.97fps
  - DV codec video, 16-bit PCM audio
  - ~13GB/hour (~3.6MB/sec) for full DV, smaller clips proportional
This script:
  1. Scans directories for .dv/.DV files
  2. Sorts them chronologically by filename (date/time stamp)
  3. Groups files by recording session (configurable gap threshold)
  4. Concatenates each group into a single MP4 using ffmpeg
  5. Preserves original timestamps in output filenames
Usage:
  # Dry run first (always recommended)
  python3 dv_joiner.py /path/to/dv/files --dry-run
  # Process with defaults (groups files with <30min gap)
  python3 dv_joiner.py /path/to/dv/files
  # Limit to first 10 files for testing
  python3 dv_joiner.py /path/to/dv/files --limit 10
  # Process all 6 subdirectories, custom gap
  python3 dv_joiner.py /path/to/dv/files --recursive --gap 60
  # Join ALL files into one single video (no session grouping)
  python3 dv_joiner.py /path/to/dv/files --single
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
# ─────────────────────────────────────────────
# CONFIGURATION - Adjust these for your files
# ─────────────────────────────────────────────
# Common date/time patterns found in DV filenames from 2002-era recorders.
# Add your own pattern if none of these match.
# Each pattern: (regex, datetime format string)
FILENAME_PATTERNS = [
    # 2002-03-15_14-30-22.dv  or  2002-03-15 14-30-22.dv
    (r"(\d{4}[-_]\d{2}[-_]\d{2}[-_ ]\d{2}[-_]\d{2}[-_]\d{2})", "%Y-%m-%d_%H-%M-%S"),
    # 20020315_143022.dv  or  20020315143022.dv
    (r"(\d{8}[-_]?\d{6})", None),  # handled specially
    # 20020315_1430.dv (no seconds)
    (r"(\d{8}[-_]?\d{4})(?!\d)", None),  # handled specially
    # 15-03-2002_14-30-22.dv (DD-MM-YYYY)
    (r"(\d{2}[-_]\d{2}[-_]\d{4}[-_ ]\d{2}[-_]\d{2}[-_]\d{2})", "%d-%m-%Y_%H-%M-%S"),
    # Mar152002_143022.dv style
    (r"([A-Za-z]{3}\d{1,2}\d{4}[-_]\d{6})", None),
]
def parse_datetime_from_filename(filename: str) -> datetime | None:
    """
    Extract a datetime from a DV filename's date/time stamp.
    Primary format: clip-2002-03-13 08;37;36.dv
    Also handles other common patterns from 2002-era recorders.
    """
    stem = Path(filename).stem
    # Normalise all separators: semicolons, spaces, underscores → consistent format
    normalised = stem.replace(";", "-").replace(" ", "_").replace(".", "_")
    # Pattern 1 (PRIMARY): clip-YYYY-MM-DD_HH-MM-SS
    # Matches: clip-2002-03-13 08;37;36 → clip-2002-03-13_08-37-36
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[-_ ](\d{2})-(\d{2})-(\d{2})", normalised)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]),
                            int(m[4]), int(m[5]), int(m[6]))
        except ValueError:
            pass
    # Pattern 2: YYYYMMDD_HHMMSS or YYYYMMDDHHMMSS
    m = re.search(r"(\d{4})(\d{2})(\d{2})[-_]?(\d{2})(\d{2})(\d{2})", normalised)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]),
                            int(m[4]), int(m[5]), int(m[6]))
        except ValueError:
            pass
    # Pattern 3: YYYYMMDD_HHMM (no seconds)
    m = re.search(r"(\d{4})(\d{2})(\d{2})[-_]?(\d{2})(\d{2})(?!\d)", normalised)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]),
                            int(m[4]), int(m[5]))
        except ValueError:
            pass
    # Pattern 4: DD-MM-YYYY_HH-MM-SS (AU/EU format)
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})[-_ ](\d{2})-(\d{2})-(\d{2})", normalised)
    if m:
        try:
            return datetime(int(m[3]), int(m[2]), int(m[1]),
                            int(m[4]), int(m[5]), int(m[6]))
        except ValueError:
            pass
    # Fallback: use file modification time
    return None
def get_dv_files(source_dir: str, recursive: bool = False, verbose: bool = False) -> list[dict]:
    """Find all .dv/.DV files and extract their timestamps."""
    source = Path(source_dir)
    if not source.exists():
        print(f"ERROR: Directory not found: {source_dir}")
        sys.exit(1)
    if recursive:
        dv_files = list(source.rglob("*.dv")) + list(source.rglob("*.DV"))
    else:
        dv_files = list(source.glob("*.dv")) + list(source.glob("*.DV"))
    if verbose:
        print(f"  Raw file matches: {len(dv_files)}")
        folders_seen = set()
        for f in dv_files:
            folder = str(f.parent)
            if folder not in folders_seen:
                folders_seen.add(folder)
                folder_count = sum(1 for x in dv_files if str(x.parent) == folder)
                print(f"    {f.parent.name}/: {folder_count} file(s)")

    # Deduplicate (case-insensitive filesystems)
    seen = set()
    unique_files = []
    for f in dv_files:
        resolved = f.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_files.append(f)
    results = []
    skipped = 0
    for f in unique_files:
        # Validate DV file is readable before including it
        if not validate_dv_file(f):
            size_kb = f.stat().st_size / 1024
            print(f"  SKIPPING invalid/corrupt DV file: {f.name} ({size_kb:.0f} KB) in {f.parent.name}/")
            skipped += 1
            continue
        dt = parse_datetime_from_filename(f.name)
        if dt is None:
            # Fall back to file modification time
            mtime = os.path.getmtime(f)
            dt = datetime.fromtimestamp(mtime)
            print(f"  WARNING: Could not parse date from '{f.name}', using file mtime: {dt}")
        results.append({
            "path": f,
            "datetime": dt,
            "filename": f.name,
            "size_mb": f.stat().st_size / (1024 * 1024),
        })
    if skipped:
        print(f"  Skipped {skipped} invalid/corrupt file(s)")
    # Sort chronologically
    results.sort(key=lambda x: (x["datetime"], x["filename"]))
    return results
def get_duration(filepath: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(filepath)],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError):
        return 0.0

def validate_dv_file(filepath: Path) -> bool:
    """Check if a DV file is readable by ffprobe (has a valid DV header)."""
    if filepath.stat().st_size < 120000:  # DV frames are ~120KB; smaller = likely corrupt
        return False
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1:nokey=1", str(filepath)],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0 and result.stdout.strip() != ""
    except subprocess.TimeoutExpired:
        return False
def group_by_session(files: list[dict], gap_minutes: int = 30) -> list[list[dict]]:
    """
    Group files into recording sessions.
    Files within `gap_minutes` of each other are considered the same session.
    This handles cases where a recording was paused and resumed.
    """
    if not files:
        return []
    gap = timedelta(minutes=gap_minutes)
    groups = [[files[0]]]
    for f in files[1:]:
        prev = groups[-1][-1]
        # Estimate end time of previous file (get duration if small enough)
        prev_duration = get_duration(prev["path"])
        prev_end = prev["datetime"] + timedelta(seconds=prev_duration)
        if f["datetime"] - prev_end > gap:
            groups.append([f])
        else:
            groups[-1].append(f)
    return groups
def group_by_folder(files: list[dict]) -> list[tuple[str, list[dict]]]:
    """
    Group files by their parent folder, preserving folder sort order.
    Within each folder, files are sorted chronologically.
    Returns list of (folder_name, files) tuples, sorted by folder name.
    This respects the trip chapter structure:
      Europe-Russia-Mongolia-China-2002   → Chapter 1
      Europe-Russia-Mongolia-China-2002-b → Chapter 2
      ...
      Europe-Russia-Mongolia-China-2002-f → Chapter 6
    """
    from collections import defaultdict
    folders = defaultdict(list)
    for f in files:
        folder_name = f["path"].parent.name
        folders[folder_name].append(f)
    # Sort folders: base folder first (no suffix), then -b, -c, -d, -e, -f
    def folder_sort_key(name: str) -> str:
        # Folders ending in -b through -f sort after the base folder
        # Base folder (no letter suffix) should come first
        if re.search(r"-[a-z]$", name):
            return name
        else:
            # Base folder sorts before -b by appending -a
            return name + "-a"
    sorted_folders = sorted(folders.keys(), key=folder_sort_key)
    result = []
    for folder in sorted_folders:
        folder_files = sorted(folders[folder], key=lambda x: (x["datetime"], x["filename"]))
        result.append((folder, folder_files))
    return result
def concatenate_dv_files(files: list[dict], output_path: Path, dry_run: bool = False,
                         crf: int = 18, preset: str = "slow") -> bool:
    """
    Concatenate DV files into a single MP4 using ffmpeg concat demuxer.
    DV files from the same recorder should have consistent format (PAL or NTSC),
    making concat demuxer the fastest and most reliable method.
    Args:
        crf: Quality (0=lossless, 18=visually lossless, 23=default, 28=ok).
             18 is recommended for archival of home videos.
        preset: Encoding speed (ultrafast/fast/medium/slow/veryslow).
                'slow' gives better compression with reasonable speed.
    """
    if dry_run:
        total_mb = sum(f["size_mb"] for f in files)
        print(f"  Would join {len(files)} files ({total_mb:.1f} MB) → {output_path.name}")
        for f in files:
            print(f"    - {f['filename']} ({f['size_mb']:.1f} MB, {f['datetime']})")
        return True
    # Create concat list file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as concat_file:
        for f in files:
            # ffmpeg concat format requires escaping single quotes
            escaped = str(f["path"].resolve()).replace("'", "'\\''")
            concat_file.write(f"file '{escaped}'\n")
        concat_list_path = concat_file.name
    try:
        cmd = [
            "ffmpeg",
            "-y",                       # Overwrite output
            "-f", "concat",             # Concat demuxer
            "-safe", "0",               # Allow absolute paths
            "-i", concat_list_path,     # Input file list
            # Video encoding
            "-c:v", "libx264",          # H.264 codec (universal playback)
            "-crf", str(crf),           # Quality factor
            "-preset", preset,          # Encoding speed/compression tradeoff
            "-pix_fmt", "yuv420p",      # Compatibility with all players
            # Handle interlaced DV content (common in 2002 recordings)
            "-vf", "yadif=mode=0",      # Deinterlace (bob to progressive)
            # Audio encoding
            "-c:a", "aac",              # AAC audio
            "-b:a", "192k",             # Good quality audio
            "-ar", "48000",             # 48kHz (match DV audio)
            # Container
            "-movflags", "+faststart",  # Web/streaming friendly
            str(output_path),
        ]
        print(f"  Encoding: {output_path.name} ({len(files)} files)...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ERROR encoding {output_path.name}:")
            # Show last few lines of ffmpeg output
            for line in result.stderr.strip().split("\n")[-5:]:
                print(f"    {line}")
            return False
        output_size = output_path.stat().st_size / (1024 * 1024)
        input_size = sum(f["size_mb"] for f in files)
        ratio = (output_size / input_size * 100) if input_size > 0 else 0
        print(f"  ✓ Done: {output_path.name} ({output_size:.1f} MB, {ratio:.0f}% of original)")
        return True
    finally:
        os.unlink(concat_list_path)
def main():
    parser = argparse.ArgumentParser(
        description="Join DV video files chronologically into modern MP4 format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/dv --dry-run                    # Preview what will happen
  %(prog)s /path/to/dv --limit 10                    # Test with first 10 files
  %(prog)s /path/to/dv --recursive --per-folder      # One MP4 per trip chapter (recommended)
  %(prog)s /path/to/dv --recursive --single          # Everything into one big file
  %(prog)s /path/to/dv -r --gap 120                  # Session-based, 2-hour gap
        """
    )
    parser.add_argument("source", help="Directory containing .DV files")
    parser.add_argument("-o", "--output", default=None,
                        help="Output directory (default: 'joined' subdir in source)")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Search subdirectories for .DV files")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only first N files (for testing)")
    parser.add_argument("--gap", type=int, default=30,
                        help="Minutes gap to split sessions (default: 30)")
    parser.add_argument("--single", action="store_true",
                        help="Join ALL files into one single output video")
    parser.add_argument("--per-folder", action="store_true",
                        help="One output video per folder (recommended for trip chapters)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without encoding")
    parser.add_argument("--crf", type=int, default=18,
                        help="Video quality: 0=lossless, 18=excellent (default), 23=good, 28=ok")
    parser.add_argument("--preset", default="slow",
                        choices=["ultrafast", "fast", "medium", "slow", "veryslow"],
                        help="Encoding speed (default: slow, better compression)")
    parser.add_argument("--no-deinterlace", action="store_true",
                        help="Skip deinterlacing (if source is already progressive)")
    parser.add_argument("--verbose", action="store_true",
                        help="Show detailed info about file discovery and validation")
    args = parser.parse_args()
    # Find files
    print(f"\nScanning for .DV files in: {args.source}")
    if args.recursive:
        print("  (including subdirectories)")
    files = get_dv_files(args.source, recursive=args.recursive, verbose=args.verbose)
    if not files:
        print("No valid .DV files found! (files may be corrupt or missing DV headers)")
        print("  Tip: Check that the source folder contains actual DV recordings,")
        print("       not iMovie project references or placeholder files.")
        sys.exit(1)
    print(f"\nFound {len(files)} valid DV files")
    # Apply limit for testing
    if args.limit:
        files = files[:args.limit]
        print(f"  (limited to first {args.limit} for testing)")
    # Show date range
    first_dt = files[0]["datetime"]
    last_dt = files[-1]["datetime"]
    total_mb = sum(f["size_mb"] for f in files)
    print(f"  Date range: {first_dt.strftime('%Y-%m-%d %H:%M')} → {last_dt.strftime('%Y-%m-%d %H:%M')}")
    print(f"  Total size: {total_mb:.1f} MB ({total_mb/1024:.2f} GB)")
    # Setup output directory
    output_dir = Path(args.output) if args.output else Path(args.source) / "joined"
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Output dir: {output_dir}")
    # Group and process
    if args.single:
        groups = [("all", files)]
        print(f"\nJoining all {len(files)} files into a single video")
    elif args.per_folder and args.recursive:
        folder_groups = group_by_folder(files)
        groups = folder_groups
        print(f"\nGrouped by folder into {len(groups)} chapter(s):")
        for folder_name, folder_files in groups:
            total = sum(f["size_mb"] for f in folder_files)
            print(f"  {folder_name}: {len(folder_files)} files ({total:.1f} MB)")
    else:
        session_groups = group_by_session(files, gap_minutes=args.gap)
        groups = [(f"session_{i:03d}", g) for i, g in enumerate(session_groups, 1)]
        print(f"\nGrouped into {len(groups)} session(s) (gap threshold: {args.gap} min)")
    print("=" * 60)
    success = 0
    failed = 0
    for i, (group_name, group_files) in enumerate(groups, 1):
        start_dt = group_files[0]["datetime"]
        end_dt = group_files[-1]["datetime"]
        if args.single:
            output_name = f"all_recordings_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}.mp4"
        elif args.per_folder:
            # Clean folder name for use as filename
            safe_name = re.sub(r"[^\w\-]", "_", group_name)
            output_name = f"{safe_name}.mp4"
        elif len(groups) == 1:
            output_name = f"recording_{start_dt.strftime('%Y%m%d_%H%M%S')}.mp4"
        else:
            output_name = f"{group_name}_{start_dt.strftime('%Y%m%d_%H%M%S')}.mp4"
        output_path = output_dir / output_name
        print(f"\n[{i}/{len(groups)}] {group_name}: {start_dt.strftime('%Y-%m-%d %H:%M')} "
              f"→ {end_dt.strftime('%Y-%m-%d %H:%M')} ({len(group_files)} files)")
        if concatenate_dv_files(group_files, output_path, dry_run=args.dry_run,
                                crf=args.crf, preset=args.preset):
            success += 1
        else:
            failed += 1
    # Summary
    print("\n" + "=" * 60)
    print(f"Complete: {success} session(s) processed, {failed} failed")
    if args.dry_run:
        print("\n** This was a DRY RUN - no files were created **")
        print(f"** Re-run without --dry-run to encode **")
    if not args.dry_run and success > 0:
        print(f"\nOutput files in: {output_dir}")
if __name__ == "__main__":
    main()
