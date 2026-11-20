"""图名标注 / 指北针验收（v0.9.3）。

要点：
  · 图名文字自动落在 AA-NAME 层，图名下粗线落在 AA-SHEET 层（线宽 0.70）
  · 指北针圆 + 三角指针落在 AA-NAME 层，直径默认 2400（24mm@1:100）
  · 两者都以 AA_SYM_<编号> 块参照存储，属性可回读（AA_TEXT / AA_SCALE / AA_KIND）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    LAYERS,
    CadError,
    Session,
    block_geometry,
    create_north_arrow,
    create_title_mark,
    layer_of_block,
    layer_table,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_symbols.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()

    # 1. 图名标注
    t = create_title_mark(s, "T001", (1000.0, 1000.0), "一层平面图", 100)
    assert t["scale"] == "1:100", t
    attrs = s.attributes("AA_SYM_T001")
    assert attrs["AA_TYPE"] == "TITLEMARK", attrs
    assert attrs["AA_TEXT"] == "一层平面图", attrs
    assert attrs["AA_SCALE"] == "100", attrs

    layers = layer_of_block(path, "AA_SYM_T001")
    assert LAYERS["name"] in layers, layers
    assert LAYERS["sheet"] in layers, layers        # 图名下粗线
    assert layers - {"0"} <= {LAYERS["name"], LAYERS["sheet"]}, layers

    # 图名层与图框层规格（粗线真的来自图框层 0.70）
    table = layer_table(path)
    assert abs(table[LAYERS["sheet"]]["lineweight"] - 0.70) < 0.011, table[LAYERS["sheet"]]
    assert abs(table[LAYERS["name"]]["lineweight"] - 0.25) < 0.011, table[LAYERS["name"]]

    # 2. 指北针
    n = create_north_arrow(s, "N001", (4000.0, 1000.0))
    assert abs(n["diameter"] - 2400.0) < 1e-6, n
    attrs2 = s.attributes("AA_SYM_N001")
    assert attrs2["AA_KIND"] == "NORTH", attrs2
    assert abs(float(attrs2["AA_R"]) - 1200.0) < 1e-6, attrs2
    assert layer_of_block(path, "AA_SYM_N001") - {"0"} == {LAYERS["name"]}

    # 3. 几何看图：图名 1 条文字 + 2 条下画线；指北针 1 圆 + 3 线 + 1 文字
    g1 = block_geometry(path, "AA_SYM_T001")
    kinds1 = sorted(x["type"] for x in g1)
    assert kinds1.count("TEXT") == 2, kinds1
    assert kinds1.count("LINE") == 2, kinds1
    g2 = block_geometry(path, "AA_SYM_N001")
    kinds2 = sorted(x["type"] for x in g2)
    assert kinds2.count("CIRCLE") == 1, kinds2
    assert kinds2.count("LINE") == 3, kinds2
    assert kinds2.count("TEXT") == 1, kinds2

    # 4. 重名拒绝
    try:
        create_title_mark(s, "T001", (0.0, 0.0), "重复", 50)
    except CadError:
        pass
    else:
        raise AssertionError("重名图名应被拒绝")

    print("图名层:", sorted(layer_of_block(path, "AA_SYM_T001")))
    print("指北针几何:", kinds2)
    print("PASS test_symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
