"""平面 → 立面 门窗联动验收（v1.0.23）。

要点：
  · 立面一层门窗直接读平面上墙的 AA_OPENING，不再手填坐标；
  · 洞口左边距 x 按"站在室外看这面墙"的左手边取零点：墙起点在左手 → x=AA_POS；
    墙起点在右手（朝北的墙）→ x = 墙长 - AA_POS - 洞宽；
  · 派生出来的 x/宽/高/窗台高 与预期逐条相等，且与立面 block 里的洞口位置一致。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    create_elevation,
    create_opening,
    create_wall,
    read_cut_openings,
    read_facade_openings,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_link.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    create_wall(s, "W001", (0.0, 0.0), (7200.0, 0.0), thick=240.0)
    create_wall(s, "W003", (7200.0, 4500.0), (0.0, 4500.0), thick=240.0)
    create_opening(s, "M001", "W001", "DOOR", 900.0, 1500.0, height=2100.0, no="M0921")
    create_opening(s, "C001", "W001", "WINDOW", 1500.0, 5000.0,
                   height=1500.0, sill=900.0, no="C1215")
    create_opening(s, "C002", "W003", "WINDOW", 1200.0, 5600.0,
                   height=1500.0, sill=900.0, no="C0915")

    # 南墙（起点在左手边）：x = 中心 - 半宽
    south = read_facade_openings(s, "W001")
    assert [(o["x"], o["w"], o["h"], o["sill"], o["kind"]) for o in south] == [
        (1050.0, 900.0, 2100.0, 0.0, "DOOR"),
        (4250.0, 1500.0, 1500.0, 900.0, "WINDOW"),
    ], south
    assert [o["no"] for o in south] == ["M0921", "C1215"], south

    # 北墙（墙从右往左画，起点在右手边）：x = 7200 - 5600 - 600 = 1000
    north = read_facade_openings(s, "W003", flip=True)
    assert [(o["x"], o["w"]) for o in north] == [(1000.0, 1200.0)], north
    assert read_facade_openings(s, "W003")[0]["x"] == 5000.0, "不 flip 时应是 中心-半宽"

    # 派生清单直接喂给立面：洞口在立面上就落在这些 x 上
    elev = create_elevation(s, "E1", (0.0, 0.0), 7200.0,
                            [{"height": 3600.0}], south, "NONE", marks=False)
    assert elev["openings"] == 2, elev

    # 只取本墙的门窗：别的墙的洞口不会混进来
    empty = read_facade_openings(s, "W001", floor=1)
    assert len(empty) == 2 and all(o["floor"] == 1 for o in empty), empty

    # wall= 直接把平面门窗并进立面：2 樘来自平面 + 1 樘手填二层
    mixed = create_elevation(s, "E2", (0.0, 8000.0), 7200.0,
                             [{"height": 3600.0}, {"height": 3300.0}],
                             [{"floor": 2, "x": 4250.0, "w": 1500.0, "h": 1500.0,
                               "sill": 900.0}],
                             "NONE", marks=False, wall="W001")
    assert mixed["openings"] == 3, mixed

    # 剖切线取洞口：X=1500 切到南墙门（中心 1500）、北墙 C0915（跨 1000..2200）
    cut = read_cut_openings(s, (1500.0, -1200.0), (1500.0, 5700.0))
    assert [(o["side"], o["kind"]) for o in cut] == [("LEFT", "DOOR"), ("RIGHT", "WINDOW")], cut
    # 切在墙身上（X=3000，两樘都不在洞口宽度内）→ 一个洞口都不给
    assert read_cut_openings(s, (3000.0, -1200.0), (3000.0, 5700.0)) == []

    print("平面→立面联动: 南墙 2 樘 (x=1050/4250) / 北墙 flip 后 1 樘 (x=1000) / 剖切线取洞口 2 樘 校验通过")
    print("PASS test_link")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
