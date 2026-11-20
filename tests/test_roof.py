"""屋顶平面验收（v1.0.15，B6 第二项：平 / 双坡 / 四坡 / 单坡）。

要点：
  · 平屋顶：檐口轮廓 + 檐沟内线 2 条多段线，四角雨水口 4 个方框 + 4 条中横线，
    南北两条找坡箭头（2 LINE + 2 SOLID）
  · 双坡：轮廓 + 正脊 1 条（坡屋面不注找坡箭头）
  · 四坡：轮廓 + 正脊 + 四条 45° 斜脊 = 5 条直线
  · 单坡：轮廓 + 檐沟 2 条多段线 + 1 条找坡杆 + 1 箭头
  · 檐口外挑计入平面面积：6000×4000 外挑 600 -> 7200×5200 = 37.44 m2
  · 重名 / 错类型 / 尺寸非正 / 负外挑 / 檐沟过宽 拒绝
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
    create_roof,
    layer_of_block,
)

OUT = ROOT / "samples"


def kinds(g):
    return sum(1 for x in g if x["type"] == "LWPOLYLINE"), \
           sum(1 for x in g if x["type"] == "LINE"), \
           sum(1 for x in g if x["type"] == "SOLID")


def main() -> int:
    path = OUT / "test_roof.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    flat = create_roof(s, "RF1", (0.0, 0.0), "FLAT", 6000.0, 4000.0, 600.0, 300.0)
    assert abs(flat["outer_w"] - 7200.0) < 1e-6, flat
    assert abs(flat["outer_d"] - 5200.0) < 1e-6, flat
    assert abs(flat["area"] - 7200.0 * 5200.0) < 1e-6, flat
    g = block_geometry(path, "AA_ROOF_RF1")
    np, nl, ns = kinds(g)
    assert np == 6, (np, nl, ns)      # 轮廓 + 檐沟 + 4 雨水口
    assert nl == 6, (np, nl, ns)      # 4 雨水口横线 + 2 找坡杆
    assert ns == 2, (np, nl, ns)      # 南北两个箭头
    layers = layer_of_block(path, "AA_ROOF_RF1")
    assert LAYERS["roof"] in layers, layers
    assert LAYERS["roofarrow"] in layers, layers

    attrs = s.attributes("AA_ROOF_RF1")
    assert attrs["AA_TYPE"] == "ROOF" and attrs["AA_KIND"] == "FLAT", attrs
    assert attrs["AA_RIDGE"] == "X" and attrs["AA_GUTTER"] == "300.0000", attrs

    gable = create_roof(s, "RF2", (10000.0, 0.0), "GABLE", 6000.0, 4000.0, ridge="X")
    g = block_geometry(path, "AA_ROOF_RF2")
    np, nl, ns = kinds(g)
    assert (np, nl, ns) == (1, 1, 0), (np, nl, ns)   # 轮廓 / 正脊
    assert s.attributes("AA_ROOF_RF2")["AA_KIND"] == "GABLE"

    hip = create_roof(s, "RF3", (20000.0, 0.0), "HIP", 6000.0, 4000.0)
    g = block_geometry(path, "AA_ROOF_RF3")
    np, nl, ns = kinds(g)
    assert (np, nl, ns) == (1, 5, 0), (np, nl, ns)   # 正脊 + 4 斜脊

    shed = create_roof(s, "RF4", (0.0, 6000.0), "SHED", 6000.0, 4000.0)
    g = block_geometry(path, "AA_ROOF_RF4")
    np, nl, ns = kinds(g)
    assert (np, nl, ns) == (2, 1, 1), (np, nl, ns)   # 轮廓 + 檐沟 / 1 杆 / 1 箭头

    # 脊沿 Y 的镜像口径
    create_roof(s, "RF5", (10000.0, 6000.0), "GABLE", 4000.0, 6000.0, ridge="Y")
    assert s.attributes("AA_ROOF_RF5")["AA_RIDGE"] == "Y"

    # 拒绝
    for bad in ("TRUSS", "flat2", ""):
        try:
            create_roof(s, "RFX", (0.0, 0.0), bad)
        except CadError as e:
            assert "屋顶类型" in str(e), e
        else:
            raise AssertionError("类型 %r 应被拒绝" % bad)

    # 女儿墙（压顶外沿 + 墙内皮）+ 上人孔（v1.0.29）
    guarded = create_roof(s, "RF6", (20000.0, 6000.0), "FLAT", 6000.0, 4000.0,
                          parapet=240.0, hatch={"x": 3000.0, "y": 2000.0,
                                                "size": 700.0})
    assert guarded["parapet"] == 240.0 and guarded["hatch"] == (3000.0, 2000.0, 700.0), guarded
    g = block_geometry(path, "AA_ROOF_RF6")
    np, nl, ns = kinds(g)
    # 6 原有（轮廓 + 檐沟 + 4 雨水口）+ 2 女儿墙 + 1 上人孔方框 = 9 多段线
    # 6 原有 + 1 上人孔对角斜线 = 7 直线；2 箭头；1 注字
    assert (np, nl, ns) == (9, 7, 2), (np, nl, ns)
    assert sum(1 for x in g if x["type"] == "TEXT") == 1, [(x["type"]) for x in g]
    attrs = s.attributes("AA_ROOF_RF6")
    assert attrs["AA_PARAPET"] == "240.0000" and attrs["AA_HATCH"] == "3000.0000,2000.0000,700.0000", attrs

    # 拒绝
    for kw, msg in (({"parapet": 240.0}, "女儿墙"),
                    ({"hatch": {"x": 100.0, "y": 100.0, "size": 700.0}}, "屋面净区")):
        roof_kind = "GABLE" if "parapet" in kw else "FLAT"
        try:
            create_roof(s, "RFY", (0.0, 0.0), roof_kind, **kw)
        except CadError as e:
            assert msg in str(e), e
        else:
            raise AssertionError("%r 应被拒绝" % (kw,))

    for kw, msg in (({"width": 0.0}, "屋面宽与进深"),
                    ({"depth": -1.0}, "屋面宽与进深"),
                    ({"overhang": -10.0}, "檐口外挑"),
                    ({"gutter": 0.0}, "檐沟宽")):
        try:
            create_roof(s, "RFY", (0.0, 0.0), "FLAT", **kw)
        except CadError as e:
            assert msg in str(e), e
        else:
            raise AssertionError("%r 应被拒绝" % kw)

    try:
        create_roof(s, "RFZ", (0.0, 0.0), "FLAT", 6000.0, 4000.0, 600.0, 2000.0)
    except CadError as e:
        assert "净面积" in str(e), e
    else:
        raise AssertionError("檐沟过宽应被拒绝")

    try:
        create_roof(s, "RF1", (0.0, 0.0))
    except CadError as e:
        assert "已存在" in str(e), e
    else:
        raise AssertionError("重复编号应被拒绝")

    print("屋顶: 平/双坡/四坡/单坡 四类图元数与面积 37.44 m2 校验通过")
    print("PASS test_roof")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
