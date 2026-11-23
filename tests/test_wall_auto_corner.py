"""新建墙自动合角：连续 create_wall 四墙，不手动 normalize 也必须闭合。

红测试：当前 create_wall 不调用 normalize_around，块内两侧线是 0..L 的原始平行线，
四角会留半个墙厚缺口；期望外线 -120..L+120、内线 +120..L-120。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    block_geometry,
    corner_gap_count,
    create_wall,
    normalize_all_walls,
)

OUT = ROOT / "samples"


def spans(path: Path, block: str) -> list[tuple[float, float]]:
    lines = [g for g in block_geometry(path, block) if g["type"] == "LINE"]
    return sorted({(round(min(p[0] for p in g["pts"]), 1),
                    round(max(p[0] for p in g["pts"]), 1))
                   for g in lines})


def main() -> int:
    path = OUT / "test_wall_auto_corner.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    # 连续建四堵 6000×4000、厚 240 的外墙；全程不调用 normalize_around
    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W002", (6000.0, 0.0), (6000.0, 4000.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W003", (6000.0, 4000.0), (0.0, 4000.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W004", (0.0, 4000.0), (0.0, 0.0), thick=240.0, kind="EXTERNAL")

    lengths = {"W001": 6000.0, "W002": 4000.0, "W003": 6000.0, "W004": 4000.0}
    for wid, ln in lengths.items():
        sp = spans(path, "AA_WALL_" + wid)
        print("%s: %s" % (wid, sp))
        assert (-120.0, round(ln + 120.0, 1)) in sp, (wid, sp)
        assert (120.0, round(ln - 120.0, 1)) in sp, (wid, sp)

    # 批量路径：normalize=False 落四墙 -> corner_gap>0；normalize_all_walls 后归零
    path2 = OUT / "test_wall_auto_corner_batch.dxf"
    path2.unlink(missing_ok=True)
    s2 = Session(path2)
    s2.new_metric()
    create_wall(s2, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0,
                kind="EXTERNAL", normalize=False)
    create_wall(s2, "W002", (6000.0, 0.0), (6000.0, 4000.0), thick=240.0,
                kind="EXTERNAL", normalize=False)
    create_wall(s2, "W003", (6000.0, 4000.0), (0.0, 4000.0), thick=240.0,
                kind="EXTERNAL", normalize=False)
    create_wall(s2, "W004", (0.0, 4000.0), (0.0, 0.0), thick=240.0,
                kind="EXTERNAL", normalize=False)
    assert corner_gap_count(s2) > 0, "未规整时应有 corner_gap"
    normalize_all_walls(s2)
    assert corner_gap_count(s2) == 0, "批量规整后 corner_gap 应为 0"
    for wid, ln in lengths.items():
        sp = spans(path2, "AA_WALL_" + wid)
        assert (-120.0, round(ln + 120.0, 1)) in sp, (wid, sp)
        assert (120.0, round(ln - 120.0, 1)) in sp, (wid, sp)

    print("PASS test_wall_auto_corner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
