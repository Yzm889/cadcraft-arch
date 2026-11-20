"""标高 / 索引 / 剖切符号验收（v0.9.8，B1）。

要点：
  · 标高：三角高 3mm + 数字 2.5mm 在基线上方，`format_elevation` 统一成 ±0.000 / 3.600 / -0.450
  · 索引：直径 10mm 圆 + 直径线，上半详图编号，下半图号（同图写 —）
  · 剖切：位置线只画两端两段 6mm 粗线，两端各 5mm 投射方向线，编号 1-1 两端都写
  · 三者都是 AA_SYM_<编号> 块参照，属性可回读；换比例后按新 mm 规格重画
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    block_geometry,
    create_elevation_mark,
    create_index_mark,
    create_section_mark,
    format_elevation,
    rescale_annotations,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_symbols2.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()

    # 0. 数值格式（三位小数、米制、不带 m）
    assert format_elevation(0) == "±0.000", format_elevation(0)
    assert format_elevation(3.6) == "3.600", format_elevation(3.6)
    assert format_elevation(-0.45) == "-0.450", format_elevation(-0.45)
    assert format_elevation(-0.0004) == "±0.000", format_elevation(-0.0004)

    # 1. 标高：4 条线（三角 3 + 基线 1）+ 1 条文字；文字基线在三角底边之上
    e = create_elevation_mark(s, "E001", (0.0, 0.0), 0.0)
    assert e["value"] == "±0.000", e
    attrs = s.attributes("AA_SYM_E001")
    assert attrs["AA_KIND"] == "ELEV", attrs
    assert abs(float(attrs["AA_H"]) - 300.0) < 1e-6, attrs
    g = block_geometry(path, "AA_SYM_E001")
    kinds = sorted(x["type"] for x in g)
    assert kinds.count("LINE") == 4, kinds
    assert kinds.count("TEXT") == 1, kinds
    txt = [x for x in g if x["type"] == "TEXT"][0]
    assert abs(txt["h"] - 250.0) < 1e-6, txt
    assert txt["pts"][0][1] > 300.0 + 1e-6, txt   # 数字在底边上方，不压墙线

    # 2. 索引：1 圆 + 1 直径线 + 2 文字，圆直径 10mm@1:100
    i = create_index_mark(s, "I001", (4000.0, 0.0), "1")
    attrs2 = s.attributes("AA_SYM_I001")
    assert attrs2["AA_KIND"] == "INDEX", attrs2
    assert attrs2["AA_DETAIL"] == "1", attrs2
    assert attrs2["AA_SHEETNO"] == "—", attrs2
    g2 = block_geometry(path, "AA_SYM_I001")
    kinds2 = sorted(x["type"] for x in g2)
    assert kinds2.count("CIRCLE") == 1 and kinds2.count("LINE") == 1, kinds2
    assert kinds2.count("TEXT") == 2, kinds2
    circ = [x for x in g2 if x["type"] == "CIRCLE"][0]
    assert abs(circ["r"] - 500.0) < 1e-6, circ

    # 3. 剖切：两端两段 6mm 位置线 + 两条 5mm 方向线 + 两端编号
    sec = create_section_mark(s, "S001", (0.0, -1000.0), (0.0, 6000.0),
                              direction="left", no="1")
    attrs3 = s.attributes("AA_SYM_S001")
    assert attrs3["AA_KIND"] == "SECTION", attrs3
    assert attrs3["AA_NO"] == "1", attrs3
    assert abs(float(attrs3["AA_SEG"]) - 600.0) < 1e-6, attrs3
    g3 = block_geometry(path, "AA_SYM_S001")
    kinds3 = sorted(x["type"] for x in g3)
    assert kinds3.count("LINE") == 4, kinds3       # 2 段位置线 + 2 条方向线
    assert kinds3.count("TEXT") == 2, kinds3       # 两端各一个 1-1

    # 4. 拒绝非法剖切
    for bad in (((0.0, 0.0), (0.0, 0.0), "left"), ((0.0, 0.0), (1000.0, 0.0), "north")):
        try:
            create_section_mark(s, "S999", bad[0], bad[1], direction=bad[2])
        except CadError:
            pass
        else:
            raise AssertionError("非法剖切应被拒绝：%r" % (bad,))

    # 5. 换 1:50：按新比例重画（三角高 150、索引圆 r=250、文字 125）
    rescale_annotations(s, 50, rebuild_dims=False)
    attrs = s.attributes("AA_SYM_E001")
    assert abs(float(attrs["AA_H"]) - 150.0) < 1e-6, attrs
    assert abs(float(attrs["AA_SCALE"]) - 50.0) < 1e-6, attrs
    circ = [x for x in block_geometry(path, "AA_SYM_I001") if x["type"] == "CIRCLE"][0]
    assert abs(circ["r"] - 250.0) < 1e-6, circ
    sec_attrs = s.attributes("AA_SYM_S001")
    assert abs(float(sec_attrs["AA_SEG"]) - 300.0) < 1e-6, sec_attrs

    print("标高文字:", e["value"], "索引:", attrs2["AA_DETAIL"], "剖切:", sec["no"])
    print("按 1:50 重画后三角高:", attrs["AA_H"], "索引半径:", circ["r"])
    print("PASS test_symbols2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
