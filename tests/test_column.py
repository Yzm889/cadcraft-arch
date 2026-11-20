"""柱验收（v1.0.0，B2）。

要点：
  · 矩形柱：实心 SOLID + 外框，落在 AA-COLUMN，尺寸/面积/转角可回读
  · 圆柱：24 个扇形 SOLID + 圆，面积按 π r²
  · 重名 / 非法类型 / 非正尺寸拒绝；几何是真实尺寸（换比例不变）
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
    create_column,
    layer_of_block,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_column.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()

    # 1. 矩形柱 400×300
    c1 = create_column(s, "C1", (2000.0, 1000.0), 400.0, 300.0)
    assert c1["kind"] == "RECT", c1
    assert abs(c1["area"] - 120000.0) < 1e-6, c1
    attrs = s.attributes("AA_COLUMN_C1")
    assert attrs["AA_TYPE"] == "COLUMN", attrs
    assert attrs["AA_KIND"] == "RECT", attrs
    assert abs(float(attrs["AA_W"]) - 400.0) < 1e-6, attrs
    assert abs(float(attrs["AA_H"]) - 300.0) < 1e-6, attrs
    assert abs(float(attrs["AA_AREA"]) - 120000.0) < 1e-6, attrs
    assert layer_of_block(path, "AA_COLUMN_C1") - {"0"} == {LAYERS["column"]}

    g1 = block_geometry(path, "AA_COLUMN_C1")
    kinds1 = sorted(x["type"] for x in g1)
    assert kinds1.count("SOLID") == 1, kinds1
    assert kinds1.count("LWPOLYLINE") == 1, kinds1

    # 2. 圆柱 D500：24 扇形 + 1 圆
    c2 = create_column(s, "C2", (6000.0, 3000.0), 500.0, kind="circle")
    assert c2["kind"] == "CIRCLE", c2
    assert abs(c2["area"] - 3.141592653589793 * 250.0 ** 2) < 1e-3, c2
    kinds2 = sorted(x["type"] for x in block_geometry(path, "AA_COLUMN_C2"))
    assert kinds2.count("SOLID") == 24, kinds2
    assert kinds2.count("CIRCLE") == 1, kinds2

    # 3. 转角写入属性（几何真实旋转，不依赖块旋转）
    c3 = create_column(s, "C3", (8000.0, 1000.0), 400.0, 400.0, angle=30.0)
    assert abs(float(s.attributes("AA_COLUMN_C3")["AA_ANGLE"]) - 30.0) < 1e-6

    # 4. 拒绝：重名、未知类型、非正尺寸
    for kwargs, msg in (
        (dict(column_id="C1", at=(0.0, 0.0), w=200.0), "重名"),
        (dict(column_id="C9", at=(0.0, 0.0), w=200.0, kind="TRI"), "类型"),
        (dict(column_id="C9", at=(0.0, 0.0), w=-100.0), "尺寸"),
    ):
        try:
            create_column(s, **kwargs)
        except CadError as e:
            assert "已存在" in str(e) or "类型" in str(e) or "正实数" in str(e), (msg, e)
        else:
            raise AssertionError("应被拒绝：%s" % msg)

    print("柱: 矩形 %s mm², 圆柱 %s mm², 转角 %s°" % (c1["area"], round(c2["area"], 1), c3["angle"]))
    print("PASS test_column")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
