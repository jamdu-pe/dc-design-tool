"""사용자 카탈로그 등록 테스트 (웹 UI 랙 추가의 저장 로직)."""
import pytest
import yaml
from pydantic import ValidationError

from dc_design_tool.engine import catalog
from dc_design_tool.engine.catalog import append_user_block, load_blocks
from dc_design_tool.engine.models import Spec
from dc_design_tool.engine.sizing import size

VALID = {
    "id": "acme_test_rack", "type": "rack", "vendor": "ACME", "model": "TEST-1",
    "interface": {"power_kw_typical": 150.0, "liquid_fraction": 0.9,
                  "accel_count": 64, "supply_water_c": 32, "footprint_m2": 1.3,
                  "weight_kg": 1400, "scaleout_ports": 64, "port_speed_gbps": 800},
    "as_of_date": "2026-08", "confidence": "vendor",
    "source_url": "https://example.com/datasheet",
}


@pytest.fixture
def user_file(tmp_path, monkeypatch):
    """사용자 카탈로그를 임시 경로로 돌려 실제 data/ 를 건드리지 않는다."""
    path = tmp_path / "user_racks.yaml"
    monkeypatch.setattr(catalog, "USER_DATA", path)
    return path


# ---------- 정상 등록 ----------

def test_creates_file_with_header_on_first_write(user_file):
    append_user_block(VALID)
    text = user_file.read_text(encoding="utf-8")
    assert text.startswith("#")
    assert "source_url" in text


def test_saved_block_round_trips_through_yaml(user_file):
    append_user_block(VALID)
    items = yaml.safe_load(user_file.read_text(encoding="utf-8"))
    assert len(items) == 1
    assert items[0]["id"] == "acme_test_rack"
    assert items[0]["interface"]["power_kw_typical"] == 150.0


def test_second_block_is_appended_and_first_is_kept(user_file):
    append_user_block(VALID)
    append_user_block({**VALID, "id": "acme_test_rack_2", "model": "TEST-2"})
    items = yaml.safe_load(user_file.read_text(encoding="utf-8"))
    assert [i["id"] for i in items] == ["acme_test_rack", "acme_test_rack_2"]


def test_returns_validated_block(user_file):
    block = append_user_block(VALID)
    assert block.id == "acme_test_rack"
    assert block.interface.power_kw_typical == 150.0


# ---------- 로더 규칙 강제 ----------

def test_missing_source_url_is_rejected(user_file):
    bad = {**VALID, "source_url": ""}
    with pytest.raises(ValueError, match="source_url"):
        append_user_block(bad)
    assert not user_file.exists()


def test_whitespace_only_source_url_is_rejected(user_file):
    with pytest.raises(ValueError, match="source_url"):
        append_user_block({**VALID, "source_url": "   "})


def test_duplicate_id_against_shipped_catalog_is_rejected(user_file):
    with pytest.raises(ValueError, match="중복 블록 id"):
        append_user_block({**VALID, "id": "nvidia_gb200_nvl72"})


def test_duplicate_id_within_user_file_is_rejected(user_file):
    append_user_block(VALID)
    with pytest.raises(ValueError, match="중복 블록 id"):
        append_user_block(VALID)


def test_invalid_field_type_raises_validation_error(user_file):
    bad = {**VALID, "interface": {**VALID["interface"], "power_kw_typical": "많이"}}
    with pytest.raises(ValidationError):
        append_user_block(bad)


def test_unknown_block_type_raises_validation_error(user_file):
    with pytest.raises(ValidationError):
        append_user_block({**VALID, "type": "spaceship"})


# ---------- 실제 카탈로그 반영 ----------

def test_registered_rack_is_loaded_by_load_blocks(tmp_path, monkeypatch):
    """사용자 파일을 data/ 에 두면 load_blocks 가 코드 수정 없이 읽는다."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for src in catalog.DATA.glob("*.yaml"):
        (data_dir / src.name).write_text(src.read_text(encoding="utf-8"),
                                         encoding="utf-8")
    monkeypatch.setattr(catalog, "DATA", data_dir)
    monkeypatch.setattr(catalog, "USER_DATA", data_dir / "user_racks.yaml")

    append_user_block(VALID)
    blocks = load_blocks()
    assert "acme_test_rack" in blocks
    assert blocks["acme_test_rack"].vendor == "ACME"


def test_registered_rack_can_be_sized(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for src in catalog.DATA.glob("*.yaml"):
        (data_dir / src.name).write_text(src.read_text(encoding="utf-8"),
                                         encoding="utf-8")
    monkeypatch.setattr(catalog, "DATA", data_dir)
    monkeypatch.setattr(catalog, "USER_DATA", data_dir / "user_racks.yaml")

    append_user_block(VALID)
    r = size(Spec(rack_id="acme_test_rack", it_power_mw=3.0), load_blocks())
    assert r.rack_count == 20            # ceil(3000/150)
    assert r.it_power_kw == 3000.0
