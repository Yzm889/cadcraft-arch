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
    assert (nl, nt) == (94, 3), (nl, nt, [x["type"] for x in g])

    layers = layer_of_block(path, "AA_ELEVATION_E1")
    assert LAYERS["elev"] in layers and LAYERS["elevdetail"] in layers, layers

    # 左侧三道竖向尺寸（v1.0.30）：内道特征高度 9 段（<500 杂段已并）\+ 中道 4 段 \+ 外道 1 段 = 14
    dims = [e for e in s.entities()["entities"] if e["type"] == "Dimension"]
    assert len(dims) == 14, len(dims)
    vals = sorted(round(float(e["geometry"]["measurement"]), 1) for e in dims)
    assert vals.count(3600.0) == 2 and vals.count(3300.0) == 1, vals
    assert 11700.0 in vals and 1500.0 in vals, vals
    for e in dims:
        g = e["geometry"]
        assert e["layer"] == LAYERS["dim"], e["layer"]
        assert g["defpt"]["x"] < 0, g["defpt"]        # 尺寸线一律在立面左侧
        assert abs(abs(g["p14"]["y"] - g["p13"]["y"]) - g["measurement"]) < 1e-6, g

    attrs = s.attributes("AA_ELEVATION_E1")
    assert attrs["AA_TYPE"] == "ELEVATION" and attrs["AA_ROOF"] == "FLAT", attrs
    assert attrs["AA_ROWS"].split("~")[2] == "3600.0000", attrs["AA_ROWS"]

    # 双坡（山墙三角）+ 无女儿墙
    gable = create_elevation(s, "E2", (8000.0, 0.0), 6000.0, floors,
                             ops[:1], "GABLE", 0.0, rise=1800.0)
    assert abs(gable["total"] - 12300.0) < 1e-6, gable
    g = block_geometry(path, "AA_ELEVATION_E2")
    nl, nt = counts(g)
    # 3（地坪+轮廓）+ 2（楼层线）+ 3（檐口+两坡）+ 9（1 门）+ 20（3 楼层 + 檐口 + 屋脊 5 个标高）
    assert (nl, nt) == (37, 5), (nl, nt)

    # 无窗、无标高
    plain = create_elevation(s, "E3", (0.0, 8000.0), 4000.0,
                             [{"height": 3000.0}], [], "NONE", marks=False)
    assert plain["floors"] == 1 and plain["openings"] == 0, plain

    # 檐口厚度 + 立面轴号（v1.0.28）
    eav = create_elevation(s, "E4", (0.0, 16000.0), 6000.0,
                           [{"no": "1", "height": 3600.0},
                            {"no": "2", "height": 3600.0},
                            {"no": "3", "height": 3300.0}], [], "FLAT", 0.0,
                           eave=200.0, axes=[{"x": 0.0, "label": "1"},
                                             {"x": 6000.0, "label": "3"}])
    assert eav["eave"] == 200.0 and eav["axes"] == ["1", "3"], eav
    g = block_geometry(path, "AA_ELEVATION_E4")
    nl, nt = counts(g)
    # 3（地坪+轮廓）+ 2（楼层线）+ 1（挑檐）+ 3（檐口板厚：板底线+两端封口）
    # + 12（3 个标高）+ 2（2 根轴号的引线）= 23；文字 3 标高 + 2 轴号 = 5
    assert (nl, nt) == (23, 5), (nl, nt, [(x["type"], x["layer"]) for x in g])
    attrs = s.attributes("AA_ELEVATION_E4")
    assert attrs["AA_AXES"] == "1;3" and attrs["AA_EAVE"] == "200.0000", attrs

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

    # E6：dims=False 一条尺寸都不该新增（老图重生成不能凭空多三道线）
    before = len([e for e in s.entities()["entities"] if e["type"] == "Dimension"])
    create_elevation(s, "E6", (0.0, -8000.0), 6000.0, floors, dims=False)
    after = len([e for e in s.entities()["entities"] if e["type"] == "Dimension"])
    assert after == before, f"dims=False 多出 {after - before} 条尺寸"

    print("立面: 3 层顶 10500 / 女儿墙 1200 / 总高 11700 / 7 洞 / 3 标高")
    print("PASS test_elev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
