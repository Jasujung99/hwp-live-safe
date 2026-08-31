"""Local-only, read-only personal-profile support.

Profile values are deliberately kept out of MCP responses.  The server reads a
selected value only while creating a private preview plan, then re-checks its
hash immediately before applying the plan.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


class ProfileError(RuntimeError):
    """A local profile is missing, malformed, or unsafe to type."""


ProfileSensitivity = Literal["personal", "contact", "professional", "other"]

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SENSITIVITIES = {"personal", "contact", "professional", "other"}


@dataclass(frozen=True)
class ProfileKey:
    profile_id: str
    profile_label: str
    key: str
    label: str
    sensitivity: ProfileSensitivity
    configured: bool


@dataclass(frozen=True)
class ResolvedProfileValue:
    profile_id: str
    profile_label: str
    key: str
    label: str
    sensitivity: ProfileSensitivity
    value: str
    value_hash: str


class ProfileStore:
    """Read profile JSON files from a user-local directory without writing them."""

    max_value_chars = 4_000

    def __init__(self, profile_dir: Path | None = None) -> None:
        self.profile_dir = profile_dir or self.default_profile_dir()

    @staticmethod
    def default_profile_dir() -> Path:
        # The old variable is accepted only for a smooth transition from the
        # pre-release name.  The new name takes precedence and is documented.
        configured = os.environ.get("HWP_LIVE_SAFE_PROFILE_DIR") or os.environ.get(
            "HWP_LIVE_PROFILE_DIR"
        )
        if configured:
            return Path(configured).expanduser()
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            root = Path(local_app_data)
        else:
            root = Path.home() / "AppData" / "Local"
        current = root / "HWP Live Safe" / "profiles"
        legacy = root / "HWP Live 2022" / "profiles"
        # A pre-release user should not lose access to an existing local profile
        # merely because the application name changed. New installations still
        # use the HWP Live Safe directory.
        if not current.exists() and legacy.is_dir():
            return legacy
        return current

    def list_keys(self) -> list[ProfileKey]:
        if not self.profile_dir.exists():
            return []
        if not self.profile_dir.is_dir():
            raise ProfileError("The configured HWP Live profile location is not a folder.")

        keys: list[ProfileKey] = []
        for path in sorted(self.profile_dir.glob("*.json"), key=lambda item: item.name.lower()):
            profile_id = path.stem
            self._validate_identifier(profile_id, "profile id")
            profile = self._read_profile(path, profile_id)
            fields = profile["fields"]
            for key in sorted(fields, key=str.lower):
                field = fields[key]
                value = field["value"]
                keys.append(
                    ProfileKey(
                        profile_id=profile_id,
                        profile_label=profile["label"],
                        key=key,
                        label=field["label"],
                        sensitivity=field["sensitivity"],
                        configured=isinstance(value, str) and bool(value.strip()),
                    )
                )
        return keys

    def resolve(self, profile_id: str, key: str) -> ResolvedProfileValue:
        self._validate_identifier(profile_id, "profile id")
        self._validate_identifier(key, "profile key")
        path = self.profile_dir / f"{profile_id}.json"
        try:
            path.resolve().relative_to(self.profile_dir.resolve())
        except ValueError as exc:
            raise ProfileError("The requested profile is outside the configured profile folder.") from exc
        if not path.is_file():
            raise ProfileError("The requested local profile does not exist.")
        profile = self._read_profile(path, profile_id)
        field = profile["fields"].get(key)
        if field is None:
            raise ProfileError("The requested key does not exist in that local profile.")
        value = field["value"]
        if value is None or not isinstance(value, str) or not value.strip():
            raise ProfileError("The requested local profile value has not been configured.")
        self._validate_value(value)
        value_hash = self._value_hash(profile_id, key, value)
        return ResolvedProfileValue(
            profile_id=profile_id,
            profile_label=profile["label"],
            key=key,
            label=field["label"],
            sensitivity=field["sensitivity"],
            value=value,
            value_hash=value_hash,
        )

    @classmethod
    def _value_hash(cls, profile_id: str, key: str, value: str) -> str:
        payload = f"{profile_id}\0{key}\0{value}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:20]

    def _read_profile(self, path: Path, expected_id: str) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProfileError("A local profile could not be read as UTF-8 JSON.") from exc
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise ProfileError("A local profile must use version 1.")
        label = raw.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ProfileError("A local profile needs a non-empty label of at most 80 characters.")
        fields = raw.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ProfileError("A local profile needs a non-empty fields object.")

        normalized: dict[str, dict[str, Any]] = {}
        for key, field in fields.items():
            if not isinstance(key, str):
                raise ProfileError("Every local profile key must be a string.")
            self._validate_identifier(key, "profile key")
            if not isinstance(field, dict):
                raise ProfileError("Every local profile field must be an object.")
            field_label = field.get("label", key)
            if not isinstance(field_label, str) or not field_label.strip() or len(field_label) > 80:
                raise ProfileError("Every local profile field needs a label of at most 80 characters.")
            sensitivity = field.get("sensitivity", "personal")
            if sensitivity not in _SENSITIVITIES:
                raise ProfileError("A local profile field has an unsupported sensitivity.")
            value = field.get("value")
            if value is not None and not isinstance(value, str):
                raise ProfileError("A local profile value must be a string or null.")
            if isinstance(value, str):
                self._validate_value(value)
            normalized[key] = {
                "label": field_label.strip(),
                "sensitivity": sensitivity,
                "value": value,
            }

        # expected_id is intentionally consumed here: it makes profile identity
        # validation explicit and prevents a file's arbitrary metadata from
        # selecting a different profile id.
        self._validate_identifier(expected_id, "profile id")
        return {"label": label.strip(), "fields": normalized}

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if not _IDENTIFIER.fullmatch(value):
            raise ProfileError(
                f"The {label} must use lowercase letters, digits, hyphens, or underscores."
            )

    def _validate_value(self, value: str) -> None:
        if len(value) > self.max_value_chars:
            raise ProfileError("A local profile value is too long to insert safely.")
        if "\x00" in value or "\x02" in value:
            raise ProfileError("A local profile value contains a reserved control character.")
