#!/usr/bin/env python3
"""Run or resume the official full ablation experiment."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_ABLATION_SCRIPT = REPO_ROOT / "scripts" / "run_ablation.py"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "ablation_results"
DEFAULT_PROJECT_PATH = "./godot"
DEFAULT_PUZZLE_PATH = "res://puzzles/puzzle_suite.json"
DEFAULT_MAX_ATTEMPTS = 30
DEFAULT_CHECKPOINT_FILENAME = "full_ablation_checkpoint.json"
DOTENV_PATH = REPO_ROOT / ".env"
EXPECTED_FULL_CONFIGS = {
    "I0_E0_R0",
    "I0_E0_R1",
    "I0_E1_R0",
    "I0_E1_R1",
    "I1_E0_R0",
    "I1_E0_R1",
    "I1_E1_R0",
    "I1_E1_R1",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
        values[key] = value.strip().strip("'").strip('"')
    return values


def _require_real_api_key() -> None:
    env_key = os.environ.get("LLM_API_KEY", "").strip()
    if not env_key:
        env_key = _load_dotenv_values(DOTENV_PATH).get("LLM_API_KEY", "").strip()
    if not env_key:
        raise SystemExit(
            "Missing LLM API key. Official ablation requires LLM_API_KEY "
            "in environment or .env."
        )


def _is_incomplete_full_checkpoint(payload: dict[str, Any]) -> bool:
    signature_payload = payload.get("run_signature_payload", {})
    if str(signature_payload.get("mode", "")).strip() != "full":
        return False

    pending_configs = payload.get("pending_configs", [])
    if pending_configs:
        return True

    completed_workers = payload.get("completed_workers", [])
    completed_configs = {
        str(row.get("config", "")).strip() for row in completed_workers if str(row.get("config", "")).strip()
    }
    return completed_configs != EXPECTED_FULL_CONFIGS


def _find_latest_incomplete_checkpoint(output_dir: Path) -> Path | None:
    candidates = sorted(
        output_dir.rglob("*ablation_checkpoint.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            payload = _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if _is_incomplete_full_checkpoint(payload):
            return path
    return None


def _build_resume_command(
    checkpoint_path: Path,
    *,
    godot_path: str,
    max_parallel: int,
) -> list[str]:
    payload = _read_json(checkpoint_path)
    run_payload = payload.get("run_signature_payload", {})

    command = [
        sys.executable,
        str(RUN_ABLATION_SCRIPT),
        "--mode",
        "full",
        "--resume",
        "--checkpoint-path",
        str(checkpoint_path),
        "--output-dir",
        str(checkpoint_path.parent),
        "--max-attempts",
        str(int(run_payload.get("max_attempts", DEFAULT_MAX_ATTEMPTS))),
        "--project-path",
        str(run_payload.get("project_path", DEFAULT_PROJECT_PATH)),
        "--puzzle-path",
        str(run_payload.get("puzzle_path", DEFAULT_PUZZLE_PATH)),
        "--max-parallel",
        str(max_parallel),
    ]
    if godot_path:
        command.extend(["--godot-path", godot_path])

    configs = run_payload.get("configs", [])
    if isinstance(configs, list) and configs:
        command.append("--configs")
        command.extend(str(config) for config in configs)

    return command


def _build_fresh_command(
    *,
    output_dir: Path,
    project_path: str,
    puzzle_path: str,
    max_attempts: int,
    max_parallel: int,
    godot_path: str,
) -> list[str]:
    command = [
        sys.executable,
        str(RUN_ABLATION_SCRIPT),
        "--mode",
        "full",
        "--output-dir",
        str(output_dir),
        "--project-path",
        project_path,
        "--puzzle-path",
        puzzle_path,
        "--max-attempts",
        str(max_attempts),
        "--max-parallel",
        str(max_parallel),
    ]
    if godot_path:
        command.extend(["--godot-path", godot_path])
    return command


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Wrapper around scripts/run_ablation.py for the official full ablation run. "
            "Resumes the latest incomplete full checkpoint when present."
        )
    )
    parser.add_argument(
        "--godot-path",
        default="",
        help="Path to Godot binary. If omitted, run_ablation.py resolves from GODOT_PATH/env/.env.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for ablation artifacts.")
    parser.add_argument("--project-path", default=DEFAULT_PROJECT_PATH, help="Path to the Godot project.")
    parser.add_argument("--puzzle-path", default=DEFAULT_PUZZLE_PATH, help="Puzzle JSON path (Godot res:// path).")
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS, help="Attempt cap per puzzle.")
    parser.add_argument("--max-parallel", type=int, default=8, help="Maximum parallel workers.")
    args = parser.parse_args()

    if not RUN_ABLATION_SCRIPT.exists():
        raise SystemExit(f"Missing orchestrator script: {RUN_ABLATION_SCRIPT}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Double-check before any run selection to guarantee "official" conditions.
    _require_real_api_key()

    checkpoint_path = _find_latest_incomplete_checkpoint(output_dir)
    if checkpoint_path is not None:
        print(f"Resuming incomplete full ablation from checkpoint: {checkpoint_path}")
        command = _build_resume_command(
            checkpoint_path,
            godot_path=str(args.godot_path).strip(),
            max_parallel=max(1, int(args.max_parallel)),
        )
    else:
        default_checkpoint = output_dir / DEFAULT_CHECKPOINT_FILENAME
        print("No incomplete full ablation checkpoint found. Starting a fresh official run.")
        print(f"Checkpoint path for this run: {default_checkpoint}")
        command = _build_fresh_command(
            output_dir=output_dir,
            project_path=str(args.project_path).strip() or DEFAULT_PROJECT_PATH,
            puzzle_path=str(args.puzzle_path).strip() or DEFAULT_PUZZLE_PATH,
            max_attempts=max(1, int(args.max_attempts)),
            max_parallel=max(1, int(args.max_parallel)),
            godot_path=str(args.godot_path).strip(),
        )

    # Double-check right before launch in case the key file changed during setup.
    _require_real_api_key()

    print("Launching command:")
    print(" ".join(command))
    completed = subprocess.run(command, cwd=str(REPO_ROOT), check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
