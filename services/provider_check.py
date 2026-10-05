"""Read-only provider checks. No inference, user data, or secrets in output."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from urllib.parse import quote

import httpx


def runtime_environment() -> dict[str, str] | None:
    """Read the running AURA process, never expose its environment."""
    try:
        pid = subprocess.run(
            ["systemctl", "show", "nutrition-bot", "-p", "MainPID", "--value"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
        if not pid.isdigit() or int(pid) == 0:
            return None
        with open(f"/proc/{pid}/environ", "rb") as stream:
            raw = stream.read()
        return dict(part.decode().split("=", 1) for part in raw.split(b"\0") if b"=" in part)
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return None


def safe_model(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) else "invalid_model_setting"


async def check_anthropic(env: dict[str, str], client: httpx.AsyncClient) -> dict:
    key = env.get("ANTHROPIC_API_KEY", "")
    if not key:
        return {"provider": "anthropic", "status": "missing_key"}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    report = {"provider": "anthropic", "models": {}}
    # Resolve configured aliases individually. A paginated list can omit them.
    for name, fallback in (("VISION_MODEL", "claude-sonnet-5"), ("BUILD_MODEL", "claude-opus-5")):
        model = safe_model(env.get(name, fallback))
        if model == "invalid_model_setting":
            report["models"][name] = {"status": model}
            continue
        try:
            response = await client.get(
                "https://api.anthropic.com/v1/models/" + quote(model, safe=""), headers=headers,
            )
            code = response.status_code
            state = {200: "available", 401: "authentication_rejected", 402: "billing_required",
                     403: "permission_denied", 404: "model_unavailable", 429: "rate_limited"}.get(code, "provider_error")
            report["models"][name] = {"model": model, "http_status": code, "status": state}
            if code in (401, 402, 403, 429):
                break
        except (httpx.HTTPError, ValueError):
            # Exception strings may contain a URL, headers, or credentials.
            report["models"][name] = {"model": model, "status": "connection_failed"}
            break
    return report


async def collect() -> dict:
    configured = dict(os.environ)
    running = runtime_environment()
    selected = {**configured, **(running or {})}
    key_in_running = running is not None and "ANTHROPIC_API_KEY" in running
    report = {
        "source": "running_process_environment" if key_in_running else "script_environment",
        "running_key_observable": key_in_running,
        "key_matches_script_environment": (
            running.get("ANTHROPIC_API_KEY", "") == configured.get("ANTHROPIC_API_KEY", "")
            if key_in_running else None
        ),
        "inference_tested": False,
    }
    async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
        report["anthropic"] = await check_anthropic(selected, client)
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(collect()), ensure_ascii=False))
