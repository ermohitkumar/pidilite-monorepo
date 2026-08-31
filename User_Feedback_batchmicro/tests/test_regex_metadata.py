import pytest
from services.api.routers.ingest import FILENAME_METADATA_PATTERN

def test_full_filename_extraction():
    filename = "MH_DivA_West_Cluster1_RBDM2_Mumbai_TSI001_FME002_TTY003_User99_Sales.mp3"
    match = FILENAME_METADATA_PATTERN.match(filename)
    assert match is not None
    data = match.groupdict()
    assert data == {
        "state": "MH",
        "division": "DivA",
        "zone": "West",
        "cluster": "Cluster1",
        "rbdm_cluster": "RBDM2",
        "town_city": "Mumbai",
        "tsi_territory_code": "TSI001",
        "fme_code": "FME002",
        "tty_code": "TTY003",
        "user_id": "User99",
        "user_type": "Sales"
    }

def test_missing_fields_extraction():
    # Only state, cluster, fme, and user are provided. Others are left blank with double/multiple underscores
    filename = "MH___Cluster1____FME002__User99_.wav"
    match = FILENAME_METADATA_PATTERN.match(filename)
    assert match is not None
    data = match.groupdict()
    assert data["state"] == "MH"
    assert data["division"] == ""
    assert data["zone"] == ""
    assert data["cluster"] == "Cluster1"
    assert data["rbdm_cluster"] == ""
    assert data["town_city"] == ""
    assert data["tsi_territory_code"] == ""
    assert data["fme_code"] == "FME002"
    assert data["tty_code"] == ""
    assert data["user_id"] == "User99"
    assert data["user_type"] == ""

def test_all_missing_fields():
    # Just 10 underscores and an extension
    filename = "__________.m4a"
    match = FILENAME_METADATA_PATTERN.match(filename)
    assert match is not None
    data = match.groupdict()
    assert all(value == "" for value in data.values())

def test_filename_with_spaces_and_special_chars():
    filename = "New York_Div-B_Zone C_Cluster (1)_RBDM/2_NY City_TSI-001_FME!@#_TTY$%^_User 99_Admin.ogg"
    match = FILENAME_METADATA_PATTERN.match(filename)
    assert match is not None
    data = match.groupdict()
    assert data["state"] == "New York"
    assert data["division"] == "Div-B"
    assert data["zone"] == "Zone C"
    assert data["cluster"] == "Cluster (1)"
    assert data["rbdm_cluster"] == "RBDM/2"
    assert data["town_city"] == "NY City"
    assert data["tsi_territory_code"] == "TSI-001"
    assert data["user_type"] == "Admin"

def test_failure_too_few_underscores():
    filename = "state_division_zone.mp3"
    match = FILENAME_METADATA_PATTERN.match(filename)
    assert match is None

def test_failure_too_many_underscores():
    # Because of `[^_]*`, providing more underscores than expected will cause it to fail matching the extension
    filename = "1_2_3_4_5_6_7_8_9_10_11_12.mp3"
    match = FILENAME_METADATA_PATTERN.match(filename)
    assert match is None
