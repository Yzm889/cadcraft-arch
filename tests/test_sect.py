"""剖面验收（v1.0.17，B6 第四项：按楼层生成立面剖切）。

要点：
  · 地坪线 + 两道外墙内皮 + 每层楼板（板顶粗 / 板底细）+ 屋面板
  · 平屋顶女儿墙只在外墙位置画两道窄矩形（不再是横贯整宽的大框）
  · 标高：各层楼面 + 屋面共 5 个
  · 层高 <=0 / 宽 <=0 / 楼板 <=0 / 外墙过厚 / 双坡无脊高 / 重名 拒绝
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
    create_section,
    layer_of_block,
)

OUT = ROOT / "samples"


def counts(g):
    return (sum(1 for x in g if x["type"] == "LINE"),
            len([x for x in g if x["type"] == "TEXT"]))


def main() -> int:
    path = OUT / "test_sect.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    floors = [{"no": "1", "height": 3600.0},
              {"no": "2", "height": 3600.0},
              {"no": "3", "height": 3300.0}]
    r = create_section(s, "P1", (0.0, 0.0), 6000.0, floors, (), "BOTH", 100.0, "FLAT", 1200.0)
    assert r["floors"] == 3 and abs(r["top"] - 10500.0) < 1e-6, r
    assert abs(r["total"] - 11800.0) < 1e-6, r   # 10500 + 板 100 + 女儿墙 1200
    g = block_geometry(path, "AA_SECTION_P1")
    nl, nt = counts(g)
    assert (nl, nt) == (35, 4), (nl, nt, [x["type"] for x in g])

    layers = layer_of_block(path, "AA_SECTION_P1")
    assert LAYERS["elev"] in layers and LAYERS["elevdetail"] in layers, layers
    attrs = s.attributes("AA_SECTION_P1")
    assert attrs["AA_TYPE"] == "SECTION" and attrs["AA_SLAB"] == "100.0000", attrs
    assert attrs["AA_ROWS"].split("~")[0] == "1", attrs["AA_ROWS"]

    # 双坡：檐口/屋脊共 4 条 + 6（地坪/墙/楼板/分界）= ...
    gable = create_section(s, "P2", (8000.0, 0.0), 6000.0, floors, (), "BOTH",
                           100.0, "GABLE", 0.0, 1800.0)
    assert abs(gable["total"] - 12400.0) < 1e-6, gable    # 10500 + 1800 + 100
    g = block_geometry(path, "AA_SECTION_P2")
    nl, nt = counts(g)
    # 1 地坪 + 4 墙带 + 4 楼板 + 4 坡屋面 + 20 标高（4 楼层 + 檐口 + 屋脊）
    assert (nl, nt) == (33, 5), (nl, nt)

    # 剖到的门窗：剖在哪道墙就在那道墙带上断墙 + 窗框 + 玻璃 / 门上亮子 + 窗台挑出
    ops = [{"floor": 1, "h": 2100.0, "sill": 0.0, "kind": "DOOR"},
           {"floor": 2, "h": 1500.0, "sill": 900.0},
           {"floor": 3, "h": 1500.0, "sill": 900.0}]
    cut = create_section(s, "P3", (0.0, 15000.0), 6000.0, floors, ops,
                         "BOTH", 100.0, "FLAT", 1200.0)
    assert cut["openings"] == 3, cut
    g = block_geometry(path, "AA_SECTION_P3")
    nl, nt = counts(g)
    assert (nl, nt) == (55, 4), (nl, nt)
    assert s.attributes("AA_SECTION_P3")["AA_OPENINGS"] == "3"

    # 剖切面穿过两端外墙：两端各挂一樘（BOTH），互不干扰
    both = create_section(s, "P4", (0.0, 30000.0), 6000.0, floors,
                          [{"floor": 1, "h": 2100.0, "sill": 0.0, "kind": "DOOR",
                            "side": "LEFT"},
                           {"floor": 2, "h": 1500.0, "sill": 900.0, "side": "RIGHT"}],
                          "BOTH", 100.0, "FLAT", 1200.0)
    assert both["openings"] == 2, both
    g = block_geometry(path, "AA_SECTION_P4")
    nl, nt = counts(g)
    assert (nl, nt) == (47, 4), (nl, nt)

    # 被剖到的室内隔墙 + 梁：隔墙 2 条竖线，梁 2 侧 + 1 底 = 3 条
    inner = create_section(s, "P5", (0.0, 45000.0), 6000.0, floors, (),
                          "BOTH", 100.0, "FLAT", 1200.0, 0.0, 240.0, True, 0.0,
                          [{"x": 2400.0, "thick": 120.0}],
                          [{"floor": 2, "x0": 240.0, "x1": 5760.0, "h": 500.0}])
    assert inner["inner_walls"] == 1 and inner["beams"] == 1, inner
    g = block_geometry(path, "AA_SECTION_P5")
    nl, nt = counts(g)
    assert (nl, nt) == (40, 4), (nl, nt)
    a5 = s.attributes("AA_SECTION_P5")
    assert a5["AA_INWALLS"] == "1" and a5["AA_BEAMS"] == "1", a5

    # 隔墙上也开洞（120 薄墙）：墙带在 0..2100 断开，只留洞口上口 + 门扇冒头线
    po = create_section(s, "P6", (0.0, 60000.0), 6000.0, floors, (),
                        "BOTH", 100.0, "FLAT", 1200.0, 0.0, 240.0, True, 0.0,
                        [{"x": 2400.0, "thick": 120.0,
                          "openings": [{"floor": 1, "h": 2100.0, "sill": 0.0,
                                        "kind": "DOOR"}]}])
    assert po["inner_walls"] == 1 and po["openings"] == 0, po
    g = block_geometry(path, "AA_SECTION_P6")
    nl, nt = counts(g)
    assert (nl, nt) == (39, 4), (nl, nt)

    # 隔墙压到外墙 / 梁方向反了 -> 拒绝
    try:
        create_section(s, "PX", (0.0, 0.0), 6000.0, floors, (), "BOTH",
                       100.0, "FLAT", 1200.0, 0.0, 240.0, True, 0.0,
                       [{"x": 100.0, "thick": 120.0}])
    except CadError as e:
        assert "压在外墙" in str(e), e
    else:
        raise AssertionError("隔墙压外墙应被拒绝")

    try:
        create_section(s, "PX", (0.0, 0.0), 6000.0, floors, (), "BOTH",
                       100.0, "FLAT", 1200.0, 0.0, 240.0, True, 0.0, (),
                       [{"floor": 2, "x0": 3000.0, "x1": 2000.0}])
    except CadError as e:
        assert "大于 x0" in str(e), e
    else:
        raise AssertionError("梁 x1<=x0 应被拒绝")

    # 同一道墙上两个洞口竖向叠着 -> 拒绝
    try:
        create_section(s, "PX", (0.0, 0.0), 6000.0, floors,
                       [{"floor": 1, "h": 900.0, "sill": 0.0},
                        {"floor": 1, "h": 900.0, "sill": 300.0}])
    except CadError as e:
        assert "重叠" in str(e), e
    else:
        raise AssertionError("剖面同墙洞口重叠应被拒绝")

    # 半剖（side=LEFT）时，落在右端（没画墙带）的洞口 → 拒绝
    try:
        create_section(s, "PX", (0.0, 0.0), 6000.0, floors,
                       [{"floor": 2, "h": 1500.0, "sill": 900.0, "side": "RIGHT"}],
                       "LEFT", 100.0, "FLAT", 1200.0)
    except CadError as e:
        assert "没有剖开" in str(e), e
    else:
        raise AssertionError("半剖下落在未剖端的洞口应被拒绝")

    # 剖到右侧（side=RIGHT）：墙带落在 宽-墙厚..宽，对侧只留一条细线
    pr = create_section(s, "P9", (0.0, 7000.0), 6000.0, floors,
                        [{"floor": 2, "h": 1500.0, "sill": 900.0, "side": "RIGHT"}],
                        "RIGHT", 100.0, "FLAT", 1200.0)
    assert pr["openings"] == 1, pr
    assert s.attributes("AA_SECTION_P9")["AA_OPENINGS"] == "1"

    # 拒绝
    for kw, msg in (({"width": 0.0}, "剖面宽度"),
                    ({"roof": "DOME"}, "屋顶形式"),
                    ({"slab": 0.0}, "楼板厚"),
                    ({"wall": 4000.0}, "外墙厚")):
        args = {"floors": floors}
        args.update({k: v for k, v in kw.items() if k == "roof"})
        try:
            create_section(s, "PX", (0.0, 0.0), kw.get("width", 6000.0),
                           floors, (), "LEFT", kw.get("slab", 100.0),
                           kw.get("roof", "FLAT"), 1200.0, 0.0,
                           kw.get("wall", 240.0))
        except CadError as e:
            assert msg in str(e), e
        else:
            raise AssertionError("%r 应被拒绝" % (kw,))

    try:
        create_section(s, "PX", (0.0, 0.0), 6000.0, floors, (), "LEFT",
                       100.0, "GABLE", 0.0, 0.0)
    except CadError as e:
        assert "脊高" in str(e), e
    else:
        raise AssertionError("双坡无脊高应被拒绝")

    try:
        create_section(s, "P1", (0.0, 0.0), 6000.0, floors, (), "LEFT")
    except CadError as e:
        assert "已存在" in str(e), e
    else:
        raise AssertionError("重复编号应被拒绝")

    print("剖面: 3 层顶 10500 / 板 100 / 女儿墙 1200 / 总高 11800 / 4 个标高")
    print("PASS test_sect")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
