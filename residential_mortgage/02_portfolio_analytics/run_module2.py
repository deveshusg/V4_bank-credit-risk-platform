"""Run the Module 2 portfolio analytics pipeline in dependency order (00 to 18).

Usage:
    .venv\\Scripts\\python.exe residential_mortgage\\02_portfolio_analytics\\run_module2.py
    .venv\\Scripts\\python.exe residential_mortgage\\02_portfolio_analytics\\run_module2.py --full
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

MODULE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = MODULE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from module2_common import REPO_ROOT, SCRATCH_DIR  # noqa: E402

SCRIPTS: tuple[str, ...] = (
    "00_build_monthly_core",
    "01_data_audit",
    "02_default_engine",
    "03_roll_rates",
    "04_emergence_and_thresholds",
    "05_vintage_curves",
    "06_current_ltv",
    "07_default_rate_history",
    "08_sample_population",
    "09_risk_drivers",
    "10_segmentation",
    "11_default_outcomes",
    "12_forbearance",
    "13_economy_links",
    "14_cycle_and_benchmarks",
    "15_portfolio_mix",
    "16_representativeness",
    "17_survivorship",
    "18_portfolio_findings",
)


def resolve_start_index(from_step: str | None) -> int:
    """Resolve a script prefix (e.g. '07') or full stem to its index in SCRIPTS."""
    if not from_step:
        return 0
    needle = from_step.removesuffix(".py").strip()
    matches = [
        idx
        for idx, name in enumerate(SCRIPTS)
        if name == needle or name.startswith(f"{needle}_")
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        valid = ", ".join(s[:2] for s in SCRIPTS)
        raise SystemExit(f"Unknown --from-step '{from_step}'. Expected prefix in {{{valid}}} or full script name.")
    raise SystemExit(f"Ambiguous --from-step '{from_step}': matches {[SCRIPTS[i] for i in matches]}")


def emit(line: str, log_file: TextIO | None) -> None:
    """Write a line to stdout and optionally flush it to the log file."""
    sys.stdout.write(line)
    sys.stdout.flush()
    if log_file is not None:
        log_file.write(line)
        log_file.flush()


def run_step(script_stem: str, full: bool, log_file: TextIO | None) -> int:
    """Execute one Module 2 script with unbuffered output streamed to stdout and log_file."""
    script_path = SCRIPTS_DIR / f"{script_stem}.py"
    if not script_path.is_file():
        emit(f"FAIL  missing script: {script_path}\n", log_file)
        return 1

    cmd = [sys.executable, "-u", str(script_path)]
    if full:
        cmd.append("--full")

    emit(f"=== {script_stem} ===\n", log_file)
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        emit(line, log_file)
    rc = proc.wait()
    elapsed = time.perf_counter() - t0
    status = "OK" if rc == 0 else f"FAIL (exit {rc})"
    emit(f"--- {script_stem}: {status} in {elapsed:.1f}s ---\n", log_file)
    return rc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI options for the Module 2 batch runner."""
    parser = argparse.ArgumentParser(description="Run Module 2 scripts 00 through 18 sequentially.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run against full mortgages.duckdb into full/ outputs (default uses sample DB).",
    )
    parser.add_argument(
        "--from-step",
        default=None,
        help="Start from script number or name (e.g. '07' or '07_default_rate_history').",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Optional log file path (default: .scratch/module2_run[_full].log).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the scripts that would run without executing them.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run selected Module 2 scripts in order and stop on the first failure."""
    args = parse_args(argv)
    start_idx = resolve_start_index(args.from_step)
    selected = SCRIPTS[start_idx:]

    if args.dry_run:
        mode = "full" if args.full else "sample (default)"
        print(f"Module 2 dry-run ({mode}, {len(selected)} scripts):")
        for stem in selected:
            suffix = " --full" if args.full else ""
            print(f"  {sys.executable} -u {SCRIPTS_DIR / f'{stem}.py'}{suffix}")
        return 0

    default_log = SCRATCH_DIR / ("module2_run_full.log" if args.full else "module2_run_sample.log")
    log_path = args.log if args.log is not None else default_log
    if not log_path.is_absolute():
        log_path = REPO_ROOT / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    t_all = time.perf_counter()
    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        for stem in selected:
            rc = run_step(stem, full=args.full, log_file=log_file)
            if rc != 0:
                emit(f"OVERALL: FAIL on {stem} (log: {log_path})\n", log_file)
                return rc
        total_elapsed = time.perf_counter() - t_all
        emit(
            f"=== module 2 run complete ({len(selected)} scripts in {total_elapsed:.1f}s; log: {log_path}) ===\n",
            log_file,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
