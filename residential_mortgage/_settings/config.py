"""Shared settings and path resolution loader for the residential_mortgage platform."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

SETTINGS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SETTINGS_DIR.parent
REPO_ROOT = PACKAGE_ROOT.parent


def load(name: str) -> dict[str, Any]:
    """Load one TOML settings group from residential_mortgage/_settings/<name>.toml."""
    path = SETTINGS_DIR / f"{name}.toml"
    if not path.is_file():
        raise FileNotFoundError(f"Settings file not found: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def resolve_path(rel_or_abs: str | Path) -> Path:
    """Resolve a path from paths.toml relative to residential_mortgage/."""
    p = Path(rel_or_abs)
    return p if p.is_absolute() else (PACKAGE_ROOT / p).resolve()


def paths() -> dict[str, Path]:
    """Return resolved platform data, output, and scratch paths."""
    cfg = load("paths")
    data = cfg["data"]
    return {
        "raw_dir": resolve_path(data["raw_dir"]),
        "fannie_mae_zip": resolve_path(data["fannie_mae_zip"]),
        "macro_dir": resolve_path(data["macro_dir"]),
        "parquet_dir": resolve_path(data["parquet_dir"]),
        "processed_dir": resolve_path(data["processed_dir"]),
        "module_outputs_dir": resolve_path(data["module_outputs_dir"]),
        "scratch_dir": resolve_path(data["scratch_dir"]),
    }


def scope_name(full: bool = False) -> str:
    """Return 'full' when opt-in full mode is enabled, else 'sample' (default)."""
    return "full" if full else "sample"


def base_db_path(full: bool = False) -> Path:
    """Return base DuckDB path: sample DB by default, or full DB when full=True."""
    cfg = load("paths")
    p = paths()
    if full:
        return p["processed_dir"] / cfg["databases"]["full_db"]
    return p["module_outputs_dir"] / "00_data" / cfg["databases"]["sample_db"]


def module_outputs(module_name: str, full: bool = False) -> Path:
    """Return module output directory: module_outputs/<module>/<sample|full>/."""
    p = paths()
    return p["module_outputs_dir"] / module_name / scope_name(full)


def script_outputs(module_name: str, script_stem: str, full: bool = False) -> Path:
    """Return per-script output folder inside module_outputs/<module>/<sample|full>/<script_stem>/."""
    return module_outputs(module_name, full=full) / script_stem


def module_db_path(module_name: str, stem: str, full: bool = False) -> Path:
    """Return <stem>.duckdb (full) or <stem>_sample.duckdb (sample) inside module outputs."""
    suffix = "" if full else "_sample"
    return module_outputs(module_name, full=full) / f"{stem}{suffix}.duckdb"
