"""房间自动搜环验收测试：闭合墙环必须被枚举出来，开放缺口不得虚报房间。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    auto_rooms,
    create_wall,
    find_room_rings,
    normalize_around,
    room_data,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)
EXT = 240.0


def rect(s: Session, prefix="W", x=6000.0, y=4000.0):
    create_wall(s, f"{prefix}1", (0.0, 0.0), (x, 0.0), thick=EXT, kind="EXTERNAL")
    create_wall(s, f"{prefix}2", (x, 0.0), (x, y), thick=EXT, kind="EXTERNAL")
    create_wall(s, f"{prefix}3", (x, y), (0.0, y), thick=EXT, kind="EXTERNAL")
    create_wall(s, f"{prefix}4", (0.0, y), (0.0, 0.0), thick=EXT, kind="EXTERNAL")
    for i in (1, 2, 3, 4):
        normalize_around(s, f"{prefix}{i}")


def main() -> int:
    # 1) 单个闭合矩形 6000×4000、外墙 240
    path = OUT / "test_room_auto.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()
    rect(s)

    rings = find_room_rings(s)
    print("单房间 rings:", rings)
    assert len(rings) == 1 and set(rings[0]["walls"]) == {"W1", "W2", "W3", "W4"}, rings

    r = auto_rooms(s)
    print("单房间 auto:", r["created"])
    assert r["rooms"] == 1, r
    # 净面积 = (6000-240)*(4000-240) = 5760*3760（容差 1 mm²，吸收落图坐标漂移）
    assert abs(r["created"][0]["area"] - 5760.0 * 3760.0) < 1.0, r["created"][0]
    assert set(r["created"][0]["walls"]) == {"W1", "W2", "W3", "W4"}, r["created"][0]

    # 2) 幂等：同一墙环再来一次不重复建房
    r2 = auto_rooms(s)
    print("重跑 auto:", r2["rooms"], "skipped", len(r2["skipped"]))
    assert r2["rooms"] == 0 and len(r2["skipped"]) == 1, r2
    assert len(room_data(s)) == 1, room_data(s)

    # 3) 中间一道隔墙把房间一分为二：应搜出 2 个房间
    path2 = OUT / "test_room_auto_split.dxf"
    if path2.exists():
        path2.unlink()
    s2 = Session(path2)
    s2.new_metric()
    create_wall(s2, "W001", (0.0, 0.0), (6000.0, 0.0), thick=EXT, kind="EXTERNAL")
    create_wall(s2, "W002", (6000.0, 0.0), (6000.0, 4000.0), thick=EXT, kind="EXTERNAL")
    create_wall(s2, "W003", (6000.0, 4000.0), (0.0, 4000.0), thick=EXT, kind="EXTERNAL")
    create_wall(s2, "W004", (0.0, 4000.0), (0.0, 0.0), thick=EXT, kind="EXTERNAL")
    create_wall(s2, "W005", (3000.0, 0.0), (3000.0, 4000.0), thick=EXT, kind="PARTITION")
    for wid in ("W001", "W002", "W003", "W004", "W005"):
        normalize_around(s2, wid)

    rings2 = find_room_rings(s2)
    print("两房间 rings:", rings2)
    assert len(rings2) == 2, rings2

    r3 = auto_rooms(s2)
    areas = sorted(round(c["area"], 1) for c in r3["created"])
    print("两房间 auto:", r3["created"])
    # 每间净面积 = (3000-240)*(4000-240) = 2760*3760
    assert areas == [2760.0 * 3760.0, 2760.0 * 3760.0], areas

    # 4) 开放缺口（少一堵墙）不得虚报房间
    path3 = OUT / "test_room_auto_open.dxf"
    if path3.exists():
        path3.unlink()
    s3 = Session(path3)
    s3.new_metric()
    create_wall(s3, "W001", (0.0, 0.0), (6000.0, 0.0), thick=EXT, kind="EXTERNAL")
    create_wall(s3, "W002", (6000.0, 0.0), (6000.0, 4000.0), thick=EXT, kind="EXTERNAL")
    create_wall(s3, "W003", (6000.0, 4000.0), (0.0, 4000.0), thick=EXT, kind="EXTERNAL")
    print("开放缺口 rings:", find_room_rings(s3))
    assert find_room_rings(s3) == [], "缺一堵墙时不得搜出房间"

    # 5) 房间中间一段悬挂墙（不接墙）不得把房间算成两个，也不得报错
    path4 = OUT / "test_room_auto_float.dxf"
    if path4.exists():
        path4.unlink()
    s4 = Session(path4)
    s4.new_metric()
    rect(s4)
    create_wall(s4, "W9", (2000.0, 2000.0), (4000.0, 2000.0), thick=120.0, kind="PARTITION")
    rings4 = find_room_rings(s4)
    print("悬挂墙 rings:", rings4)
    assert len(rings4) == 1, rings4

    print("PASS test_room_auto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
