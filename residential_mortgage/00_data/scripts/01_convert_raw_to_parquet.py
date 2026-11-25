"""Convert Fannie Mae raw quarterly CSV performance files to compressed Parquet files.

Features:
- Single quarter: e.g. 2005Q1 (or 2005q1)
- Quarter range: e.g. 2000Q1 to 2008Q4
- All quarters: all (starts from oldest 2000Q1 to 2025Q4)
- Option --record-only: write or back-fill conversion records without rewriting Parquet files
- Writes YYYYQn.conversion.json with line and byte counts, timings, and DuckDB version
- Skips quarters where both .parquet and .conversion.json exist and row counts match
- ASCII-only terminal output: OK, ..., FAIL. Live updates only when running in a terminal.
"""

import argparse
import json
import os
import re
import shutil
import sys
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

import duckdb

# Reconfigure stdout for safe encoding if supported
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Import 113 layout field definitions & central settings
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent
PACKAGE_ROOT = DATA_DIR.parent
REPO_ROOT = PACKAGE_ROOT.parent

for _p in (str(SCRIPT_DIR), str(PACKAGE_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _settings import config  # noqa: E402
from field_map import FIELDS  # noqa: E402

_PATHS = config.paths()
_COMPUTE = config.load("compute")

DEFAULT_ZIP = _PATHS["fannie_mae_zip"]
SCRATCH_DIR = _PATHS["scratch_dir"]
PARQUET_DIR = _PATHS["parquet_dir"]

CHUNK_BYTES = int(_COMPUTE["io"]["zip_chunk_mb"]) * 1024 * 1024
CONVERT_MEM_LIMIT = str(_COMPUTE["duckdb"]["convert_memory_limit"])


# =======================================================================================
# Terminal progress and text formatting
# =======================================================================================

def format_bytes(num_bytes: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} PB"


def format_seconds(seconds: float) -> str:
    seconds = int(max(0, seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def print_in_place(line: str):
    """Print an updating line in place if in an interactive terminal."""
    if not sys.stdout.isatty():
        return
    cols = shutil.get_terminal_size((80, 20)).columns
    safe_line = line[: cols - 1].ljust(cols - 1)
    sys.stdout.write(f"\r{safe_line}")
    sys.stdout.flush()


def print_final(line: str):
    """Print a completed line and advance cursor."""
    if sys.stdout.isatty():
        cols = shutil.get_terminal_size((80, 20)).columns
        safe_line = line[: cols - 1].ljust(cols - 1)
        sys.stdout.write(f"\r{safe_line}\n")
    else:
        sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


class ExtractionProgressBar:
    """Progress tracker for extracting CSV files from the raw zip."""

    def __init__(self, total_bytes: int, prefix: str):
        self.total_bytes = total_bytes
        self.prefix = prefix
        self.start_time = time.perf_counter()
        self.last_update = 0.0

    def update(self, current_bytes: int):
        now = time.perf_counter()
        if now - self.last_update < 0.1 and current_bytes < self.total_bytes:
            return
        self.last_update = now
        elapsed = now - self.start_time
        speed = current_bytes / elapsed if elapsed > 0 else 0
        pct = (current_bytes / self.total_bytes) * 100 if self.total_bytes > 0 else 0
        rem_bytes = max(0, self.total_bytes - current_bytes)
        eta_sec = rem_bytes / speed if speed > 0 else 0

        bar_len = 16
        filled = int(bar_len * current_bytes // self.total_bytes) if self.total_bytes > 0 else 0
        bar = "=" * filled + (">" if filled < bar_len else "")
        bar = bar.ljust(bar_len)

        text = (
            f"  {self.prefix}: [{bar}] {pct:5.1f}% "
            f"({format_bytes(current_bytes)}/{format_bytes(self.total_bytes)}) "
            f"| {speed / (1024 * 1024):5.1f} MB/s | ETA: {format_seconds(eta_sec)}"
        )
        print_in_place(text)

    def finish(self, lines: int):
        elapsed = time.perf_counter() - self.start_time
        speed = self.total_bytes / elapsed if elapsed > 0 else 0
        text = (
            f"  OK [{self.prefix}]: {format_bytes(self.total_bytes)} extracted ({lines:,} lines) "
            f"in {format_seconds(elapsed)} ({speed / (1024 * 1024):.1f} MB/s)"
        )
        print_final(text)


class StreamingProgressBar:
    """Progress tracker for streaming CSV into Parquet."""

    def __init__(self, con, prefix: str):
        self.con = con
        self.prefix = prefix
        self.start_time = time.perf_counter()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def _run(self):
        bar_len = 16
        while not self._stop_event.is_set():
            p = -1.0
            try:
                p = self.con.query_progress()
            except Exception:
                pass
            elapsed = time.perf_counter() - self.start_time
            if p >= 0:
                p_clamped = min(100.0, max(0.0, p))
                filled = int(bar_len * p_clamped // 100)
                bar = "=" * filled + (">" if filled < bar_len else "")
                bar = bar.ljust(bar_len)
                eta_sec = (elapsed / (p_clamped / 100.0)) - elapsed if p_clamped > 0 else 0
                text = (
                    f"  {self.prefix}: [{bar}] {p_clamped:5.1f}% "
                    f"| Elapsed: {format_seconds(elapsed)} | ETA: {format_seconds(eta_sec)}"
                )
            else:
                text = f"  {self.prefix}: processing... | Elapsed: {format_seconds(elapsed)}"
            print_in_place(text)
            time.sleep(0.2)

    def finish(self):
        if not self._stop_event.is_set():
            self._stop_event.set()
            self._thread.join()
            elapsed = time.perf_counter() - self.start_time
            text = f"  OK [{self.prefix}] in {format_seconds(elapsed)}"
            print_final(text)


class OverallProgressTracker:
    """Tracks overall multi-quarter progress and batch ETA."""

    def __init__(self, total_quarters: int):
        self.total = total_quarters
        self.completed = 0
        self.start_time = time.perf_counter()
        self.durations = []

    def record_quarter(self, duration: float):
        self.completed += 1
        self.durations.append(duration)

    def print_status(self):
        if self.total <= 1:
            return
        elapsed = time.perf_counter() - self.start_time
        avg_per_q = sum(self.durations) / len(self.durations) if self.durations else 0
        remaining_q = self.total - self.completed
        eta_sec = remaining_q * avg_per_q
        pct = (self.completed / self.total) * 100
        print(
            f"  >>> BATCH PROGRESS: [{self.completed}/{self.total} Quarters | {pct:4.1f}%] "
            f"| Elapsed: {format_seconds(elapsed)} | Batch ETA: {format_seconds(eta_sec)}\n"
        )


# =======================================================================================
# Core extraction, streaming, and validation logic
# =======================================================================================

def parse_quarter(text: str) -> tuple[int, int, str]:
    """Parse '2005Q1', '2005q1', or '2005-Q1' into (year, quarter_num, '2005Q1')."""
    cleaned = text.strip().upper().replace("-", "")
    match = re.fullmatch(r"(\d{4})Q([1-4])", cleaned)
    if not match:
        sys.exit(f"Error: Invalid quarter format '{text}'. Expected YYYYQn (e.g. 2005Q1).")
    year, q = int(match.group(1)), int(match.group(2))
    return year, q, f"{year}Q{q}"


def list_quarters_in_zip(zip_path: Path) -> list[str]:
    """Inspect the zip file and return all quarters in sorted chronological order."""
    if not zip_path.exists():
        sys.exit(f"Error: Raw zip file not found at: {zip_path}")
    quarters = []
    pattern = re.compile(r"^(\d{4})Q([1-4])\.csv$", re.IGNORECASE)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            filename = Path(name).name
            match = pattern.match(filename)
            if match:
                year, q = int(match.group(1)), int(match.group(2))
                quarters.append((year, q, f"{year}Q{q}"))
    quarters.sort()
    return [q[2] for q in quarters]


def find_zip_info(zf: zipfile.ZipFile, quarter: str):
    """Find the zipfile.ZipInfo entry for a given quarter."""
    target_name = f"{quarter}.csv".upper()
    for item in zf.infolist():
        if Path(item.filename).name.upper() == target_name:
            return item
    return None


def get_parquet_row_count(file_path: Path) -> int:
    """Read exact row count from a Parquet file."""
    if not file_path.exists() or file_path.stat().st_size == 0:
        return 0
    con = None
    try:
        con = duckdb.connect()
        path_str = str(file_path).replace("\\", "/")
        return con.execute("SELECT count(*) FROM read_parquet(?)", [path_str]).fetchone()[0]
    except Exception:
        return 0
    finally:
        if con:
            con.close()


def is_quarter_complete(final_parquet: Path, final_json: Path) -> tuple[bool, int]:
    """Check if both .parquet and .conversion.json exist and row counts match."""
    if not final_parquet.exists() or not final_json.exists():
        return False, 0
    try:
        with open(final_json, "r", encoding="utf-8") as f:
            rec = json.load(f)
        parquet_rows = get_parquet_row_count(final_parquet)
        if parquet_rows > 0 and rec.get("parquet_rows") == parquet_rows:
            return True, parquet_rows
        return False, 0
    except Exception:
        return False, 0


def write_conversion_record(target_json: Path, record: dict):
    """Write conversion record atomically via a temporary file."""
    tmp_json = target_json.with_suffix(".json.tmp")
    with open(tmp_json, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    if target_json.exists():
        target_json.unlink()
    tmp_json.rename(target_json)


def extract_quarter_csv(zf: zipfile.ZipFile, zip_info: zipfile.ZipInfo, target_csv: Path, quarter: str) -> tuple[int, float]:
    """Extract CSV chunk by chunk, counting line breaks and updating the progress bar."""
    lines = 0
    bytes_read = 0
    last_byte = b"\n"
    start_time = time.perf_counter()

    pbar = ExtractionProgressBar(zip_info.file_size, f"{quarter} 1/3 Extract CSV")

    with zf.open(zip_info) as source, open(target_csv, "wb") as out:
        while True:
            chunk = source.read(CHUNK_BYTES)
            if not chunk:
                break
            out.write(chunk)
            bytes_read += len(chunk)
            lines += chunk.count(b"\n")
            last_byte = chunk[-1:]
            pbar.update(bytes_read)

    if last_byte != b"\n":
        lines += 1

    pbar.finish(lines)
    return lines, time.perf_counter() - start_time


def stream_csv_to_parquet(csv_path: Path, parquet_tmp_path: Path, quarter: str) -> float:
    """Use DuckDB to stream raw CSV directly into Parquet with ZSTD compression."""
    columns_sql = ", ".join(f"'{f.column}': 'VARCHAR'" for f in FIELDS)
    csv_str = str(csv_path).replace("\\", "/")
    tmp_str = str(parquet_tmp_path).replace("\\", "/")

    sql = f"""
    COPY (
        SELECT * FROM read_csv(
            '{csv_str}',
            delim='|',
            header=false,
            quote='',
            escape='',
            columns={{{columns_sql}}},
            strict_mode=true
        )
    ) TO '{tmp_str}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """

    con = None
    t0 = time.perf_counter()
    try:
        con = duckdb.connect()
        con.execute(f"PRAGMA memory_limit = '{CONVERT_MEM_LIMIT}';")
        con.execute("SET enable_progress_bar = true;")
        con.execute("SET enable_progress_bar_print = false;")

        pbar = StreamingProgressBar(con, f"{quarter} 2/3 Stream to Parquet")
        pbar.start()
        try:
            con.execute(sql)
        finally:
            pbar.finish()
    finally:
        if con:
            con.close()
    return time.perf_counter() - t0


def verify_and_commit(parquet_tmp: Path, final_parquet: Path, expected_lines: int, quarter: str) -> int:
    """Verify Parquet row count matches raw CSV lines, then atomically rename."""
    prefix = f"{quarter} 3/3 Validate rows"
    print_in_place(f"  ... [{prefix}] Checking Parquet row count...")

    actual_rows = get_parquet_row_count(parquet_tmp)
    if actual_rows != expected_lines:
        raise ValueError(
            f"Validation failed for {quarter}: raw CSV had {expected_lines:,} lines, "
            f"but Parquet has {actual_rows:,} rows."
        )

    if final_parquet.exists():
        final_parquet.unlink()
    parquet_tmp.rename(final_parquet)

    print_final(f"  OK [{prefix}]: Parquet rows ({actual_rows:,}) == Raw lines ({expected_lines:,})")
    return actual_rows


def process_record_only(quarter: str, zip_path: Path, parquet_dir: Path):
    """Back-fill YYYYQn.conversion.json by streaming zip member without extracting to disk.

    Returns True when the record is written or already complete, False when there is
    no Parquet file to record, and None when the check fails (no record is written).
    """
    final_parquet = parquet_dir / f"{quarter}.parquet"
    final_json = parquet_dir / f"{quarter}.conversion.json"

    if not final_parquet.exists():
        print(f"[{quarter}] SKIP: Parquet file does not exist ({final_parquet.name})")
        return False

    is_valid, existing_rows = is_quarter_complete(final_parquet, final_json)
    if is_valid:
        print(f"[{quarter}] SKIP: Conversion record already complete ({existing_rows:,} rows)")
        return True

    print(f"[{quarter}] Checking raw lines against Parquet rows...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        info = find_zip_info(zf, quarter)
        if not info:
            print(f"[{quarter}] FAIL: Quarter file not found in zip")
            return None

        start_t = time.perf_counter()
        raw_lines = 0
        last_byte = b"\n"
        with zf.open(info) as src:
            while True:
                chunk = src.read(CHUNK_BYTES)
                if not chunk:
                    break
                raw_lines += chunk.count(b"\n")
                last_byte = chunk[-1:]
        if last_byte != b"\n":
            raw_lines += 1
        count_sec = time.perf_counter() - start_t

    parquet_rows = get_parquet_row_count(final_parquet)
    parquet_bytes = final_parquet.stat().st_size
    raw_csv_bytes = info.file_size

    if raw_lines != parquet_rows:
        print(f"[{quarter}] FAIL: Raw lines ({raw_lines:,}) != Parquet rows ({parquet_rows:,})")
        return None

    # Back-filled record: the conversion times were not kept, so they are left empty.
    # count_seconds is the time taken to count the raw lines from the zip.
    record = {
        "quarter": quarter,
        "raw_csv_bytes": raw_csv_bytes,
        "raw_lines": raw_lines,
        "parquet_rows": parquet_rows,
        "parquet_bytes": parquet_bytes,
        "extract_seconds": None,
        "convert_seconds": None,
        "count_seconds": round(count_sec, 2),
        "converted_at": None,
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duckdb_version": duckdb.__version__,
    }
    write_conversion_record(final_json, record)
    print(f"[{quarter}] OK: Record written ({parquet_rows:,} rows)")
    return True


def process_quarter(quarter: str, zip_path: Path, scratch_dir: Path, parquet_dir: Path) -> bool:
    """Execute the full pipeline for one quarter. Returns True if converted, False if skipped."""
    final_parquet = parquet_dir / f"{quarter}.parquet"
    final_json = parquet_dir / f"{quarter}.conversion.json"
    parquet_tmp = parquet_dir / f"{quarter}.parquet.tmp"
    target_csv = scratch_dir / f"{quarter}.csv"

    is_valid, existing_rows = is_quarter_complete(final_parquet, final_json)
    if is_valid:
        print(f"[{quarter}] SKIP: Already complete ({existing_rows:,} rows in {final_parquet.name})")
        return False

    if final_parquet.exists() and not final_json.exists():
        # A Parquet file from an earlier run, without a conversion record. Count the raw
        # lines from the zip and write the record instead of converting again. Convert
        # again only if the counts do not match.
        result = process_record_only(quarter, zip_path, parquet_dir)
        if result:
            return False
        print(f"[{quarter}] Parquet file does not match the raw file. Converting again.")
        final_parquet.unlink()
    elif final_parquet.exists():
        final_parquet.unlink()
    if parquet_tmp.exists():
        parquet_tmp.unlink()
    if target_csv.exists():
        target_csv.unlink()

    q_start = time.perf_counter()
    print(f"\n[{quarter}] START: Processing raw quarter...")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            info = find_zip_info(zf, quarter)
            if not info:
                raise FileNotFoundError(f"Quarter '{quarter}.csv' not found inside {zip_path.name}")

            expected_lines, extract_sec = extract_quarter_csv(zf, info, target_csv, quarter)
            convert_sec = stream_csv_to_parquet(target_csv, parquet_tmp, quarter)
            rows = verify_and_commit(parquet_tmp, final_parquet, expected_lines, quarter)

            raw_size = info.file_size
            parquet_size = final_parquet.stat().st_size
            comp_ratio = raw_size / parquet_size if parquet_size > 0 else 0
            q_time = time.perf_counter() - q_start

            record = {
                "quarter": quarter,
                "raw_csv_bytes": raw_size,
                "raw_lines": rows,
                "parquet_rows": rows,
                "parquet_bytes": parquet_size,
                "extract_seconds": round(extract_sec, 2),
                "convert_seconds": round(convert_sec, 2),
                "converted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "duckdb_version": duckdb.__version__,
            }
            write_conversion_record(final_json, record)

            print(
                f"[{quarter}] COMPLETE in {format_seconds(q_time)}: {rows:,} rows | "
                f"Raw: {format_bytes(raw_size)} -> Parquet: {format_bytes(parquet_size)} "
                f"({comp_ratio:.1f}x compression)"
            )
            return True

    finally:
        if target_csv.exists():
            target_csv.unlink()
        if parquet_tmp.exists():
            parquet_tmp.unlink()


# =======================================================================================
# CLI and main entry point
# =======================================================================================

def build_quarter_list(args, all_available: list[str]) -> list[str]:
    """Resolve CLI arguments into an ordered list of quarters to process."""
    if args.all or (args.target and args.target[0].lower() == "all"):
        return all_available

    if args.quarter:
        _, _, q_clean = parse_quarter(args.quarter)
        return [q_clean]

    if args.from_quarter and args.to_quarter:
        start_y, start_q, _ = parse_quarter(args.from_quarter)
        end_y, end_q, _ = parse_quarter(args.to_quarter)
        if (start_y, start_q) > (end_y, end_q):
            sys.exit(f"Error: --from ({args.from_quarter}) is after --to ({args.to_quarter}).")
        return [q for q in all_available if parse_quarter(q)[:2] >= (start_y, start_q) and parse_quarter(q)[:2] <= (end_y, end_q)]

    if args.target:
        if len(args.target) == 1:
            _, _, q_clean = parse_quarter(args.target[0])
            return [q_clean]
        elif len(args.target) == 2:
            start_y, start_q, _ = parse_quarter(args.target[0])
            end_y, end_q, _ = parse_quarter(args.target[1])
            if (start_y, start_q) > (end_y, end_q):
                sys.exit(f"Error: Start quarter ({args.target[0]}) is after end quarter ({args.target[1]}).")
            return [q for q in all_available if parse_quarter(q)[:2] >= (start_y, start_q) and parse_quarter(q)[:2] <= (end_y, end_q)]
        else:
            sys.exit(f"Error: Too many positional arguments ({len(args.target)}). Expected at most 2.")

    sys.exit(
        "Error: Please specify quarters to process.\n"
        "Examples:\n"
        "  python residential_mortgage/00_data/scripts/01_convert_raw_to_parquet.py 2005Q1\n"
        "  python residential_mortgage/00_data/scripts/01_convert_raw_to_parquet.py 2000Q1 2008Q4\n"
        "  python residential_mortgage/00_data/scripts/01_convert_raw_to_parquet.py all\n"
        "  python residential_mortgage/00_data/scripts/01_convert_raw_to_parquet.py all --record-only\n"
        "  python residential_mortgage/00_data/scripts/01_convert_raw_to_parquet.py --quarter 2005Q1\n"
        "  python residential_mortgage/00_data/scripts/01_convert_raw_to_parquet.py --from 2000Q1 --to 2008Q4\n"
        "  python residential_mortgage/00_data/scripts/01_convert_raw_to_parquet.py --all"
    )


def main():
    parser = argparse.ArgumentParser(description="Convert Fannie Mae raw CSV quarters into compressed Parquet files.")
    parser.add_argument("target", nargs="*", help="Positional quarter specification: '2005Q1', '2000Q1 2008Q4', or 'all'")
    parser.add_argument("--quarter", help="Single quarter (e.g. 2005Q1 or 2005q1)")
    parser.add_argument("--from", dest="from_quarter", help="Start quarter (e.g. 2000Q1)")
    parser.add_argument("--to", dest="to_quarter", help="End quarter (e.g. 2008Q4)")
    parser.add_argument("--all", action="store_true", help="Process all quarters starting from oldest")
    parser.add_argument("--record-only", action="store_true", help="Write or back-fill conversion records without rewriting Parquet")
    parser.add_argument("--zip", default=str(DEFAULT_ZIP), help="Path to Performance_All.zip")
    parser.add_argument("--scratch", default=str(SCRATCH_DIR), help="Temporary scratch directory for CSV unzipping")
    parser.add_argument("--out", default=str(PARQUET_DIR), help="Destination directory for raw parquet files")

    args = parser.parse_args()

    zip_path = Path(args.zip).resolve()
    scratch_dir = Path(args.scratch).resolve()
    parquet_dir = Path(args.out).resolve()

    scratch_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)

    all_available = list_quarters_in_zip(zip_path)
    quarters_to_run = build_quarter_list(args, all_available)

    print("=" * 80)
    print("Fannie Mae Raw CSV -> Parquet Conversion")
    print(f"Source zip:  {zip_path}")
    print(f"Scratch dir: {scratch_dir}")
    print(f"Parquet dir: {parquet_dir}")
    print(f"Mode:        {'Record only (back-fill)' if args.record_only else 'Extract and convert'}")
    print(f"Quarters:    {len(quarters_to_run)} queued ({quarters_to_run[0]} to {quarters_to_run[-1]})")
    print("=" * 80)

    if args.record_only:
        failed = []
        for quarter in quarters_to_run:
            if process_record_only(quarter, zip_path, parquet_dir) is None:
                failed.append(quarter)
        if failed:
            print(f"\nRecord-only processing FAILED for {len(failed)} quarter(s): {', '.join(failed)}")
            sys.exit(1)
        print("\nRecord-only processing complete. All quarters OK.")
        return

    tracker = OverallProgressTracker(len(quarters_to_run))
    for idx, quarter in enumerate(quarters_to_run, start=1):
        q_start = time.perf_counter()
        converted = process_quarter(quarter, zip_path, scratch_dir, parquet_dir)
        tracker.record_quarter(time.perf_counter() - q_start)
        tracker.print_status()

    print("All requested quarters processed successfully.")


if __name__ == "__main__":
    main()
