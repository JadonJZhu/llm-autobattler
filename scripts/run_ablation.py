#!/usr/bin/env python3
"""Parallel orchestrator for Godot ablation runs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ablation_analysis import analyze_results_payload, save_analysis


STAGGER_DELAY_SECONDS = 1.5
OUTPUT_SENTINEL = "ABLATION_OUTPUT_PATH:"
FULL_CONFIGS = [
    "I0_E0_R0",
    "I0_E0_R1",
    "I0_E1_R0",
    "I0_E1_R1",
    "I1_E0_R0",
    "I1_E0_R1",
    "I1_E1_R0",
    "I1_E1_R1",
]
MINI_CONFIGS = ["I0_E0_R0", "I1_E1_R1"]
CONFIG_LABEL_RE = re.compile(r"^I[01]_E[01]_R[01]$")


@dataclass(frozen=True)
class WorkerSpec:
    config_label: str
    worker_index: int


def _parse_output_path(raw_output: str) -> str:
    for line in raw_output.splitlines():
        if line.startswith(OUTPUT_SENTINEL):
            return line[len(OUTPUT_SENTINEL) :].strip()
    return ""


def _run_single_worker(
    spec: WorkerSpec,
    godot_path: str,
    project_path: str,
    mode: str,
    max_attempts: int,
    puzzle_path: str,
    prefix_base: str,
    stagger_delay_seconds: float,
) -> dict[str, Any]:
    # Spread launches to reduce first-request bursts.
    if spec.worker_index > 0 and stagger_delay_seconds > 0:
        import time

        time.sleep(spec.worker_index * stagger_delay_seconds)

    mode_flag = "--mini-ablation" if mode == "mini" else "--ablation"
    output_prefix = f"{prefix_base}_{spec.config_label}"
    command = [
        godot_path,
        "--headless",
        "--path",
        project_path,
        "--",
        mode_flag,
        "--config",
        spec.config_label,
        "--max-attempts",
        str(max_attempts),
        "--puzzle-path",
        puzzle_path,
        "--output-prefix",
        output_prefix,
    ]

    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    combined_output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    output_path = _parse_output_path(combined_output)

    return {
        "config": spec.config_label,
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "output_path": output_path,
    }


def _validate_configs(configs: list[str]) -> list[str]:
    normalized: list[str] = []
    for label in configs:
        trimmed = label.strip()
        if not trimmed:
            continue
        if not CONFIG_LABEL_RE.match(trimmed):
            raise ValueError(f"Invalid config label: {trimmed}")
        normalized.append(trimmed)
    deduped = sorted(set(normalized))
    if not deduped:
        raise ValueError("No valid configs provided.")
    return deduped


def _load_worker_payload(output_path: str) -> dict[str, Any]:
    path = Path(output_path)
    if not path.exists():
        raise FileNotFoundError(f"Worker output path does not exist: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_worker_payloads(
    worker_payloads: list[dict[str, Any]],
    worker_results: list[dict[str, Any]],
    mode: str,
    max_attempts: int,
) -> dict[str, Any]:
    merged_rows: list[dict[str, Any]] = []
    merged_by_config: dict[str, dict[str, Any]] = {}
    all_puzzle_ids: set[str] = set()
    terminated_early = False
    termination_messages: list[str] = []

    for payload in worker_payloads:
        run_results = payload.get("results", {})
        rows = run_results.get("results", [])
        for row in rows:
            merged_rows.append(row)
            all_puzzle_ids.add(str(row.get("puzzle_id", "")))
        by_config = run_results.get("by_config", {})
        for config_label, bucket in by_config.items():
            merged_by_config[config_label] = bucket
        if bool(run_results.get("terminated_early", False)):
            terminated_early = True
            reason = str(run_results.get("termination_reason", "")).strip()
            if reason:
                termination_messages.append(reason)

    unique_configs = sorted(merged_by_config.keys())
    termination_reason = " | ".join(termination_messages)
    timestamp = datetime.now().isoformat(timespec="seconds")
    return {
        "timestamp": timestamp,
        "mode": mode,
        "worker_count": len(worker_results),
        "workers": worker_results,
        "results": {
            "max_attempts_per_puzzle": max_attempts,
            "puzzle_count": len(all_puzzle_ids),
            "config_count": len(unique_configs),
            "terminated_early": terminated_early,
            "termination_reason": termination_reason,
            "results": merged_rows,
            "by_config": merged_by_config,
        },
    }


def _save_merged_payload(payload: dict[str, Any], output_dir: Path, mode: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{mode}_ablation_merged_{timestamp}.json"
    output_path = output_dir / filename
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Godot ablation workers in parallel.")
    parser.add_argument("--godot-path", required=True, help="Path to the Godot binary.")
    parser.add_argument("--project-path", default="./godot", help="Path to the Godot project.")
    parser.add_argument("--max-attempts", type=int, default=10, help="Attempt cap per puzzle.")
    parser.add_argument("--max-parallel", type=int, default=8, help="Max concurrent workers.")
    parser.add_argument(
        "--puzzle-path",
        default="res://puzzles/puzzle_suite.json",
        help="Puzzle JSON path passed into Godot.",
    )
    parser.add_argument(
        "--configs",
        nargs="*",
        default=None,
        help="Optional config labels (example: I0_E0_R0 I1_E1_R1).",
    )
    parser.add_argument(
        "--output-dir",
        default="./ablation_results",
        help="Directory for merged output and analysis.",
    )
    parser.add_argument(
        "--mode",
        choices=("full", "mini"),
        default="full",
        help="Run full 8-config ablation or mini-ablation.",
    )
    parser.add_argument(
        "--stagger-delay",
        type=float,
        default=STAGGER_DELAY_SECONDS,
        help="Seconds to stagger worker launches.",
    )
    args = parser.parse_args()

    godot_path = str(Path(args.godot_path).expanduser())
    project_path = str(Path(args.project_path).expanduser().resolve())
    output_dir = Path(args.output_dir).expanduser().resolve()
    max_attempts = max(1, int(args.max_attempts))
    max_parallel = max(1, int(args.max_parallel))

    default_configs = MINI_CONFIGS if args.mode == "mini" else FULL_CONFIGS
    config_labels = _validate_configs(args.configs if args.configs else default_configs)
    if args.mode == "mini":
        unsupported = [label for label in config_labels if label not in MINI_CONFIGS]
        if unsupported:
            print(
                "Mini mode only supports configs {allowed}; got {bad}".format(
                    allowed=" ".join(MINI_CONFIGS),
                    bad=" ".join(unsupported),
                )
            )
            return 1

    specs = [WorkerSpec(config_label=label, worker_index=index) for index, label in enumerate(config_labels)]
    prefix_base = "mini_ablation" if args.mode == "mini" else "ablation"
    worker_results: list[dict[str, Any]] = []

    print(
        f"Starting {len(specs)} workers (mode={args.mode}, max_parallel={min(max_parallel, len(specs))}, "
        f"max_attempts={max_attempts})"
    )
    with ProcessPoolExecutor(max_workers=min(max_parallel, len(specs))) as executor:
        futures = [
            executor.submit(
                _run_single_worker,
                spec,
                godot_path,
                project_path,
                args.mode,
                max_attempts,
                args.puzzle_path,
                prefix_base,
                args.stagger_delay,
            )
            for spec in specs
        ]
        for future in as_completed(futures):
            result = future.result()
            worker_results.append(result)
            print(
                f"[{result['config']}] returncode={result['returncode']} "
                f"output_path={result['output_path'] or '<missing>'}"
            )

    worker_results.sort(key=lambda row: row["config"])
    failed_workers = [
        row
        for row in worker_results
        if row["returncode"] != 0 or not row["output_path"]
    ]
    if failed_workers:
        print("One or more workers failed:")
        for row in failed_workers:
            print(f"- {row['config']}: returncode={row['returncode']}, output_path={row['output_path']}")
        return 1

    worker_payloads: list[dict[str, Any]] = []
    for row in worker_results:
        worker_payloads.append(_load_worker_payload(str(row["output_path"])))

    merged_payload = _merge_worker_payloads(worker_payloads, worker_results, args.mode, max_attempts)
    merged_path = _save_merged_payload(merged_payload, output_dir, args.mode)
    print(f"MERGED_OUTPUT_PATH:{merged_path}")

    analysis = analyze_results_payload(merged_payload)
    analysis_path = save_analysis(analysis, output_dir)
    print(f"ANALYSIS_OUTPUT_PATH:{analysis_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
