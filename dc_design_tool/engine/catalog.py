"""YAML 카탈로그/규칙 로더 + 검증 + 사용자 카탈로그 등록."""
from __future__ import annotations

import copy
import pathlib
from typing import Any, Optional

import yaml

from .models import Block

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RULES = ROOT / "rules"
REGIONS = RULES / "regions"
USER_DATA = DATA / "user_racks.yaml"

USER_DATA_HEADER = """\
# 사용자 추가 카탈로그 (웹 UI 또는 catalog.append_user_block 으로 생성).
#
# 배포본 카탈로그(racks.yaml 등)와 분리해 관리한다. data/*.yaml 은 모두 자동 로드되므로
# 이 파일에 추가한 블록은 CLI·UI 양쪽에서 즉시 보인다.
# 각 항목은 as_of_date / confidence / source_url 이 필수다(CLAUDE.md 절대규칙 2).
"""


def load_blocks() -> dict[str, Block]:
    """data/*.yaml 의 모든 블록을 검증 로드. id 중복은 오류."""
    blocks: dict[str, Block] = {}
    for f in sorted(DATA.glob("*.yaml")):
        items = yaml.safe_load(f.read_text(encoding="utf-8")) or []
        for raw in items:
            b = Block(**raw)
            if b.id in blocks:
                raise ValueError(f"중복 블록 id: {b.id} ({f.name})")
            if not b.source_url:
                raise ValueError(f"{b.id}: source_url 누락")
            blocks[b.id] = b
    return blocks


def get_block(blocks: dict[str, Block], block_id: str) -> Block:
    if block_id not in blocks:
        raise KeyError(f"카탈로그 부재: '{block_id}' — data/*.yaml 에 블록 추가 필요")
    return blocks[block_id]


# ---------- 역할(subtype)별 후보 조회 · 선택 ----------

def list_candidates(type_: str, subtype: str,
                    blocks: Optional[dict[str, Block]] = None) -> list[Block]:
    """해당 역할을 맡을 수 있는 블록 후보를 카탈로그 등재 순서대로 반환한다.

    순서는 표시 순서일 뿐이고, 기본 선택은 `default: true` 플래그가 정한다
    (`resolve` 참고).

    조건에 맞는 블록이 없으면 예외가 아니라 빈 목록을 준다(UI 가 "후보 없음"을
    그릴 수 있어야 한다). 실제 사용 시점의 부재 판정은 `resolve`가 한다.
    """
    blocks = blocks if blocks is not None else load_blocks()
    return [b for b in blocks.values()
            if b.type == type_ and b.subtype == subtype]


def resolve(type_: str, subtype: str, blocks: dict[str, Block],
            selections: Optional[dict[str, str]] = None) -> Block:
    """역할에 쓸 블록을 정한다. 선택이 있으면 그것을, 없으면 기본 블록을 쓴다.

    기본 블록은 `default: true` 가 붙은 후보다. 플래그가 하나도 없으면 첫 후보로
    폴백한다(테스트가 주입하는 임시 카탈로그를 위한 것이며, 배포 카탈로그는
    tests/test_selection.py 가 모든 역할에 플래그를 강제한다).

    블록을 고르기만 하고 어떤 계산도 하지 않는다. 수량·용량은 호출한 도메인
    엔진이 `calc.*` 로 재산정한다(CLAUDE.md 절대규칙 1).

    Args:
        type_: 블록 종류(cooling|electrical|network).
        subtype: 역할(ups, cdu, leaf 등).
        blocks: 카탈로그.
        selections: 역할 → block_id. 해당 역할 키가 없으면 기본 블록을 쓴다.

    Raises:
        KeyError: 후보가 하나도 없거나, 지정한 id 가 없거나, 그 id 의 역할이
            요청한 역할과 다를 때(후보 목록을 메시지에 담는다).
    """
    candidates = list_candidates(type_, subtype, blocks)
    if not candidates:
        raise KeyError(f"카탈로그 부재: {type_}/{subtype} — "
                       f"data/{type_}.yaml 에 블록 추가 필요")

    chosen_id = (selections or {}).get(subtype)
    if not chosen_id:
        return next((b for b in candidates if b.default), candidates[0])

    for block in candidates:
        if block.id == chosen_id:
            return block
    raise KeyError(f"선택 불가: 역할 '{subtype}' 에 '{chosen_id}' — 후보: "
                   f"{', '.join(b.id for b in candidates)}")


# ---------- 규칙 · 지역 규격 팩 ----------

def _deep_merge(base: dict, override: dict) -> dict:
    """override 를 base 위에 재귀 병합. base 는 변경하지 않고 새 dict 를 만든다."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def available_regions() -> list[str]:
    """사용 가능한 규격 팩 코드 목록."""
    return sorted(p.stem for p in REGIONS.glob("*.yaml"))


def load_region(code: str) -> dict:
    """지역 규격 팩 로드.

    Raises:
        KeyError: 정의되지 않은 지역 코드.
    """
    path = REGIONS / f"{code}.yaml"
    if not path.is_file():
        raise KeyError(f"규격 팩 부재: '{code}' — 사용 가능: "
                       f"{', '.join(available_regions())}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_rule(name: str, region: Optional[str] = None) -> dict:
    """규칙 파일 로드. region 을 주면 해당 규격 팩의 오버라이드를 병합한다.

    Args:
        name: 규칙 파일명(예: "electrical.yaml").
        region: 지역 규격 팩 코드(예: "KR"). None 이면 기본 규칙 그대로.

    Raises:
        KeyError: 정의되지 않은 지역 코드.
    """
    base = yaml.safe_load((RULES / name).read_text(encoding="utf-8"))
    if not region:
        return base
    overrides = load_region(region).get("overrides") or {}
    return _deep_merge(base, overrides.get(name.rsplit(".", 1)[0], {}))


# ---------- 사용자 카탈로그 등록 ----------

def append_user_block(raw: dict[str, Any],
                      path: Optional[pathlib.Path] = None) -> Block:
    """사용자 입력 블록을 검증해 사용자 카탈로그에 추가하고 검증된 Block 을 반환한다.

    로더(`load_blocks`)와 동일한 규칙을 등록 시점에 강제한다.

    Raises:
        pydantic.ValidationError: 필드 타입·필수값 위반.
        ValueError: source_url 누락 또는 기존 카탈로그와 id 충돌.
    """
    path = path or USER_DATA
    block = Block(**raw)
    if not (block.source_url or "").strip():
        raise ValueError(f"{block.id}: source_url 누락 — 출처 없는 사양은 등록할 수 없다")

    existing = load_blocks()
    if block.id in existing:
        raise ValueError(f"중복 블록 id: {block.id} — 기존 카탈로그에 이미 있다")

    items = []
    if path.is_file():
        items = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if any(item.get("id") == block.id for item in items):
            raise ValueError(f"중복 블록 id: {block.id} ({path.name})")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(USER_DATA_HEADER, encoding="utf-8")

    items.append(block.model_dump(exclude_none=True, exclude_defaults=False))
    body = yaml.safe_dump(items, allow_unicode=True, sort_keys=False)
    path.write_text(USER_DATA_HEADER + body, encoding="utf-8")
    return block
