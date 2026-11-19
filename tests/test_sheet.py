"""图框 / 标题栏 / 出图 验收：几何、图层、属性、排图、幂等、PDF 导出。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError, Session, block_geometry, create_room, create_sheet, create_wall, draw_table,
    export, set_sheet, sheet_layout, sheet_window, LAYERS,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def layer_of(path: Path, block: str) -> set[str]:
    """块内图元的图层集合（DXF 组 8）。"""
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {ln.strip() for ln in text if ln.strip().upper().startswith("AA-")}


def main() -> int:
    path = OUT / "test_sheet.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()
    # 一张小图：6000×4800 单间，用来验证自动排图
    for wid, p1, p2 in [
        ("W001", (0.0, 0.0), (6000.0, 0.0)),
        ("W002", (6000.0, 0.0), (6000.0, 4800.0)),
        ("W003", (6000.0, 4800.0), (0.0, 4800.0)),
        ("W004", (0.0, 4800.0), (0.0, 0.0)),
    ]:
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL")
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="客厅")

    # 1) 固定定位：A3@1:100，图幅 42000×29700，内框 39000×28700
    lay = sheet_layout("A3", 100)
    assert (lay["sheet_w"], lay["sheet_h"]) == (42000.0, 29700.0)
    assert (lay["inner_w"], lay["inner_h"]) == (39000.0, 28700.0)
    res = create_sheet(s, "S001", "A3", 100, at=(0.0, 0.0),
                       project="演示工程", drawing="一层平面图", number="建-01",
                       date="2026-11-19", design="严", unit="CADCraft")
    assert res["lines"] == 18 and res["texts"] >= 12, res

    geom = block_geometry(path, "AA_SHEET_S001")
    xs = [p[0] for g in geom for p in g["pts"]]
    ys = [p[1] for g in geom for p in g["pts"]]
    assert round(min(xs)) == 0 and round(max(xs)) == 42000, (min(xs), max(xs))
    assert round(min(ys)) == 0 and round(max(ys)) == 29700, (min(ys), max(ys))
    # 内框线：x=2500（装订边 25mm）、x=41500（c=5mm）、y=500 / y=29200
    lines = [tuple(round(v) for v in p) for g in geom if g["type"] == "LINE" for p in g["pts"]]
    for x in (2500, 41500):
        assert any(abs(px - x) <= 1 for (px, _py) in lines), x
    for y in (500, 29200):
        assert any(abs(py - y) <= 1 for (_px, py) in lines), y

    # 2) 图层落位：图框 AA-SHEET、标题栏 AA-TITLE
    layers = layer_of(path, "AA_SHEET_S001")
    assert LAYERS["sheet"] in layers and LAYERS["title"] in layers, layers

    # 3) 同一编号重复建图幅 -> 拒绝
    try:
        create_sheet(s, "S001", "A3", 100, at=(0.0, 0.0))
    except CadError as e:
        assert "已存在" in str(e), e
    else:
        raise AssertionError("重复编号应被拒绝")

    # 4) 改标题栏：重画后块只剩一个、属性同步、旧文字消失
    set_sheet(s, "S001", drawing="二层平面图", number="建-02")
    refs = [e for e in s.references() if e["geometry"]["block"] == "AA_SHEET_S001"]
    assert len(refs) == 1, len(refs)
    attrs = {a["tag"]: a["text"]["value"] for a in refs[0]["geometry"]["attribs"]}
    assert attrs["AA_DRAWING"] == "二层平面图" and attrs["AA_NO"] == "建-02", attrs
    texts = [g["type"] for g in block_geometry(path, "AA_SHEET_S001")]
    assert texts.count("TEXT") >= 12

    # 5) 自动排图：另建一页，不给 at，图形外廓必须落在内框内
    #    先在墙下方 12m 处摆一张表 —— 表格在图框外的老实现会漏算，这里专门盯它
    draw_table(s, (0.0, -12000.0), "房间面积表", ["编号", "名称", "净面积(m2)"],
               [["R001", "客厅", "26.27"]], [1600.0, 2600.0, 2600.0])
    auto = create_sheet(s, "S003", "A3", 100, project="自动排图")
    ref3 = [e for e in s.references() if e["geometry"]["block"] == "AA_SHEET_S003"][0]
    ip3 = ref3["geometry"]["insert"]
    for x, y in ((0.0, 0.0), (6000.0, 4800.0)):
        assert ip3["x"] + 2500 <= x <= ip3["x"] + 41500, (x, ip3["x"])
        assert ip3["y"] + 500 <= y <= ip3["y"] + 29200, (y, ip3["y"])
    # 表格底边（-12000 - 总高）也必须在内框里
    tab_y = -12000.0 - (400.0 * 1.15 + 400.0 * 2)
    assert ip3["y"] + 500 <= tab_y, (tab_y, ip3["y"])
    assert ip3["x"] <= 0.0 <= ip3["x"] + 39000
    ext = auto["extent"]
    assert ext is not None and ext[1] <= tab_y, (ext, tab_y)

    # 6) 图幅过小：A4 留白 20m 时 6000×4800 装不下
    try:
        create_sheet(s, "S002", "A4", 100, pad=20000.0)
    except CadError as e:
        assert "放不进" in str(e), e
    else:
        raise AssertionError("A4 应装不下")

    # 7) 出图：PNG / PDF 都要有实体产物
    win = sheet_window(s, "S001")
    png = export(s, OUT / "test_sheet.png", win)
    pdf = export(s, OUT / "test_sheet.pdf", win)
    assert png["bytes"] > 2048 and pdf["bytes"] > 2048, (png, pdf)

    print("PASS test_sheet (lines=%d, texts=%d, png=%dB, pdf=%dB)"
          % (res["lines"], res["texts"], png["bytes"], pdf["bytes"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
