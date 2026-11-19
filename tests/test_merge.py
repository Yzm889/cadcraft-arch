"""墙体合并（切断的逆操作）验收测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    block_geometry,
    create_opening,
    create_wall,
    merge_walls,
    opening_data,
    split_at_intersections,
    wall_data,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def expect_error(fn, keyword: str) -> None:
    try:
        fn()
    except CadError as e:
        assert keyword in str(e), (keyword, str(e))
        print("  拒绝合并 ok:", str(e))
        return
    raise AssertionError("应当拒绝但没有：%s" % keyword)


def main() -> int:
    path = OUT / "test_merge.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()

    # 与切断测试同一张图：十字交叉 + 水平墙一樘门
    create_wall(s, "W001", (0.0, 0.0), (3600.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W002", (1800.0, -1800.0), (1800.0, 1800.0), thick=240.0, kind="EXTERNAL")
    create_opening(s, "D001", "W001", "DOOR", width=1000.0, pos=2700.0)

    split_at_intersections(s)
    assert len(wall_data(s)) == 4
    print("after split:", [(w["id"], round(w["len"], 1), w["root"]) for w in wall_data(s)])

    res = merge_walls(s)
    print("merge result:", res)

    walls = wall_data(s)
    assert res["merges"] == 2, res
    assert len(walls) == 2, walls
    ids = {w["id"] for w in walls}
    assert ids == {"W001", "W002"}, ids
    for w in walls:
        assert abs(w["len"] - 3600.0) < 1e-4, w
        assert w["root"] == w["id"], w

    # 洞口回到原墙，偏移量 900 + 1800 = 2700
    ops = opening_data(s)
    assert len(ops) == 1, ops
    d = ops[0]
    assert d["wallid"] == "W001", d
    assert abs(d["pos"] - 2700.0) < 1e-4, d
    print("opening restored:", d["id"], "->", d["wallid"], "pos", d["pos"])

    # 合并后墙身开洞仍在：W001 侧线 = [0,1680] + [1920,2200] + [3200,3600]
    geom = block_geometry(path, "AA_WALL_W001")
    sides = [g for g in geom if g["type"] == "LINE"]
    spans = sorted({(round(min(p[0] for p in g["pts"]), 1), round(max(p[0] for p in g["pts"]), 1))
                    for g in sides})
    assert len(sides) == 6, sides
    assert spans == [(0.0, 1680.0), (1920.0, 2200.0), (3200.0, 3600.0)], spans
    print("opening hole kept after merge ok:", spans)

    # 幂等：已经合过，再跑不再合并
    again = merge_walls(s)
    assert again["merges"] == 0, again
    assert len(wall_data(s)) == 2
    print("idempotent ok")

    # 显式指定：非共线（十字交叉的两段）必须拒绝，且图纸不变
    p2 = OUT / "test_merge_reject.dxf"
    if p2.exists():
        p2.unlink()
    s2 = Session(p2)
    s2.new_metric()
    create_wall(s2, "W001", (0.0, 0.0), (3600.0, 0.0), thick=240.0)
    create_wall(s2, "W002", (1800.0, -1800.0), (1800.0, 1800.0), thick=240.0)
    before = len(wall_data(s2))
    expect_error(lambda: merge_walls(s2, ["W001", "W002"]), "不共线")
    assert len(wall_data(s2)) == before == 2
    print("no partial write ok", before)

    # 墙厚不一致也必须拒绝
    p3 = OUT / "test_merge_thick.dxf"
    if p3.exists():
        p3.unlink()
    s3 = Session(p3)
    s3.new_metric()
    create_wall(s3, "W001", (0.0, 0.0), (1800.0, 0.0), thick=240.0)
    create_wall(s3, "W002", (1800.0, 0.0), (3600.0, 0.0), thick=200.0)
    expect_error(lambda: merge_walls(s3, ["W001", "W002"]), "墙厚不一致")

    # 显式合并不共 root 的两段共线墙：允许（人工并段）
    s4 = Session(OUT / "test_merge_explicit.dxf")
    if (OUT / "test_merge_explicit.dxf").exists():
        (OUT / "test_merge_explicit.dxf").unlink()
    s4.new_metric()
    create_wall(s4, "W001", (0.0, 0.0), (1800.0, 0.0), thick=240.0)
    create_wall(s4, "W002", (1800.0, 0.0), (3600.0, 0.0), thick=240.0)
    r4 = merge_walls(s4, ["W001", "W002"])
    assert r4["merges"] == 1, r4
    w4 = wall_data(s4)
    assert len(w4) == 1 and w4[0]["id"] == "W001", w4
    assert abs(w4[0]["len"] - 3600.0) < 1e-4
    print("explicit merge ok:", r4["merged"])

    print("PASS test_merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
