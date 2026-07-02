from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChromeProfile:
    directory: str
    name: str
    email: str
    last_used: bool


def default_chrome_user_data_dir() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA nao esta definido neste Windows.")
    return Path(local_app_data) / "Google" / "Chrome" / "User Data"


def list_chrome_profiles(user_data_dir: str | Path | None = None) -> list[ChromeProfile]:
    root = Path(user_data_dir) if user_data_dir else default_chrome_user_data_dir()
    local_state_path = root / "Local State"
    if not local_state_path.exists():
        raise RuntimeError(f"Nao encontrei Local State em {local_state_path}.")

    data = json.loads(local_state_path.read_text(encoding="utf-8", errors="ignore"))
    profile_data = data.get("profile", {})
    info_cache = profile_data.get("info_cache", {})
    last_used = profile_data.get("last_used")

    profiles: list[ChromeProfile] = []
    for directory, info in sorted(info_cache.items()):
        profiles.append(
            ChromeProfile(
                directory=directory,
                name=str(info.get("name") or info.get("shortcut_name") or ""),
                email=str(info.get("user_name") or ""),
                last_used=directory == last_used,
            )
        )
    return profiles

