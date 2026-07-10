"""Download pinned faster-whisper model snapshots for 2B-4 benchmark preparation.

This helper is intentionally independent from the application runtime. It relies
on Hugging Face Hub's normal cache and recovery behavior and does not use the
deprecated ``resume_download`` argument or any replacement for it.

Default behavior is safe: no download happens unless exactly one model is chosen
with ``--model``. Use ``--dry-run`` or ``--list-only`` for no-network checks.

Examples:
    python scripts/download_asr_models.py --dry-run --model small
    python scripts/download_asr_models.py --list-only
    python scripts/download_asr_models.py --model medium
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import snapshot_download
from huggingface_hub.utils import HfHubHTTPError


@dataclass(frozen=True)
class ModelSpec:
    name: str
    repo_id: str
    revision: str


PINNED_MODELS: dict[str, ModelSpec] = {
    "small": ModelSpec(
        name="small",
        repo_id="Systran/faster-whisper-small",
        revision="536b0662742c02347bc0e980a01041f333bce120",
    ),
    "medium": ModelSpec(
        name="medium",
        repo_id="Systran/faster-whisper-medium",
        revision="08e178d48790749d25932bbc082711ddcfdfbc4f",
    ),
}

# Intentionally not part of parser choices. Turbo is deferred for 2B-4 and must
# be added only after a separate user-approved task.
DEFERRED_MODELS = {"turbo": "Systran/faster-whisper-turbo"}


def _snapshot_path_from_cache(spec: ModelSpec) -> Path:
    safe_repo = spec.repo_id.replace("/", "--")
    return Path.home() / ".cache" / "huggingface" / "hub" / f"models--{safe_repo}" / "snapshots" / spec.revision


def list_cached() -> None:
    """List pinned snapshot locations without network access or downloads."""
    print("Pinned faster-whisper model snapshots (no network):")
    for spec in PINNED_MODELS.values():
        snapshot_path = _snapshot_path_from_cache(spec)
        status = "present" if snapshot_path.is_dir() else "missing"
        print(f"repo_id: {spec.repo_id}")
        print(f"revision: {spec.revision}")
        print(f"snapshot path: {snapshot_path}")
        print(f"status: {status}\n")
    print("Deferred models: turbo (not downloaded by default)")


def download_one(spec: ModelSpec, *, dry_run: bool, offline: bool) -> dict[str, str | bool]:
    print("=" * 60)
    print(f"repo_id: {spec.repo_id}")
    print(f"revision: {spec.revision}")
    print(f"model: {spec.name}")
    print("=" * 60)

    if dry_run:
        snapshot_path = _snapshot_path_from_cache(spec)
        print("[dry-run] no network, no download")
        print(f"snapshot path: {snapshot_path}")
        return {
            "repo_id": spec.repo_id,
            "model": spec.name,
            "revision": spec.revision,
            "snapshot_path": str(snapshot_path),
            "dry_run": True,
        }

    try:
        snapshot_path = snapshot_download(
            repo_id=spec.repo_id,
            revision=spec.revision,
            local_files_only=offline,
            max_workers=4,
        )
    except HfHubHTTPError as exc:
        print(f"FAIL: HTTP error while resolving {spec.repo_id}@{spec.revision}: {exc}")
        raise
    except Exception as exc:
        print(f"FAIL: could not resolve {spec.repo_id}@{spec.revision}: {exc}")
        raise

    print("OK")
    print(f"repo_id: {spec.repo_id}")
    print(f"revision: {spec.revision}")
    print(f"snapshot path: {snapshot_path}")
    return {
        "repo_id": spec.repo_id,
        "model": spec.name,
        "revision": spec.revision,
        "snapshot_path": str(snapshot_path),
        "dry_run": False,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve one pinned faster-whisper model snapshot")
    parser.add_argument(
        "--model",
        choices=sorted(PINNED_MODELS),
        help="Exactly one model to resolve. No default is used to avoid accidental downloads.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without network or download")
    parser.add_argument(
        "--list-only",
        "--list",
        action="store_true",
        help="List pinned cached snapshots only; no network or download",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help="Allow Hugging Face Hub network access. Default is offline/local cache only.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.list_only:
        list_cached()
        return 0

    if not args.model:
        print("No model selected. Use --model small or --model medium, or use --list-only/--dry-run.")
        print("Default intentionally downloads nothing. Turbo is deferred and unavailable here.")
        return 2

    spec = PINNED_MODELS[args.model]
    result = download_one(spec, dry_run=args.dry_run, offline=not args.online)

    print("\nSUMMARY")
    print(f"repo_id: {result['repo_id']}")
    print(f"revision: {result['revision']}")
    print(f"snapshot path: {result['snapshot_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
