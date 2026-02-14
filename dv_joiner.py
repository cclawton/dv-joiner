#!/usr/bin/env python3
"""
DV Joiner — Join .DV video files into MP4 format.

Designed for archiving MiniDV/Digital8 footage. Scans directories for .dv files,
sorts them chronologically by filename timestamps, and concatenates them into
H.264/AAC MP4 files using ffmpeg.

Handles filenames like: clip-2002-03-13 08;37;36.dv
(semicolons as time separators from the original recorder)
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class DVFile:
    """A discovered .dv file with its parsed timestamp."""
    path: Path
    timestamp: datetime | None
    folder: Path

    def __lt__(self, other: "DVFile") -> bool:
        if self.timestamp and other.timestamp:
            return self.timestamp < other.timestamp
        if self.timestamp:
            return True
        if other.timestamp:
            return False
        return str(self.path) < str(other.path)


@dataclass
class EncodingJob:
    """A group of DV files to be joined into one MP4."""
    name: str
    files: list[DVFile] = field(default_factory=list)
    output_path: Path | None = None


# Regex for filenames like: clip-2002-03-13 08;37;36.dv
TIMESTAMP_PATTERN = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2});(\d{2});(\d{2})"
)

# Alternate pattern with colons or hyphens as time separators
TIMESTAMP_PATTERN_ALT = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2})[:.-](\d{2})[:.-](\d{2})"
)


def parse_timestamp(filename: str) -> datetime | None:
    """Extract a datetime from a DV filename.

    Handles formats like:
        clip-2002-03-13 08;37;36.dv
        clip-2002-03-13 08:37:36.dv
    """
    for pattern in (TIMESTAMP_PATTERN, TIMESTAMP_PATTERN_ALT):
        match = pattern.search(filename)
        if match:
            year, month, day, hour, minute, second = (int(g) for g in match.groups())
            try:
                return datetime(year, month, day, hour, minute, second)
            except ValueError:
                continue
    return None


def folder_sort_key(folder: Path) -> tuple[str, str]:
    """Sort folders so base folder comes before suffixed ones.

    Europe-Russia-Mongolia-China-2002     → ('Europe-Russia-Mongolia-China-2002', '')
    Europe-Russia-Mongolia-China-2002-b   → ('Europe-Russia-Mongolia-China-2002', 'b')
    Europe-Russia-Mongolia-China-2002-f   → ('Europe-Russia-Mongolia-China-2002', 'f')
    """
    name = folder.name
    # Check if the folder name ends with a single letter suffix like -b, -c, etc.
    match = re.match(r"^(.+)-([b-z])$", name, re.IGNORECASE)
    if match:
        return (match.group(1), match.group(2).lower())
    return (name, "")


def discover_dv_files(
    root: Path, recursive: bool = False
) -> dict[Path, list[DVFile]]:
    """Find all .dv files under root, grouped by containing folder."""
    files_by_folder: dict[Path, list[DVFile]] = {}

    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root):
            folder = Path(dirpath)
            for fname in filenames:
                if fname.lower().endswith(".dv"):
                    fpath = folder / fname
                    ts = parse_timestamp(fname)
                    dv = DVFile(path=fpath, timestamp=ts, folder=folder)
                    files_by_folder.setdefault(folder, []).append(dv)
    else:
        for item in root.iterdir():
            if item.is_file() and item.suffix.lower() == ".dv":
                ts = parse_timestamp(item.name)
                dv = DVFile(path=item, timestamp=ts, folder=root)
                files_by_folder.setdefault(root, []).append(dv)

    # Sort files chronologically within each folder
    for folder in files_by_folder:
        files_by_folder[folder].sort()

    return files_by_folder


def build_jobs(
    files_by_folder: dict[Path, list[DVFile]],
    mode: str,
    gap_minutes: int = 30,
    limit: int | None = None,
    output_dir: Path | None = None,
) -> list[EncodingJob]:
    """Build encoding jobs from discovered files.

    Modes:
        per-folder: One job per source folder
        single: All files in one job
        gap: Split into sessions based on time gaps
    """
    # Sort folders using the custom sort key
    sorted_folders = sorted(files_by_folder.keys(), key=folder_sort_key)

    jobs: list[EncodingJob] = []

    match mode:
        case "per-folder":
            for folder in sorted_folders:
                folder_files = files_by_folder[folder]
                if limit:
                    folder_files = folder_files[:limit]
                if not folder_files:
                    continue
                job = EncodingJob(name=folder.name, files=folder_files)
                jobs.append(job)

        case "single":
            all_files: list[DVFile] = []
            for folder in sorted_folders:
                all_files.extend(files_by_folder[folder])
            all_files.sort()
            if limit:
                all_files = all_files[:limit]
            if all_files:
                jobs.append(EncodingJob(name="joined_all", files=all_files))

        case "gap":
            all_files = []
            for folder in sorted_folders:
                all_files.extend(files_by_folder[folder])
            all_files.sort()
            if limit:
                all_files = all_files[:limit]

            if not all_files:
                return jobs

            current_job = EncodingJob(name="session_001", files=[all_files[0]])
            session_num = 1

            for prev, curr in zip(all_files, all_files[1:]):
                if (
                    prev.timestamp
                    and curr.timestamp
                    and (curr.timestamp - prev.timestamp).total_seconds()
                    > gap_minutes * 60
                ):
                    jobs.append(current_job)
                    session_num += 1
                    current_job = EncodingJob(
                        name=f"session_{session_num:03d}", files=[curr]
                    )
                else:
                    current_job.files.append(curr)

            jobs.append(current_job)

    # Set output paths
    if output_dir is None:
        # Default: use a "joined" subdirectory relative to the first file
        if jobs and jobs[0].files:
            first_root = jobs[0].files[0].folder
            # Walk up to find the common parent
            parents = [f.folder for job in jobs for f in job.files]
            output_dir = Path(os.path.commonpath(parents)) / "joined"
        else:
            output_dir = Path.cwd() / "joined"

    for job in jobs:
        safe_name = re.sub(r"[^\w\-.]", "_", job.name)
        job.output_path = output_dir / f"{safe_name}.mp4"

    return jobs


def print_dry_run(jobs: list[EncodingJob]) -> None:
    """Display what would happen without actually encoding."""
    total_files = sum(len(j.files) for j in jobs)
    print(f"\n{'='*60}")
    print(f"DRY RUN — {len(jobs)} job(s), {total_files} file(s) total")
    print(f"{'='*60}\n")

    for i, job in enumerate(jobs, 1):
        print(f"Job {i}: {job.name}")
        print(f"  Output: {job.output_path}")
        print(f"  Files:  {len(job.files)}")

        # Estimate size (DV is ~3.6 MB/sec, ~13 GB/hour)
        # Each DV file's actual size could be checked, but for dry run
        # we just count files
        total_bytes = 0
        for dv in job.files:
            try:
                total_bytes += dv.path.stat().st_size
            except OSError:
                pass

        if total_bytes > 0:
            gb = total_bytes / (1024**3)
            hours = total_bytes / (3.6 * 1024 * 1024) / 3600
            print(f"  Source size: {gb:.1f} GB (~{hours:.1f} hours of footage)")

        if job.files:
            first = job.files[0]
            last = job.files[-1]
            ts_first = first.timestamp.strftime("%Y-%m-%d %H:%M:%S") if first.timestamp else "unknown"
            ts_last = last.timestamp.strftime("%Y-%m-%d %H:%M:%S") if last.timestamp else "unknown"
            print(f"  Time range: {ts_first} → {ts_last}")

        # Show first few and last few files
        show_count = 3
        if len(job.files) <= show_count * 2:
            for dv in job.files:
                ts = dv.timestamp.strftime("%Y-%m-%d %H:%M:%S") if dv.timestamp else "no timestamp"
                print(f"    {dv.path.name}  ({ts})")
        else:
            for dv in job.files[:show_count]:
                ts = dv.timestamp.strftime("%Y-%m-%d %H:%M:%S") if dv.timestamp else "no timestamp"
                print(f"    {dv.path.name}  ({ts})")
            print(f"    ... {len(job.files) - show_count * 2} more files ...")
            for dv in job.files[-show_count:]:
                ts = dv.timestamp.strftime("%Y-%m-%d %H:%M:%S") if dv.timestamp else "no timestamp"
                print(f"    {dv.path.name}  ({ts})")
        print()


def encode_job(job: EncodingJob, crf: int, preset: str) -> bool:
    """Encode a single job using ffmpeg concat demuxer.

    Returns True on success, False on failure.
    """
    if not job.files or not job.output_path:
        return False

    # Create output directory
    job.output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build concat file list
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="dvjoin_"
    ) as concat_file:
        for dv in job.files:
            # ffmpeg concat demuxer requires escaped single quotes in paths
            escaped = str(dv.path.resolve()).replace("'", "'\\''")
            concat_file.write(f"file '{escaped}'\n")
        concat_path = concat_file.name

    try:
        cmd = [
            "ffmpeg",
            "-y",  # overwrite output
            "-f", "concat",
            "-safe", "0",
            "-i", concat_path,
            # Video: deinterlace and encode
            "-vf", "yadif=mode=0",  # mode 0: one frame per field-pair
            "-c:v", "libx264",
            "-crf", str(crf),
            "-preset", preset,
            "-pix_fmt", "yuv420p",
            # Audio: AAC
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            # Container options
            "-movflags", "+faststart",
            str(job.output_path),
        ]

        print(f"\nEncoding: {job.name}")
        print(f"  {len(job.files)} files → {job.output_path}")
        print(f"  Settings: CRF {crf}, preset {preset}")
        print(f"  Command: {' '.join(cmd[:6])} ... {cmd[-1]}")
        print()

        result = subprocess.run(
            cmd,
            capture_output=False,
            text=True,
        )

        if result.returncode == 0:
            size = job.output_path.stat().st_size / (1024**2)
            print(f"\n  Done: {job.output_path.name} ({size:.0f} MB)")
            return True
        else:
            print(f"\n  ERROR: ffmpeg exited with code {result.returncode}")
            return False

    finally:
        os.unlink(concat_path)


def check_ffmpeg() -> bool:
    """Verify ffmpeg is available."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Join .DV video files into MP4 format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s /path/to/folder --recursive --per-folder --dry-run
  %(prog)s /path/to/folder --recursive --per-folder --limit 10 --preset fast
  %(prog)s /path/to/folder --recursive --per-folder
        """,
    )

    parser.add_argument(
        "source",
        type=Path,
        help="Source directory containing .dv files",
    )

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--per-folder",
        action="store_const",
        const="per-folder",
        dest="mode",
        help="One MP4 per source folder/chapter (recommended)",
    )
    mode_group.add_argument(
        "--single",
        action="store_const",
        const="single",
        dest="mode",
        help="Join everything into one MP4",
    )

    parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Search subdirectories for .dv files",
    )
    parser.add_argument(
        "--gap",
        type=int,
        default=30,
        metavar="N",
        help="Split into sessions if gap exceeds N minutes (default: 30)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process only first N files per job (for testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would happen without encoding",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output directory (default: joined/ under source)",
    )

    # Encoding options
    parser.add_argument(
        "--crf",
        type=int,
        default=18,
        metavar="N",
        help="Quality: 0=lossless, 18=excellent (default), 23=good, 28=ok",
    )
    parser.add_argument(
        "--preset",
        default="slow",
        choices=["ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow"],
        help="Encoding speed/quality tradeoff (default: slow)",
    )

    args = parser.parse_args()

    # Validate source directory
    if not args.source.is_dir():
        print(f"Error: '{args.source}' is not a directory", file=sys.stderr)
        return 1

    # Default mode
    if args.mode is None:
        args.mode = "per-folder" if args.recursive else "single"

    # Check ffmpeg (unless dry run)
    if not args.dry_run and not check_ffmpeg():
        print(
            "Error: ffmpeg not found. Install it with:\n"
            "  macOS:  brew install ffmpeg\n"
            "  Linux:  sudo apt install ffmpeg",
            file=sys.stderr,
        )
        return 1

    # Discover files
    print(f"Scanning '{args.source}' for .dv files...")
    files_by_folder = discover_dv_files(args.source, recursive=args.recursive)

    total_files = sum(len(v) for v in files_by_folder.values())
    if total_files == 0:
        print("No .dv files found.", file=sys.stderr)
        return 1

    print(f"Found {total_files} .dv file(s) in {len(files_by_folder)} folder(s)")

    # Handle gap-based splitting
    mode = args.mode
    if args.gap != 30 and mode != "single":
        mode = "gap"

    # Build jobs
    output_dir = args.output or (args.source / "joined")
    jobs = build_jobs(
        files_by_folder,
        mode=mode,
        gap_minutes=args.gap,
        limit=args.limit,
        output_dir=output_dir,
    )

    if not jobs:
        print("No encoding jobs to run.", file=sys.stderr)
        return 1

    # Dry run
    if args.dry_run:
        print_dry_run(jobs)
        return 0

    # Encode
    print(f"\nStarting {len(jobs)} encoding job(s)...")
    successes = 0
    failures = 0

    for job in jobs:
        if encode_job(job, crf=args.crf, preset=args.preset):
            successes += 1
        else:
            failures += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"Complete: {successes} succeeded, {failures} failed")
    if successes > 0:
        print(f"Output directory: {output_dir}")
    print(f"{'='*60}")

    return 1 if failures > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
