from unittest.mock import MagicMock

from services.shared.dw_lookup import merge_metadata, resolve_file_metadata
from services.shared.filename_metadata import parsed_to_file_fields, parse_audio_filename


def test_resolve_uses_filename_when_dw_tables_missing():
    db = MagicMock()
    db.execute.side_effect = Exception("should be caught by lookup helpers")
    # ProgrammingError path is inside lookup; force empty lookups via rollback path.
    from sqlalchemy.exc import ProgrammingError

    db.execute.side_effect = ProgrammingError("SELECT", {}, Exception("no table"))

    name = "4401427-105231111924433-BDDEL03-00Ufw00000T3PfWEAV-1784221654.webm"
    resolved = resolve_file_metadata(db, name, {})
    assert resolved["site_number"] == "4401427"
    assert resolved["visit_sfid"] == "00Ufw00000T3PfWEAV"
    assert resolved["fme_code"] == "BDDEL03"
    assert resolved["user_type"] == "BDE"


def test_merge_prefers_hierarchy_then_gcs():
    parsed = parsed_to_file_fields(
        parse_audio_filename(
            "4401427-105231111924433-BDDEL03-00Ufw00000T3PfWEAV-1784221654.webm"
        )
    )
    hierarchy = {
        "division": "FV-RETAIL-NSM",
        "zone": "FV-DELHI NCR ZONE",
        "rfmm_cluster": "RBDM-DELHI-1",
        "fme_code": "BDDEL03",
    }
    gcs = {"zone": "Overridden Zone"}
    merged = merge_metadata(parsed, hierarchy, gcs)
    assert merged["division"] == "FV-RETAIL-NSM"
    assert merged["zone"] == "Overridden Zone"
    assert merged["rfmm_cluster"] == "RBDM-DELHI-1"
    assert merged["site_number"] == "4401427"
