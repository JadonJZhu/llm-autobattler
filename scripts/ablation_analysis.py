#!/usr/bin/env python3
"""Utilities for analyzing merged ablation outputs."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FeatureBits:
    instructions: int
    examples: int
    reflection: int


def parse_config_label(label: str) -> FeatureBits | None:
    parts = label.strip().split("_")
    if len(parts) != 3:
        return None
    if not parts[0].startswith("I") or not parts[1].startswith("E") or not parts[2].startswith("R"):
        return None
    try:
        i_value = int(parts[0][1:])
        e_value = int(parts[1][1:])
        r_value = int(parts[2][1:])
    except ValueError:
        return None
    if i_value not in (0, 1) or e_value not in (0, 1) or r_value not in (0, 1):
        return None
    return FeatureBits(i_value, e_value, r_value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def analyze_results_payload(payload: dict[str, Any]) -> dict[str, Any]:
    run_results = payload.get("results", {})
    per_puzzle_rows: list[dict[str, Any]] = run_results.get("results", [])
    by_config: dict[str, dict[str, Any]] = run_results.get("by_config", {})

    summary_table: list[dict[str, Any]] = []
    for config_label in sorted(by_config.keys()):
        bucket = by_config.get(config_label, {})
        summary_table.append(
            {
                "config": config_label,
                "pass_rate": _safe_float(bucket.get("pass_rate")),
                "puzzles_solved": _safe_int(bucket.get("puzzles_solved")),
                "puzzles_total": _safe_int(bucket.get("puzzles_total")),
                "mean_attempts_solved_only": _safe_float(bucket.get("mean_attempts_solved_only")),
            }
        )

    # config -> difficulty -> {"solved": int, "total": int}
    difficulty_counts: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"solved": 0, "total": 0})
    )
    for row in per_puzzle_rows:
        config = str(row.get("config", ""))
        if not config:
            continue
        difficulty = str(_safe_int(row.get("difficulty"), 0))
        solved = bool(row.get("solved", False))
        difficulty_counts[config][difficulty]["total"] += 1
        if solved:
            difficulty_counts[config][difficulty]["solved"] += 1

    difficulty_stratified: dict[str, dict[str, dict[str, float | int]]] = {}
    for config, per_difficulty in difficulty_counts.items():
        difficulty_stratified[config] = {}
        for difficulty, counts in sorted(per_difficulty.items(), key=lambda item: int(item[0])):
            solved = counts["solved"]
            total = counts["total"]
            pass_rate = (float(solved) / float(total)) if total > 0 else 0.0
            difficulty_stratified[config][difficulty] = {
                "solved": solved,
                "total": total,
                "pass_rate": pass_rate,
            }

    feature_samples: dict[str, dict[int, list[float]]] = {
        "instructions": {0: [], 1: []},
        "examples": {0: [], 1: []},
        "reflection": {0: [], 1: []},
    }
    for row in summary_table:
        label = row["config"]
        bits = parse_config_label(label)
        if bits is None:
            continue
        pass_rate = _safe_float(row.get("pass_rate"))
        feature_samples["instructions"][bits.instructions].append(pass_rate)
        feature_samples["examples"][bits.examples].append(pass_rate)
        feature_samples["reflection"][bits.reflection].append(pass_rate)

    feature_impact: dict[str, dict[str, float]] = {}
    for feature_name, feature_data in feature_samples.items():
        off_values = feature_data[0]
        on_values = feature_data[1]
        avg_off = (sum(off_values) / len(off_values)) if off_values else 0.0
        avg_on = (sum(on_values) / len(on_values)) if on_values else 0.0
        feature_impact[feature_name] = {
            "avg_pass_rate_off": avg_off,
            "avg_pass_rate_on": avg_on,
            "delta_on_minus_off": avg_on - avg_off,
        }

    best_config: dict[str, Any] | None = None
    worst_config: dict[str, Any] | None = None
    if summary_table:
        best_config = max(
            summary_table,
            key=lambda row: (
                _safe_float(row["pass_rate"]),
                _safe_int(row["puzzles_solved"]),
                -_safe_float(row["mean_attempts_solved_only"]),
            ),
        )
        worst_config = min(
            summary_table,
            key=lambda row: (
                _safe_float(row["pass_rate"]),
                _safe_int(row["puzzles_solved"]),
                _safe_float(row["mean_attempts_solved_only"]),
            ),
        )

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "config_count": _safe_int(run_results.get("config_count")),
        "puzzle_count": _safe_int(run_results.get("puzzle_count")),
        "max_attempts_per_puzzle": _safe_int(run_results.get("max_attempts_per_puzzle")),
        "terminated_early": bool(run_results.get("terminated_early", False)),
        "termination_reason": str(run_results.get("termination_reason", "")),
        "summary_table": summary_table,
        "difficulty_pass_rates": difficulty_stratified,
        "feature_impact": feature_impact,
        "best_config": best_config,
        "worst_config": worst_config,
    }


def save_analysis(analysis: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"ablation_analysis_{timestamp}.json"
    output_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    return output_path


def _print_summary(analysis: dict[str, Any]) -> None:
    print("Ablation summary:")
    for row in analysis.get("summary_table", []):
        print(
            "  {config}: solved={solved}/{total}, pass_rate={pass_rate:.3f}, mean_attempts={mean_attempts:.3f}".format(
                config=row.get("config", ""),
                solved=_safe_int(row.get("puzzles_solved")),
                total=_safe_int(row.get("puzzles_total")),
                pass_rate=_safe_float(row.get("pass_rate")),
                mean_attempts=_safe_float(row.get("mean_attempts_solved_only")),
            )
        )

    best = analysis.get("best_config")
    worst = analysis.get("worst_config")
    if best:
        print(f"Best config: {best.get('config')} (pass_rate={_safe_float(best.get('pass_rate')):.3f})")
    if worst:
        print(f"Worst config: {worst.get('config')} (pass_rate={_safe_float(worst.get('pass_rate')):.3f})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze merged ablation results JSON.")
    parser.add_argument("--input", required=True, help="Path to merged ablation JSON.")
    parser.add_argument(
        "--output-dir",
        default="./ablation_results",
        help="Directory for analysis output JSON.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input file does not exist: {input_path}")
        return 1

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    analysis = analyze_results_payload(payload)
    analysis_path = save_analysis(analysis, Path(args.output_dir))
    _print_summary(analysis)
    print(f"ANALYSIS_OUTPUT_PATH:{analysis_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
