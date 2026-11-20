"""立面验收（v1.0.16，B6 第三项：按楼层 + 门窗生成立面）。

要点：
  · 3 层 3600/3600/3300 -> 顶 10500；平屋顶 + 女儿墙 1200 -> 总高 11700
  · 轮廓到压顶、楼层线只画二层/三层楼面、地坪线两端出头
  · 门窗：洞口 + 窗框双线 + 上部亮子 + 中梃分扇 + 窗台线（天正立面做法）；同层重叠直接拒绝
  · 标高：三层各一个三角 + 数字，落在轮廓右侧
  · 宽 <=0 / 错屋顶类型 / 双坡无脊高 / 洞越层 / 洞超宽 / 门超层高 拒绝
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
    create_elevation,
    layer_of_block,
)

OUT = ROOT / "samples"


def counts(g):
    return (sum(1 for x in g if x["type"] == "LINE"),
            len([x for x in g if x["type"] == "TEXT"]))


def main() -> int:
    path = OUT / "test_elev.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    floors = [{"no": "1", "height": 3600.0},
              {"no": "2", "height": 3600.0},
              {"no": "3", "height": 3300.0}]
    ops = [{"floor": 1, "x": 2450.0, "w": 1100.0, "h": 2100.0, "sill": 0.0,
            "kind": "DOOR"}]
    for fl in (1, 2, 3):
        for x in (700.0, 4400.0):
            ops.append({"floor": fl, "x": x, "w": 1200.0, "h": 1500.0, "sill": 900.0})

    r = create_elevation(s, "E1", (0.0, 0.0), 6000.0, floors, ops, "FLAT", 1200.0)
    assert r["floors"] == 3 and abs(r["top"] - 10500.0) < 1e-6, r
    assert abs(r["total"] - 11700.0) < 1e-6, r
    assert r["openings"] == 7, r

    g = block_geometry(path, "AA_ELEVATION_E1")
    nl, nt = counts(g)
    # 3（地坪+两轮廓）+ 2（楼层线）+ 2（压顶）+ 76（6 窗×11 + 1 门×10）+ 12（3 个标高各 4 线）
    assert (nl, nt) == (95, 3), (nl, nt, [x["type"] for x in g])

    layers = layer_of_block(path, "AA_ELEVATION_E1")
    assert LAYERS["elev"] in layers and LAYERS["elevdetail"] in layers, layers

    attrs = s.attributes("AA_ELEVATION_E1")
    assert attrs["AA_TYPE"] == "ELEVATION" and attrs["AA_ROOF"] == "FLAT", attrs
    assert attrs["AA_ROWS"].split("~")[2] == "3600.0000", attrs["AA_ROWS"]

    # 双坡（山墙三角）+ 无女儿墙
    gable = create_elevation(s, "E2", (8000.0, 0.0), 6000.0, floors,
                             ops[:1], "GABLE", 0.0, rise=1800.0)
    assert abs(gable["total"] - 12300.0) < 1e-6, gable
    g = block_geometry(path, "AA_ELEVATION_E2")
    nl, nt = counts(g)
    # 3（地坪+轮廓）+ 2（楼层线）+ 3（檐口+两坡）+ 10（1 门）+ 12（3 标高）
    assert (nl, nt) == (30, 3), (nl, nt)

    # 无窗、无标高
    plain = create_elevation(s, "E3", (0.0, 8000.0), 4000.0,
                             [{"height": 3000.0}], [], "NONE", marks=False)
    assert plain["floors"] == 1 and plain["openings"] == 0, plain

    # 拒绝
    for kw, msg in (({"width": 0.0}, "立面宽度"),
                    ({"roof": "DOME"}, "屋顶形式")):
        try:
            create_elevation(s, "EX", (0.0, 0.0), kw.pop("width", 6000.0),
                             floors, [], **kw)
        except CadError as e:
            assert msg in str(e), e
        else:
            raise AssertionError("%r 应被拒绝" % (kw,))

    try:
        create_elevation(s, "EX", (0.0, 0.0), 6000.0, floors, [], "GABLE", 0.0, rise=0.0)
    except CadError as e:
        assert "脊高" in str(e), e
    else:
        raise AssertionError("双坡无脊高应被拒绝")

    try:
        create_elevation(s, "EX", (0.0, 0.0), 6000.0, floors,
                         [{"floor": 5, "x": 100, "w": 1000, "h": 1000}])
    except CadError as e:
        assert "超出" in str(e), e
    else:
        raise AssertionError("层号越界应被拒绝")

    try:
        create_elevation(s, "EX", (0.0, 0.0), 6000.0, floors,
                         [{"floor": 1, "x": 5600, "w": 1000, "h": 1000}])
    except CadError as e:
        assert "超出立面宽度" in str(e), e
    else:
        raise AssertionError("洞口超宽应被拒绝")

    try:
        create_elevation(s, "EX", (0.0, 0.0), 6000.0, floors,
                         [{"floor": 1, "x": 100, "w": 900, "h": 3800, "sill": 0}])
    except CadError as e:
        assert "高出本层" in str(e), e
    else:
        raise AssertionError("门超层高应被拒绝")

    try:
        create_elevation(s, "EX", (0.0, 0.0), 6000.0, floors,
                         [{"floor": 1, "x": 100, "w": 900, "h": 900, "sill": 0},
                          {"floor": 1, "x": 500, "w": 900, "h": 900, "sill": 300}])
    except CadError as e:
        assert "重叠" in str(e), e
    else:
        raise AssertionError("同层洞口重叠应被拒绝")

    try:
        create_elevation(s, "E1", (0.0, 0.0), 6000.0, floors)
    except CadError as e:
        assert "已存在" in str(e), e
    else:
        raise AssertionError("重复编号应被拒绝")

    print("立面: 3 层顶 10500 / 女儿墙 1200 / 总高 11700 / 7 洞 / 3 标高")
    print("PASS test_elev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
