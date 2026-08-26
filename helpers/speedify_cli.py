from __future__ import annotations

import json
import subprocess
import time
from typing import Any

CLI_PATH = "/Applications/Speedify.app/Contents/Resources/speedify_cli"


def run_cli(args: list[str]) -> Any:
    """Runs a speedify_cli subcommand and parses its JSON stdout.

    Args are passed as an argv list to subprocess, never through a shell.
    """
    try:
        result = subprocess.run(
            [CLI_PATH, *args],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"speedify_cli {' '.join(args)} timed out") from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"speedify_cli {' '.join(args)} failed: {result.stderr or result.stdout}"
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"speedify_cli {' '.join(args)} did not return valid JSON:\n{result.stdout}"
        ) from exc


def get_state() -> str:
    return run_cli(["state"])["state"]


def get_settings() -> dict:
    return run_cli(["show", "settings"])


def get_adapters() -> list[dict]:
    return run_cli(["show", "adapters"])


def get_current_server() -> dict:
    return run_cli(["show", "currentserver"])


def connect() -> dict:
    """Connects to the best server (no target = automatic best-server selection)."""
    return run_cli(["connect"])


def connect_to(country: str) -> dict:
    """Connects to a specific country code (or a server tag / "closest")."""
    return run_cli(["connect", country])


def disconnect() -> dict:
    return run_cli(["disconnect"])


def set_mode(mode: str) -> dict:
    return run_cli(["mode", mode])


def set_encryption(on_off: str) -> dict:
    return run_cli(["encryption", on_off])


def wait_for_state(target_state: str, timeout: float = 15) -> str:
    """Polls get_state() until it matches target_state, or raises on timeout."""
    deadline = time.monotonic() + timeout
    last = ""

    while time.monotonic() < deadline:
        last = get_state()
        if last == target_state:
            return last
        time.sleep(0.5)

    raise TimeoutError(
        f"Timed out after {timeout}s waiting for state {target_state!r}, last seen: {last!r}"
    )
