from datetime import datetime, timezone

from services.api.routers.ingest import FILENAME_METADATA_PATTERN
from services.shared.filename_metadata import parse_audio_filename, parsed_to_file_fields


def test_full_filename_extraction():
    filename = "4401427-105231111924433-BDDEL03-00Ufw00000T3PfWEAV-1784221654.webm"
    match = FILENAME_METADATA_PATTERN.match(filename)
    assert match is not None
    data = match.groupdict()
    assert data == {
        "site_number": "4401427",
        "membership_no": "105231111924433",
        "bde_code": "BDDEL03",
        "visit_sfid": "00Ufw00000T3PfWEAV",
        "saved_epoch": "1784221654",
        "extension": "webm",
    }


def test_filename_allows_spaces_around_dashes():
    filename = "4401427 - 105231111924433- BDDEL03- 00Ufw00000T3PfWEAV- 1784221654.webm"
    parsed = parse_audio_filename(filename)
    assert parsed is not None
    assert parsed["site_number"] == "4401427"
    assert parsed["bde_code"] == "BDDEL03"
    assert parsed["visit_sfid"] == "00Ufw00000T3PfWEAV"


def test_parse_sets_call_date_from_epoch():
    parsed = parse_audio_filename(
        "4401427-105231111924433-BDDEL03-00Ufw00000T3PfWEAV-1784221654.webm"
    )
    assert parsed is not None
    assert parsed["call_date"] == datetime.fromtimestamp(1784221654, tz=timezone.utc)
    fields = parsed_to_file_fields(parsed)
    assert fields["fme_code"] == "BDDEL03"
    assert fields["cmdi_code"] == "BDDEL03"
    assert fields["user_type"] == "BDE"


def test_sample_basename_from_path():
    parsed = parse_audio_filename(
        "gs://pidilite-raw-audio/test02/4552156-105230711555609-BDHYD05-00Ufw00000SIoaxEAD-1785653877.webm"
    )
    assert parsed is not None
    assert parsed["site_number"] == "4552156"
    assert parsed["bde_code"] == "BDHYD05"


def test_failure_old_underscore_pattern():
    filename = "MH_DivA_West_Cluster1_RBDM2_Mumbai_TSI001_FME002_TTY003_User99_Sales.mp3"
    assert FILENAME_METADATA_PATTERN.match(filename) is None
    assert parse_audio_filename(filename) is None


def test_failure_too_few_parts():
    filename = "4401427-BDDEL03.webm"
    assert FILENAME_METADATA_PATTERN.match(filename) is None
