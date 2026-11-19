"""墙体相交自动切断的验收测试。"""

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
        print("  拒绝切断 ok:", str(e))
        return
    raise AssertionError("应当拒绝但没有：%s" % keyword)


def main() -> int:
    path = OUT / "test_split.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()

    # 十字交叉：水平 3600，竖向 (1800,-1800) -> (1800,1800)
    create_wall(s, "W001", (0.0, 0.0), (3600.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W002", (1800.0, -1800.0), (1800.0, 1800.0), thick=240.0, kind="EXTERNAL")
    # 水平墙上放一樘门（切点右侧），用于验证洞口迁移
    create_opening(s, "D001", "W001", "DOOR", width=1000.0, pos=2700.0)

    print("before:", [(w["id"], round(w["len"], 1)) for w in wall_data(s)])
    res = split_at_intersections(s)
    print("result:", res)

    walls = wall_data(s)
    assert res["splits"] == 2, res
    assert len(walls) == 4, walls
    for w in walls:
        assert abs(w["len"] - 1800.0) < 1e-4, w
        assert w["root"] in ("W001", "W002"), w      # 逻辑墙号保留

    # 编号：原墙保留首段，新段用新号
    ids = {w["id"] for w in walls}
    assert "W001" in ids and "W002" in ids, ids
    assert len(ids) == 4, ids

    # 洞口迁移到切点右侧的新段，偏移量 2700 - 1800 = 900
    ops = opening_data(s)
    assert len(ops) == 1, ops
    d = ops[0]
    assert d["wallid"] != "W001", d
    assert abs(d["pos"] - 900.0) < 1e-4, d
    assert abs(d["width"] - 1000.0) < 1e-4, d
    host = [w for w in walls if w["id"] == d["wallid"]][0]
    assert host["root"] == "W001", host
    print("opening moved:", d["id"], "->", d["wallid"], "pos", d["pos"])

    # 墙身开洞在切断后仍然有效：承门分段侧线 = 让出邻墙 120 + 洞口 [400,1400]
    geom = block_geometry(path, "AA_WALL_" + d["wallid"])
    sides = [g for g in geom if g["type"] == "LINE"]
    spans = sorted({(round(min(p[0] for p in g["pts"]), 1), round(max(p[0] for p in g["pts"]), 1))
                    for g in sides})
    assert len(sides) == 4, sides
    assert spans == [(120.0, 400.0), (1400.0, 1800.0)], spans
    print("opening hole kept after split ok:", spans)

    # 再跑一次：已经切过，不应再产生新分段（幂等）
    again = split_at_intersections(s)
    assert again["splits"] == 0, again
    assert len(wall_data(s)) == 4, wall_data(s)
    print("idempotent ok")

    # 跨切点洞口必须拒绝，且拒绝后图纸不变
    p2 = OUT / "test_split_reject.dxf"
    if p2.exists():
        p2.unlink()
    s2 = Session(p2)
    s2.new_metric()
    create_wall(s2, "W001", (0.0, 0.0), (3600.0, 0.0), thick=240.0)
    create_wall(s2, "W002", (1800.0, -1800.0), (1800.0, 1800.0), thick=240.0)
    create_opening(s2, "D001", "W001", "DOOR", width=1000.0, pos=1800.0)
    before = len(wall_data(s2)) + len(opening_data(s2))
    expect_error(lambda: split_at_intersections(s2), "跨越")
    after = len(wall_data(s2)) + len(opening_data(s2))
    assert before == after == 3, (before, after)
    print("no partial write ok", before, after)

    print("PASS test_split")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
