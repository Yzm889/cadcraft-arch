"""房间改名与面积表验收：改名只动名称不动几何，CSV 与图上表格都要能回读。"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    block_geometry,
    create_room,
    create_wall,
    normalize_around,
    room_data,
    rooms_report,
    set_room,
)

OUT = ROOT / "samples"
EXT = 240.0


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build(s: Session) -> None:
    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=EXT, kind="EXTERNAL")
    create_wall(s, "W002", (6000.0, 0.0), (6000.0, 4000.0), thick=EXT, kind="EXTERNAL")
    create_wall(s, "W003", (6000.0, 4000.0), (0.0, 4000.0), thick=EXT, kind="EXTERNAL")
    create_wall(s, "W004", (0.0, 4000.0), (0.0, 0.0), thick=EXT, kind="EXTERNAL")
    for w in ("W001", "W002", "W003", "W004"):
        normalize_around(s, w)
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], "客厅")
    create_room(s, "R002", ["W001", "W002", "W003", "W004"], "卧室")


def main() -> int:
    path = OUT / "test_room_modify.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()
    build(s)

    rooms = {r["id"]: r for r in room_data(s)}
    assert set(rooms) == {"R001", "R002"}, rooms
    old_area = rooms["R001"]["area"]
    old_pts = rooms["R001"]["pts"]
    assert len(old_pts) == 4, old_pts

    # 1) 改名：属性与图面文字都要变，面积/轮廓不变
    res = set_room(s, "R001", "客厅A")
    print("set_room:", res)
    assert res["changed"] == 1 and res["name"] == "客厅A", res
    assert abs(res["area"] - old_area) < 1e-2, res

    r1 = {r["id"]: r for r in room_data(s)}["R001"]
    assert r1["name"] == "客厅A", r1
    assert r1["pts"] == old_pts, (r1["pts"], old_pts)
    # 图面上的名称文字必须真的变了（房间块里名称 + 面积两行，名称在前）
    geom = block_geometry(path, "AA_ROOM_R001")
    texts = [g["text"] for g in geom if g["type"] in ("TEXT", "MTEXT")]
    print("room block texts:", texts)
    assert texts[0] == "客厅A" and texts[1].endswith("㎡"), texts

    # 2) 幂等：同名再改一次不写盘
    digest = sha(path)
    again = set_room(s, "R001", "客厅A")
    assert again["changed"] == 0, again
    assert sha(path) == digest, "同名不应产生写入"

    # 3) 只改一个房间，另一个房间不受影响
    r2 = {r["id"]: r for r in room_data(s)}["R002"]
    assert r2["name"] == "卧室", r2

    # 4) 未知房间 / 非法输入拒绝，且文件字节不变
    digest = sha(path)
    try:
        set_room(s, "R999", "x")
        raise AssertionError("未知房间应被拒绝")
    except CadError as exc:
        print("拒绝未知房间 ok:", exc)
    assert sha(path) == digest

    # 5) 清空名称（允许改回编号风格的空名）
    res = set_room(s, "R002", "")
    assert res["changed"] == 1, res
    assert {r["id"]: r for r in room_data(s)}["R002"]["name"] == "", room_data(s)

    # 6) 汇总表：CSV 落盘 + 图上表格
    csv_path = OUT / "test_rooms.csv"
    if csv_path.exists():
        csv_path.unlink()
    rep = rooms_report(s, csv_path=csv_path)
    print("report:", rep["rooms"], "间, 合计", rep["total_area_m2"], "m2")
    assert rep["rooms"] == 2, rep
    assert csv_path.exists()
    raw = csv_path.read_text(encoding="utf-8-sig")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert lines[0].startswith("房间编号"), lines[0]
    assert len(lines) == 2 + 2, lines          # 表头 + 2 间 + 合计
    assert "合计" in lines[-1], lines[-1]
    # 每间净面积 5760×3760 = 21.66 m²，合计 43.32 m²
    assert abs(rep["total_area_m2"] - 43.32) < 0.05, rep["total_area_m2"]

    rep2 = rooms_report(s, table_at=(0.0, -3200.0))
    table = rep2.get("table", {})
    print("table inserted:", table)
    assert table.get("by") == "geometry", rep2
    # 表格内容要能在图里回读到中文表头与房间名（几何绘制，走 AA-TABLE 层文字）
    marks = block_geometry(path, table["block"])
    texts = [e for e in marks if str(e.get("type", "")).lower() in ("text", "mtext")]
    assert len(texts) >= table["rows"] + table["cols"] - 1, len(texts)
    flat = " ".join(str(t.get("text", t.get("value", ""))) for t in texts)
    assert "房间面积表" in flat, flat
    assert "客厅A" in flat, flat
    assert "编号" in flat, flat
    assert "合计" in flat and "43.32" in flat, flat

    print("PASS test_room_modify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
