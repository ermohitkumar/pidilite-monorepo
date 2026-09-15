"""Parse M-Power GCS audio filenames into visit metadata.

Pattern:
    sitenumber-MembershipNo-BDEcode-VisitSfid-timeofsaving.extension

Example:
    4401427-105231111924433-BDDEL03-00Ufw00000T3PfWEAV-1784221654.webm
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# Optional spaces around '-' so both GCS objects and the human-readable
# "sitenumber - Membership No- BDE code- …" form parse the same way.
FILENAME_METADATA_PATTERN = re.compile(
    r"^(?P<site_number>\d+)\s*-\s*"
    r"(?P<membership_no>\d+)\s*-\s*"
    r"(?P<bde_code>[A-Za-z0-9]+)\s*-\s*"
    r"(?P<visit_sfid>[A-Za-z0-9]+)\s*-\s*"
    r"(?P<saved_epoch>\d+)"
    r"\.(?P<extension>[A-Za-z0-9]+)$"
)


def parse_audio_filename(file_name: str | None) -> dict[str, Any] | None:
    """Return named groups from a basename, or None if the pattern does not match."""
    if not file_name:
        return None
    basename = str(file_name).rsplit("/", 1)[-1].strip()
    match = FILENAME_METADATA_PATTERN.match(basename)
    if not match:
        return None
    data = match.groupdict()
    epoch = _parse_epoch(data.get("saved_epoch"))
    data["saved_at"] = epoch
    data["call_date"] = epoch
    return data


def _parse_epoch(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    # 13-digit values are milliseconds; 10-digit are seconds.
    if value > 10_000_000_000:
        value = value / 1000
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def parsed_to_file_fields(parsed: dict[str, Any] | None) -> dict[str, Any]:
    """Map filename groups onto FileDetails / GCS metadata keys."""
    if not parsed:
        return {}
    return {
        "site_number": parsed.get("site_number"),
        "membership_no": parsed.get("membership_no"),
        "bde_code": parsed.get("bde_code"),
        "visit_sfid": parsed.get("visit_sfid"),
        "fme_code": parsed.get("bde_code"),
        "cmdi_code": parsed.get("bde_code"),
        "call_date": parsed.get("call_date"),
        "user_type": "BDE",
    }


def merge_metadata(*sources: dict[str, Any] | None) -> dict[str, Any]:
    """Left-to-right merge; later non-empty values win."""
    merged: dict[str, Any] = {}
    for source in sources:
        if not source:
            continue
        for key, value in source.items():
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            merged[key] = value
    return merged
