#!/usr/bin/env python3
"""Parallel orchestrator for Godot ablation runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ablation_analysis import analyze_results_payload, save_analysis


STAGGER_DELAY_SECONDS = 1.5
OUTPUT_SENTINEL = "ABLATION_OUTPUT_PATH:"
CHECKPOINT_VERSION = 1
DEFAULT_WORKER_RETRIES = 2
DEFAULT_PAYLOAD_READ_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0
DEFAULT_PARTIAL_FILENAME_TEMPLATE = "{mode}_ablation_partial.json"
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
REPO_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = REPO_ROOT / ".env"


def _load_dotenv_values(dotenv_path: Path) -> dict[str, str]:
    if not dotenv_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip("'").strip('"')
        values[key] = value
    return values


def _resolve_godot_path(cli_godot_path: str | None) -> str:
    if cli_godot_path:
        return str(Path(cli_godot_path).expanduser())

    env_godot_path = os.environ.get("GODOT_PATH", "").strip()
    if env_godot_path:
        return str(Path(env_godot_path).expanduser())

    dotenv_godot_path = _load_dotenv_values(DOTENV_PATH).get("GODOT_PATH", "").strip()
    if dotenv_godot_path:
        return str(Path(dotenv_godot_path).expanduser())

    raise ValueError(
        "Missing Godot path. Pass --godot-path or set GODOT_PATH in environment/.env."
    )


@dataclass(frozen=True)
class WorkerSpec:
    config_label: str
    worker_index: int


def _json_dumps_stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _hash_run_signature(signature_payload: dict[str, Any]) -> str:
    stable = _json_dumps_stable(signature_payload)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(path)


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
    worker_retries: int,
    worker_timeout_seconds: float,
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

    retry_history: list[dict[str, Any]] = []
    max_attempts = max(1, worker_retries + 1)
    output_path = ""
    returncode = 1
    final_error = ""

    for attempt in range(max_attempts):
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=worker_timeout_seconds if worker_timeout_seconds > 0 else None,
            )
            combined_output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            returncode = completed.returncode
            output_path = _parse_output_path(combined_output)
            timed_out = False
        except subprocess.TimeoutExpired as timeout_error:
            timed_out = True
            returncode = 124
            stdout = timeout_error.stdout if isinstance(timeout_error.stdout, str) else ""
            stderr = timeout_error.stderr if isinstance(timeout_error.stderr, str) else ""
            combined_output = (stdout or "") + "\n" + (stderr or "")
            output_path = _parse_output_path(combined_output)

        success = returncode == 0 and bool(output_path)
        retry_history.append(
            {
                "attempt": attempt + 1,
                "returncode": returncode,
                "output_path_found": bool(output_path),
                "timed_out": timed_out,
            }
        )
        if success:
            final_error = ""
            break

        missing_output = not output_path
        final_error = "nonzero_returncode" if returncode != 0 else "missing_output_path"
        if timed_out:
            final_error = "timeout"
        should_retry = attempt < (max_attempts - 1) and (returncode != 0 or missing_output)
        if should_retry:
            backoff_seconds = DEFAULT_RETRY_BACKOFF_SECONDS * (2**attempt)
            jitter_seconds = random.uniform(0.0, 0.75)
            time.sleep(backoff_seconds + jitter_seconds)

    return {
        "config": spec.config_label,
        "command": command,
        "returncode": returncode,
        "output_path": output_path,
        "attempts_used": len(retry_history),
        "retry_count": max(0, len(retry_history) - 1),
        "retry_history": retry_history,
        "success": returncode == 0 and bool(output_path),
        "final_error": final_error,
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


def _load_worker_payload_with_retry(output_path: str, retries: int) -> dict[str, Any]:
    last_error: Exception | None = None
    max_attempts = max(1, retries)
    for attempt in range(max_attempts):
        try:
            return _load_worker_payload(output_path)
        except (FileNotFoundError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < max_attempts - 1:
                time.sleep(0.5 * (2**attempt))
    assert last_error is not None
    raise last_error


def _merge_worker_payloads(
    worker_payloads: list[dict[str, Any]],
    worker_results: list[dict[str, Any]],
    mode: str,
    max_attempts: int,
    expected_configs: list[str] | None = None,
    resumed_from_checkpoint: bool = False,
    checkpoint_version: int = CHECKPOINT_VERSION,
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
    expected = sorted(expected_configs) if expected_configs is not None else unique_configs
    missing_configs = sorted(set(expected) - set(unique_configs))
    incomplete_run = len(missing_configs) > 0
    termination_reason = " | ".join(termination_messages)
    timestamp = datetime.now().isoformat(timespec="seconds")
    return {
        "timestamp": timestamp,
        "mode": mode,
        "worker_count": len(worker_results),
        "checkpoint_version": checkpoint_version,
        "resumed_from_checkpoint": resumed_from_checkpoint,
        "incomplete_run": incomplete_run,
        "missing_configs": missing_configs,
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


def _save_payload_to_path(payload: dict[str, Any], output_path: Path) -> Path:
    _write_json_atomic(output_path, payload)
    return output_path


def _build_signature_payload(
    mode: str,
    max_attempts: int,
    puzzle_path: str,
    configs: list[str],
    project_path: str,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "max_attempts": max_attempts,
        "puzzle_path": puzzle_path,
        "configs": sorted(configs),
        "project_path": project_path,
    }


def _build_checkpoint_payload(
    run_signature: str,
    run_signature_payload: dict[str, Any],
    completed_workers: list[dict[str, Any]],
    failed_workers: list[dict[str, Any]],
    pending_configs: list[str],
) -> dict[str, Any]:
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "run_signature": run_signature,
        "run_signature_payload": run_signature_payload,
        "completed_workers": completed_workers,
        "failed_workers": failed_workers,
        "pending_configs": sorted(pending_configs),
    }


def _load_checkpoint_if_valid(
    checkpoint_path: Path,
    expected_signature: str,
) -> dict[str, Any]:
    if not checkpoint_path.exists():
        return {}
    raw = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if raw.get("run_signature", "") != expected_signature:
        return {}
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Godot ablation workers in parallel.")
    parser.add_argument(
        "--godot-path",
        default=None,
        help="Path to the Godot binary. If omitted, uses GODOT_PATH from env or .env.",
    )
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
    parser.add_argument(
        "--checkpoint-path",
        default="",
        help="Checkpoint JSON path. Defaults to <output-dir>/<mode>_ablation_checkpoint.json.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint and skip completed configs.",
    )
    parser.add_argument(
        "--allow-partial-success",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep partial merged output when some configs fail.",
    )
    parser.add_argument(
        "--worker-retries",
        type=int,
        default=DEFAULT_WORKER_RETRIES,
        help="Retry count for each worker process on failure.",
    )
    parser.add_argument(
        "--worker-timeout-seconds",
        type=float,
        default=0.0,
        help="Optional timeout for each worker process attempt; 0 disables timeout.",
    )
    parser.add_argument(
        "--payload-read-retries",
        type=int,
        default=DEFAULT_PAYLOAD_READ_RETRIES,
        help="Retry attempts for loading worker JSON outputs.",
    )
    args = parser.parse_args()

    try:
        godot_path = _resolve_godot_path(args.godot_path)
    except ValueError as error:
        parser.error(str(error))
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

    checkpoint_path = (
        Path(args.checkpoint_path).expanduser().resolve()
        if str(args.checkpoint_path).strip()
        else output_dir / f"{args.mode}_ablation_checkpoint.json"
    )
    partial_output_path = output_dir / DEFAULT_PARTIAL_FILENAME_TEMPLATE.format(mode=args.mode)
    run_signature_payload = _build_signature_payload(
        args.mode,
        max_attempts,
        args.puzzle_path,
        config_labels,
        project_path,
    )
    run_signature = _hash_run_signature(run_signature_payload)
    checkpoint_data: dict[str, Any] = {}
    resumed_from_checkpoint = False
    completed_workers: list[dict[str, Any]] = []
    failed_workers: list[dict[str, Any]] = []
    completed_by_config: dict[str, dict[str, Any]] = {}
    if args.resume:
        checkpoint_data = _load_checkpoint_if_valid(checkpoint_path, run_signature)
        if checkpoint_data:
            resumed_from_checkpoint = True
            for row in checkpoint_data.get("completed_workers", []):
                config = str(row.get("config", ""))
                output_path = str(row.get("output_path", ""))
                if config and output_path:
                    completed_by_config[config] = row
            failed_workers = list(checkpoint_data.get("failed_workers", []))
            if completed_by_config:
                print(
                    "Resuming from checkpoint with completed configs: "
                    + ", ".join(sorted(completed_by_config.keys()))
                )
        else:
            print("No matching checkpoint found; starting fresh run.")

    pending_configs = [label for label in config_labels if label not in completed_by_config]
    specs = [WorkerSpec(config_label=label, worker_index=index) for index, label in enumerate(pending_configs)]
    prefix_base = "mini_ablation" if args.mode == "mini" else "ablation"
    worker_results: list[dict[str, Any]] = list(completed_by_config.values())

    def _persist_checkpoint_snapshot() -> None:
        payload = _build_checkpoint_payload(
            run_signature=run_signature,
            run_signature_payload=run_signature_payload,
            completed_workers=sorted(completed_workers, key=lambda row: str(row["config"])),
            failed_workers=sorted(failed_workers, key=lambda row: str(row["config"])),
            pending_configs=[label for label in config_labels if label not in {str(x["config"]) for x in completed_workers}],
        )
        _write_json_atomic(checkpoint_path, payload)

    print(
        f"Starting {len(specs)} workers (mode={args.mode}, max_parallel={min(max_parallel, len(specs)) if specs else 0}, "
        f"max_attempts={max_attempts})"
    )
    completed_workers.extend(worker_results)
    _persist_checkpoint_snapshot()
    if specs:
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
                    max(0, int(args.worker_retries)),
                    max(0.0, float(args.worker_timeout_seconds)),
                )
                for spec in specs
            ]
            for future in as_completed(futures):
                try:
                    result = future.result()
                except Exception as error:  # pragma: no cover - defensive path
                    result = {
                        "config": "<unknown>",
                        "returncode": 1,
                        "output_path": "",
                        "success": False,
                        "final_error": f"worker_exception:{error}",
                        "retry_count": 0,
                    }
                worker_results.append(result)
                if result.get("success", False):
                    completed_workers.append(result)
                else:
                    failed_workers.append(result)
                _persist_checkpoint_snapshot()
                print(
                    f"[{result['config']}] returncode={result['returncode']} "
                    f"output_path={result['output_path'] or '<missing>'} "
                    f"retries={result.get('retry_count', 0)}"
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
        if not args.allow_partial_success:
            return 1

    worker_payloads: list[dict[str, Any]] = []
    successful_results = [row for row in worker_results if row.get("returncode", 1) == 0 and row.get("output_path")]
    for row in successful_results:
        worker_payloads.append(
            _load_worker_payload_with_retry(
                str(row["output_path"]),
                max(1, int(args.payload_read_retries)),
            )
        )
        partial_payload = _merge_worker_payloads(
            worker_payloads,
            successful_results,
            args.mode,
            max_attempts,
            expected_configs=config_labels,
            resumed_from_checkpoint=resumed_from_checkpoint,
        )
        _save_payload_to_path(partial_payload, partial_output_path)

    if not worker_payloads:
        print("No successful worker payloads were produced.")
        return 1

    merged_payload = _merge_worker_payloads(
        worker_payloads,
        successful_results,
        args.mode,
        max_attempts,
        expected_configs=config_labels,
        resumed_from_checkpoint=resumed_from_checkpoint,
    )
    merged_path = _save_merged_payload(merged_payload, output_dir, args.mode)
    print(f"MERGED_OUTPUT_PATH:{merged_path}")
    print(f"PARTIAL_OUTPUT_PATH:{partial_output_path}")

    analysis = analyze_results_payload(merged_payload)
    analysis_path = save_analysis(analysis, output_dir)
    print(f"ANALYSIS_OUTPUT_PATH:{analysis_path}")
    return 0 if (not failed_workers or args.allow_partial_success) else 1


if __name__ == "__main__":
    raise SystemExit(main())
