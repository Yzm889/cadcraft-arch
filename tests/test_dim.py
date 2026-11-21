"""尺寸标注验收测试。

验收链：四外墙 + 一道内隔墙 -> 门上洞 / 窗开洞 -> 自动搜环出房间
         -> annotate（只标外墙，洞口在内层、墙段在外层）-> 回读测量值。
断言：内墙不参与标注；每条标注的 measurement 与墙长/洞宽一致；
      全部落在 AA-DIM 层且用 AA-DIM 样式；重跑幂等（数量不增长）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    LAYERS, Session, annotate, auto_rooms, create_opening, create_wall,
    normalize_around, opening_data, wall_data,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def dims(s: Session) -> list[dict]:
    return [e for e in s.entities().get("entities", [])
            if e["type"] == "Dimension"]


def main() -> int:
    path = OUT / "test_dim.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()

    # 四外墙 6000×4800，一道内隔墙在 x=3000
    walls = [
        ("W001", (0.0, 0.0), (6000.0, 0.0)),
        ("W002", (6000.0, 0.0), (6000.0, 4800.0)),
        ("W003", (6000.0, 4800.0), (0.0, 4800.0)),
        ("W004", (0.0, 4800.0), (0.0, 0.0)),
    ]
    for wid, p1, p2 in walls:
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL")
        normalize_around(s, wid)
    single = [g for g in s.entities()["entities"]
              if g["type"] == "Block Reference" and "W001" not in str(g)]
    create_wall(s, "W005", (3000.0, 0.0), (3000.0, 4800.0), thick=240.0, kind="PARTITION")
    normalize_around(s, "W005")

    create_opening(s, "D001", "W001", "DOOR", 1000.0, 1000.0, 2100.0)
    create_opening(s, "C001", "W002", "WINDOW", 1500.0, 2400.0, 1500.0)

    rooms = auto_rooms(s)
    assert rooms["rooms"] == 2, rooms

    res = annotate(s)
    # 外墙 4 段 + 洞口 2 个 + 总尺寸 4 条 = 10 条；内隔墙 W005 不标
    assert res["dims"] == 10, res
    assert res["walls"] == 4 and res["openings"] == 2 and res["totals"] == 4, res

    got = dims(s)
    assert len(got) == 10, len(got)
    assert all(d["layer"] == LAYERS["dim"] for d in got), [d["layer"] for d in got]

    values = sorted(round(float(d["geometry"]["measurement"]), 2) for d in got)
    assert values == [1000.0, 1500.0, 4800.0, 4800.0, 4800.0, 4800.0, 6000.0, 6000.0, 6000.0, 6000.0], values

    # 墙长/洞宽与标注一一对应（精确到 0.01）；总尺寸每组一条，取该组墙段全长
    want = sorted([round(w["len"], 2) for w in wall_data(s) if w["id"] != "W005"]
                  + [round(o["width"], 2) for o in opening_data(s)]
                  + [4800.0, 4800.0, 6000.0, 6000.0])
    assert want == values, (want, values)

    # 幂等：重跑不叠加
    again = annotate(s)
    assert again["dims"] == 10, again
    assert len(dims(s)) == 10, len(dims(s))

    # 标注样式已建立且为当前样式
    styles = s.run([("dimstyle.list", {})], save=False).last().get("styles") or []
    names = [x.get("name") if isinstance(x, dict) else x for x in styles]
    assert "AA-DIM" in names, names

    # 轴号外扩：轴网在墙外 1600，尺寸线最外 1150+字高，不会压到轴号圈
    gp = s.run([("dimstyle.list", {"name": "AA-DIM"})], save=False).last()
    assert float(gp["style"]["textHeight"]) == 250.0, gp
    assert float(gp["style"]["arrowSize"]) == 150.0, gp

    print("PASS test_dim (dims=%d, walls=%d, openings=%d)"
          % (res["dims"], res["walls"], res["openings"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
