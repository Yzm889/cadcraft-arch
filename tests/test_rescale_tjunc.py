"""rescale 房间重建修复验收（HANDOVER §9 #13）。

缺陷：rescale_annotations 重建房间用的是整墙版 create_room——要求列出的墙首尾相接。
带 T 接内墙的图上，房间边界落在内墙与外墙的交点（墙的中段），整墙拼环必然失败：
    CadError: 拒绝写入：墙环断裂，墙 W005 的端点与上一个终点不重合
集成样板这类真实图纸都有 T 接内墙，rescale 在它们上面必挂。改动前（v1.0.61 及更早）同样复现。

修法：重画房间时按墙编号集合从 find_room_rings 匹配子段边界，走 create_room_edges；
搜不到对应环（墙被改过/老图）再退回整墙版。

断言：
  - T 接内墙的图上 rescale 成功；房间数量/墙集合/面积/内轮廓全部不变；
  - 房间文字按新比例重画（1:50 时房名 2.5mm=125、面积 2.0mm=100）；
  - show_name/show_area 保留；墙、门窗一根不动；verify 干净；重跑幂等；
  - 整墙版建的房间（无内墙）走回退路径照样成功。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session, annotate, auto_rooms, block_geometry, create_opening, create_room,
    create_wall, normalize_around, rescale_annotations, room_data, verify, wall_data,
)

OUT = ROOT / "samples"
PATH = OUT / "test_rescale_tjunc.dxf"
PATH2 = OUT / "test_rescale_plain.dxf"


def _canon(pts):
    """内轮廓顶点序列规范化：整墙版和搜环版的起始顶点不同，多边形本身相同，
    统一旋转到最小顶点开头再比。"""
    q = [(round(x, 2), round(y, 2)) for x, y in pts]
    i = q.index(min(q))
    return q[i:] + q[:i]


def snapshot(s: Session) -> dict:
    rooms = room_data(s)
    return {
        "rooms": sorted(r["id"] for r in rooms),
        "walls_of": {r["id"]: sorted(r["walls"]) for r in rooms},
        "area": {r["id"]: round(r["area"]) for r in rooms},   # 取整到 mm²：墙端点 1e-5 漂移会让面积在第 2 位小数抖动
        "pts": {r["id"]: _canon(r["pts"]) for r in rooms},
        "show": {r["id"]: (r["show_name"], r["show_area"]) for r in rooms},
        "walls": [(w["id"], tuple(round(v, 4) for v in w["p1"]), tuple(round(v, 4) for v in w["p2"]))
                  for w in wall_data(s)],
        "openings": sorted(o["id"] for o in __import__("aa_lib").opening_data(s)),
    }


def main() -> int:
    # ---------- 场景 A：T 接内墙（此前 rescale 必挂） ----------
    path = PATH
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    for wid, p1, p2 in (("W001", (0.0, 0.0), (6000.0, 0.0)),
                        ("W002", (6000.0, 0.0), (6000.0, 4800.0)),
                        ("W003", (6000.0, 4800.0), (0.0, 4800.0)),
                        ("W004", (0.0, 4800.0), (0.0, 0.0))):
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL")
        normalize_around(s, wid)
    create_wall(s, "W005", (3000.0, 0.0), (3000.0, 4800.0), thick=200.0, kind="PARTITION")
    normalize_around(s, "W005")
    create_opening(s, "D001", "W001", "DOOR", 1000.0, 1000.0, 2100.0)
    assert auto_rooms(s)["rooms"] == 2
    annotate(s)
    before = snapshot(s)
    assert {frozenset(v) for v in before["walls_of"].values()} == {
        frozenset({"W001", "W002", "W003", "W005"}),   # 右房：W001/W003 的右段
        frozenset({"W001", "W003", "W004", "W005"}),   # 左房：W001/W003 的左段
    }, before

    rs = rescale_annotations(s, 50.0)
    assert rs["rooms"] == 2, rs
    after = snapshot(s)
    assert after["rooms"] == before["rooms"], after
    assert after["walls_of"] == before["walls_of"], after
    assert after["area"] == before["area"], (before["area"], after["area"])
    assert after["pts"] == before["pts"], "内轮廓变了"
    assert after["walls"] == before["walls"], "墙不该被动"
    assert after["openings"] == before["openings"], after

    # 房间文字按新比例：房名 2.5mm×50=125，面积 2.0mm×50=100
    for rid in ("R001", "R002"):
        hs = [g["h"] for g in block_geometry(path, "AA_ROOM_" + rid) if g["type"] == "TEXT"]
        assert sorted(hs) == [100.0, 125.0], (rid, hs)

    # 幂等：再改一次比例，结果一致
    rescale_annotations(s, 100.0)
    again = snapshot(s)
    assert again["area"] == before["area"] and again["pts"] == before["pts"], again
    hs = [g["h"] for g in block_geometry(path, "AA_ROOM_R001") if g["type"] == "TEXT"]
    assert sorted(hs) == [200.0, 250.0], hs          # 1:100 时 2.5mm=250 / 2.0mm=200
    assert verify(s)["count"] == 0, verify(s)["issues"]

    # ---------- 场景 B：整墙版建的房间（回退路径），show_name 保留 ----------
    path2 = PATH2
    path2.unlink(missing_ok=True)
    s2 = Session(path2)
    s2.new_metric()
    for wid, p1, p2 in (("W001", (0.0, 0.0), (6000.0, 0.0)),
                        ("W002", (6000.0, 0.0), (6000.0, 4800.0)),
                        ("W003", (6000.0, 4800.0), (0.0, 4800.0)),
                        ("W004", (0.0, 4800.0), (0.0, 0.0))):
        create_wall(s2, wid, p1, p2, thick=240.0, kind="EXTERNAL")
        normalize_around(s2, wid)
    create_room(s2, "R001", ["W001", "W002", "W003", "W004"], "门厅", show_name=False)
    annotate(s2)
    b2 = snapshot(s2)
    assert b2["show"]["R001"] == (False, True), b2
    rescale_annotations(s2, 50.0)
    a2 = snapshot(s2)
    assert a2["area"] == b2["area"] and a2["pts"] == b2["pts"], a2
    assert a2["show"]["R001"] == (False, True), a2   # show_name 不再被 rescale 丢掉

    print("PASS test_rescale_tjunc (rooms=%d)" % rs["rooms"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
