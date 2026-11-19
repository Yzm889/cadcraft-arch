"""转角合角验收测试：外侧墙线必须延伸到邻墙外墙面，角部不留缺口。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import Session, block_geometry, create_wall, normalize_around  # noqa: E402

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def spans(path, block):
    lines = [g for g in block_geometry(path, block) if g["type"] == "LINE"]
    return sorted({(round(min(p[0] for p in g["pts"]), 1), round(max(p[0] for p in g["pts"]), 1))
                   for g in lines})


def main() -> int:
    path = OUT / "test_corner.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()
    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W002", (0.0, 0.0), (0.0, 4800.0), thick=240.0, kind="EXTERNAL")
    normalize_around(s, "W002")     # 与两墙相接的一圈全部重建

    a = spans(path, "AA_WALL_W001")
    b = spans(path, "AA_WALL_W002")
    print("W001 侧线:", a)
    print("W002 侧线:", b)

    # 水平墙：外侧线从 -120（邻墙外墙面）起，内侧线从 +120 起
    assert a == [(-120.0, 6000.0), (120.0, 6000.0)], a
    # 竖直墙：外侧线同样从 -120 起
    assert b == [(-120.0, 4800.0), (120.0, 4800.0)], b
    # 内侧线不得穿进对方墙身
    assert (120.0, 6000.0) in a and (120.0, 4800.0) in b, (a, b)

    # 2) 四墙闭环 6000×4000：四个角全部合角，外侧线两端都要到 ±120 外墙面
    path2 = OUT / "test_corner_ring.dxf"
    if path2.exists():
        path2.unlink()
    s2 = Session(path2)
    s2.new_metric()
    create_wall(s2, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s2, "W002", (6000.0, 0.0), (6000.0, 4000.0), thick=240.0, kind="EXTERNAL")
    create_wall(s2, "W003", (6000.0, 4000.0), (0.0, 4000.0), thick=240.0, kind="EXTERNAL")
    create_wall(s2, "W004", (0.0, 4000.0), (0.0, 0.0), thick=240.0, kind="EXTERNAL")
    for wid in ("W001", "W002", "W003", "W004"):
        normalize_around(s2, wid)

    L = {"W001": 6000.0, "W002": 4000.0, "W003": 6000.0, "W004": 4000.0}
    for wid, ln in L.items():
        sp = spans(path2, f"AA_WALL_{wid}")
        print(f"ring {wid}:", sp)
        # 外侧一条：-120 .. L+120；内侧一条：+120 .. L-120
        assert (-120.0, round(ln + 120.0, 1)) in sp, (wid, sp)
        assert (120.0, round(ln - 120.0, 1)) in sp, (wid, sp)

    print("PASS test_corner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
