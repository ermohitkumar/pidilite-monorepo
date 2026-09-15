"""Resolve report filters from DW masters using audio filename keys.

Join path:
    sitenumber  → FactSitedetails.siteNumber
    visit sfid  → FactEvent.Id
    BDE code    → DimHierarchy.SH2Code (also FactSitedetails.CMDICode)
    membership  → Dimmember.MembershipNo / FactEvent.MembershipNo
    SiteId      → FactEvent.EndUserSite
    AdditionEventFieldID → Factadditionalevent.Id
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, OperationalError
from sqlalchemy.orm import Session

from services.shared.filename_metadata import (
    merge_metadata,
    parse_audio_filename,
    parsed_to_file_fields,
)

logger = logging.getLogger(__name__)

_GCS_FILTER_KEYS = (
    "state",
    "division",
    "zone",
    "cluster",
    "rfmm_cluster",
    "rbdm_cluster",
    "town_city",
    "tsi_territory_code",
    "fme_code",
    "tty_code",
    "user_id",
    "user_type",
    "data_source",
    "site_number",
    "membership_no",
    "bde_code",
    "visit_sfid",
    "cmdi_code",
    "site_id",
    "additional_event_id",
)


def _scalar_row(db: Session, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        row = db.execute(text(sql), params).mappings().first()
    except (ProgrammingError, OperationalError) as exc:
        db.rollback()
        logger.debug("DW lookup skipped: %s", exc)
        return None
    return dict(row) if row else None


def lookup_hierarchy(db: Session, bde_code: str | None) -> dict[str, Any]:
    if not bde_code:
        return {}
    row = _scalar_row(
        db,
        """
        SELECT
            NULLIF(TRIM(h."SH2Code"), '') AS fme_code,
            NULLIF(TRIM(h."SH2Name"), '') AS fme_name,
            COALESCE(NULLIF(TRIM(h."SH7Name"), ''), NULLIF(TRIM(h."SH7Code"), '')) AS division,
            NULLIF(TRIM(h."SH7Code"), '') AS division_code,
            COALESCE(NULLIF(TRIM(h."SH5Name"), ''), NULLIF(TRIM(h."SH5Code"), '')) AS zone,
            COALESCE(
                NULLIF(TRIM(h."SH3Name"), ''),
                NULLIF(TRIM(h."ClusterDescription"), ''),
                NULLIF(TRIM(h."SH3Code"), '')
            ) AS rfmm_cluster,
            COALESCE(NULLIF(TRIM(h."ClusterCode"), ''), NULLIF(TRIM(h."ClusterDescription"), '')) AS cluster,
            NULLIF(TRIM(h."WSSTerritoryCode"), '') AS tty_code,
            NULLIF(TRIM(h."WSSTerritoryName"), '') AS town_city,
            NULLIF(TRIM(h."divisioncode"), '') AS site_division
        FROM "DimHierarchy" h
        WHERE h."SH2Code" = :bde
        LIMIT 1
        """,
        {"bde": bde_code},
    )
    if not row:
        return {}
    return {
        "fme_code": row.get("fme_code") or bde_code,
        "bde_code": row.get("fme_code") or bde_code,
        "division": row.get("division"),
        "zone": row.get("zone"),
        "rfmm_cluster": row.get("rfmm_cluster"),
        "cluster": row.get("cluster"),
        "tty_code": row.get("tty_code"),
        "town_city": row.get("town_city"),
        "tsi_territory_code": row.get("tty_code"),
    }


def lookup_site(db: Session, site_number: str | None) -> dict[str, Any]:
    if not site_number:
        return {}
    row = _scalar_row(
        db,
        """
        SELECT
            NULLIF(TRIM("siteNumber"), '') AS site_number,
            NULLIF(TRIM("SiteId"), '') AS site_id,
            NULLIF(TRIM("CMDICode"), '') AS cmdi_code,
            NULLIF(TRIM("CMDITSITag"), '') AS user_type,
            NULLIF(TRIM("MemberId"), '') AS membership_no,
            NULLIF(TRIM("SiteDivision"), '') AS site_division,
            NULLIF(TRIM("Cluster"), '') AS cluster,
            NULLIF(TRIM("SiteLocation"), '') AS site_location
        FROM "FactSitedetails"
        WHERE "siteNumber" = :site_number
        LIMIT 1
        """,
        {"site_number": site_number},
    )
    if not row:
        return {}
    out = {
        "site_number": row.get("site_number") or site_number,
        "site_id": row.get("site_id"),
        "cmdi_code": row.get("cmdi_code"),
        "user_type": row.get("user_type"),
        "membership_no": row.get("membership_no"),
    }
    if row.get("cluster"):
        out["cluster"] = row["cluster"]
    return out


def lookup_event(db: Session, visit_sfid: str | None) -> dict[str, Any]:
    if not visit_sfid:
        return {}
    row = _scalar_row(
        db,
        """
        SELECT
            NULLIF(TRIM("Id"), '') AS visit_sfid,
            NULLIF(TRIM("EndUserSite"), '') AS site_id,
            COALESCE(NULLIF(TRIM("MembershipNo"), ''), NULLIF(TRIM("MembershipNumber"), '')) AS membership_no,
            NULLIF(TRIM("CMDICode"), '') AS cmdi_code,
            NULLIF(TRIM("CMDITsitag"), '') AS user_type,
            NULLIF(TRIM("AdditionEventFieldID"), '') AS additional_event_id
        FROM "FactEvent"
        WHERE "Id" = :visit_sfid
        LIMIT 1
        """,
        {"visit_sfid": visit_sfid},
    )
    if not row:
        return {}
    return {k: v for k, v in row.items() if v}


def lookup_member(db: Session, membership_no: str | None) -> dict[str, Any]:
    if not membership_no:
        return {}
    row = _scalar_row(
        db,
        """
        SELECT
            NULLIF(TRIM("MembershipNo"), '') AS membership_no,
            NULLIF(TRIM("EndUserType"), '') AS end_user_type,
            NULLIF(TRIM("MDICode"), '') AS mdi_code,
            NULLIF(TRIM("DivisionName"), '') AS division_name
        FROM "Dimmember"
        WHERE "MembershipNo" = :membership_no
        LIMIT 1
        """,
        {"membership_no": membership_no},
    )
    return dict(row) if row else {}


def lookup_dw_filters(db: Session, parsed: dict[str, Any]) -> dict[str, Any]:
    site = lookup_site(db, parsed.get("site_number"))
    event = lookup_event(db, parsed.get("visit_sfid"))
    hierarchy = lookup_hierarchy(db, parsed.get("bde_code"))
    member = lookup_member(
        db,
        event.get("membership_no") or site.get("membership_no") or parsed.get("membership_no"),
    )
    # Hierarchy is the official Division / Zone / RFMM / BDE path.
    # Site + event supply visit keys (CMDI, SiteId / EndUserSite, membership).
    return merge_metadata(member, site, event, hierarchy)


def gcs_metadata_fields(custom_meta: dict[str, Any] | None) -> dict[str, Any]:
    if not custom_meta:
        return {}
    out: dict[str, Any] = {}
    for key in _GCS_FILTER_KEYS:
        value = custom_meta.get(key)
        if value not in (None, ""):
            out[key] = value
    if custom_meta.get("rbdm_cluster") and not out.get("rfmm_cluster"):
        out["rfmm_cluster"] = custom_meta["rbdm_cluster"]
    return out


def resolve_file_metadata(
    db: Session,
    file_name: str,
    custom_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Filename parse → DW masters → GCS object metadata (later wins)."""
    parsed = parse_audio_filename(file_name)
    dw = lookup_dw_filters(db, parsed) if parsed else {}
    return merge_metadata(
        parsed_to_file_fields(parsed),
        dw,
        gcs_metadata_fields(custom_meta),
    )
