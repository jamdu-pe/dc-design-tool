"""통신(ICT) 사이징: GPU 스케일아웃 포트 → leaf/spine 대수 → 트랜시버·케이블 BOM.

패브릭 계수는 `rules/network.yaml`에서 읽는다(하드코딩 금지).
"""
from __future__ import annotations

import math
from typing import Optional

from .catalog import load_rule, resolve
from .models import Block, LineItem, Spec


def scaleout_port_count(rack_count: int, ports_per_rack: int) -> int:
    """총 스케일아웃 호스트 포트 수."""
    return rack_count * ports_per_rack


def downlinks_per_leaf(leaf_ports: int, oversubscription: float) -> int:
    """leaf 1대의 다운링크(호스트향) 포트 수.

    오버섭스크립션 k(다운:업 = k:1)일 때 다운링크 = ports × k/(k+1).

    Raises:
        ValueError: 포트 수 또는 오버섭스크립션이 0 이하일 때.
    """
    if leaf_ports <= 0:
        raise ValueError("leaf 포트 수는 0보다 커야 함")
    if oversubscription <= 0:
        raise ValueError("오버섭스크립션 비는 0보다 커야 함")
    down = int(leaf_ports * oversubscription / (oversubscription + 1))
    if down <= 0:
        raise ValueError("다운링크 포트가 0 — 포트 수/오버섭스크립션 조합 확인 필요")
    return down


def leaf_count(total_ports: int, leaf_ports: int, oversubscription: float) -> int:
    """호스트 포트를 모두 수용하는 leaf 대수."""
    return max(1, math.ceil(total_ports / downlinks_per_leaf(leaf_ports, oversubscription)))


def uplink_count(total_ports: int, oversubscription: float) -> int:
    """leaf→spine 업링크 총수 = 호스트 포트 / 오버섭스크립션.

    Raises:
        ValueError: 오버섭스크립션이 0 이하일 때.
    """
    if oversubscription <= 0:
        raise ValueError("오버섭스크립션 비는 0보다 커야 함")
    return math.ceil(total_ports / oversubscription)


def spine_count(total_ports: int, spine_ports: int, oversubscription: float) -> int:
    """업링크를 수용하는 spine 대수.

    Raises:
        ValueError: spine 포트 수가 0 이하일 때.
    """
    if spine_ports <= 0:
        raise ValueError("spine 포트 수는 0보다 커야 함")
    return max(1, math.ceil(uplink_count(total_ports, oversubscription) / spine_ports))


def transceiver_count(host_links: int, fabric_links: int, ends_per_link: int = 2,
                      spare_ratio: float = 0.05) -> int:
    """트랜시버 수량 = (호스트링크 + 패브릭링크) × 양단 × (1 + 예비율)."""
    return math.ceil((host_links + fabric_links) * ends_per_link * (1 + spare_ratio))


def cable_count(host_links: int, fabric_links: int, spare_ratio: float = 0.05) -> int:
    """광케이블 수량 = 링크 수 × (1 + 예비율)."""
    return math.ceil((host_links + fabric_links) * (1 + spare_ratio))


def size_network(rack_count: int, rack: Block, spec: Optional[Spec],
                 blocks: dict[str, Block], rules: Optional[dict] = None,
                 selections: Optional[dict[str, str]] = None
                 ) -> tuple[dict, list[LineItem]]:
    """통신 사이징 결과(dict)와 BOM(list) 반환.

    Args:
        selections: 역할 → block_id. `leaf`·`spine`·`transceiver` 를 교체할 수
            있다. 미지정 역할은 카탈로그 첫 후보를 쓴다. 교체해도 대수·링크 수는
            위 순수 함수들로 재산정한다.

    Raises:
        KeyError: leaf/spine/트랜시버 블록이 카탈로그에 없거나 선택한 id 가
            유효하지 않을 때.
    """
    r = rules or load_rule("network.yaml", spec.region if spec else None)
    fab, cab = r["fabric"], r["cabling"]
    oversub = fab["oversubscription"]

    leaf_sw = resolve("network", "leaf", blocks, selections)
    spine_sw = resolve("network", "spine", blocks, selections)
    xcvr = resolve("network", "transceiver", blocks, selections)

    ports_per_rack = rack.interface.scaleout_ports or 0
    total_ports = scaleout_port_count(rack_count, ports_per_rack)
    if total_ports <= 0:
        raise ValueError(f"{rack.id}: scaleout_ports 미정의 — 랙 블록 인터페이스 확인 필요")

    n_leaf = leaf_count(total_ports, leaf_sw.interface.ports, oversub)
    n_spine = spine_count(total_ports, spine_sw.interface.ports, oversub)
    fabric_links = uplink_count(total_ports, oversub)
    n_xcvr = transceiver_count(total_ports, fabric_links,
                               cab["ends_per_link"], cab["spare_ratio"])
    n_cable = cable_count(total_ports, fabric_links, cab["spare_ratio"])

    speed = rack.interface.port_speed_gbps
    result = {
        "topology": fab["topology"],
        "oversubscription": oversub,
        "scaleout_ports": total_ports,
        "port_speed_gbps": speed,
        "leaf_qty": n_leaf,
        "spine_qty": n_spine,
        "fabric_link_qty": fabric_links,
        "transceiver_qty": n_xcvr,
        "cable_qty": n_cable,
        "fabric_bandwidth_tbps": round(total_ports * (speed or 0) / 1000.0, 1),
        "selected": {"leaf": leaf_sw.id, "spine": spine_sw.id,
                     "transceiver": xcvr.id},
    }

    bom = [
        LineItem(domain="통신", item="Leaf 스위치", model=leaf_sw.model, block_id=leaf_sw.id,
                 unit_capacity=f"{leaf_sw.interface.ports}p x {leaf_sw.interface.port_speed_gbps}G",
                 qty=n_leaf, note=f"오버섭 {oversub}:1"),
        LineItem(domain="통신", item="Spine 스위치", model=spine_sw.model, block_id=spine_sw.id,
                 unit_capacity=f"{spine_sw.interface.ports}p x {spine_sw.interface.port_speed_gbps}G",
                 qty=n_spine, note=fab["topology"]),
        LineItem(domain="통신", item="트랜시버", model=xcvr.model, block_id=xcvr.id,
                 unit_capacity=f"{xcvr.interface.port_speed_gbps}G", qty=n_xcvr,
                 note=f"예비 {int(cab['spare_ratio'] * 100)}%"),
        LineItem(domain="통신", item="광케이블", model=xcvr.model, block_id=xcvr.id,
                 unit_capacity=f"1 link ({cab['media']})", qty=n_cable,
                 note=f"호스트 {total_ports} + 패브릭 {fabric_links}"),
    ]
    if speed and leaf_sw.interface.port_speed_gbps and speed != leaf_sw.interface.port_speed_gbps:
        bom[0].note += f" / 랙 포트속도 {speed}G ≠ 스위치 {leaf_sw.interface.port_speed_gbps}G"

    return result, bom
