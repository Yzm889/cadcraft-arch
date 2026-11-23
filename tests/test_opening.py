"""门窗功能验收测试：写入 + 四条校验规则。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    block_geometry,
    create_opening,
    create_wall,
)

OUT = ROOT / "samples"


def expect_error(fn, keyword: str) -> None:
    try:
        fn()
    except CadError as e:
        assert keyword in str(e), (keyword, str(e))
        print("  拒绝写入 ok:", str(e))
        return
    raise AssertionError("应当拒绝写入但没有拒绝：%s" % keyword)


def main() -> int:
    path = OUT / "test_opening.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()

    create_wall(s, "W001", (0.0, 0.0), (3600.0, 0.0), thick=240.0, kind="EXTERNAL")

    # 1) 门：宽 1800，中心在 900 => 洞口 [0, 1800]
    d1 = create_opening(s, "D001", "W001", "DOOR", width=1800.0, pos=900.0)
    print("door1:", d1)
    attrs = s.attributes("AA_OPENING_D001")
    assert attrs["AA_KIND"] == "DOOR", attrs
    assert attrs["AA_WIDTH"] == "1800.0000", attrs
    assert attrs["AA_WALLID"] == "W001", attrs
    assert attrs["AA_POS"] == "900.0000", attrs
    assert attrs["AA_HEIGHT"] == "2100.0000", attrs
    # 门窗编号按尺寸自动生成：门 1800x2100 => M1821
    assert attrs["AA_NO"] == "M1821", attrs
    # 平开门 1800 >= 1200 => 双扇：2 条洞口边线 + 2 条门扇线 + 2 段开启弧 + 编号 = 7
    assert d1["leaves"] == 2, d1
    assert len(d1["geom_handles"]) == 7, d1["geom_handles"]
    door_texts = [g["text"] for g in block_geometry(path, "AA_OPENING_D001")
                  if g["type"] == "TEXT"]
    assert door_texts == ["M1821"], door_texts
    # 双扇门的每扇弧半径 = 洞宽/2，两个铰点分别落在洞口两端
    arcs = sorted((round(g["r"], 4), round(g["cen"][0], 4))
                  for g in block_geometry(path, "AA_OPENING_D001") if g["type"] == "ARC")
    assert arcs == [(900.0, 0.0), (900.0, 1800.0)], arcs

    # 2) 同一墙上的窗：中心 2700，宽 1200 => 洞口 [2100, 3300]，不与门重叠
    w1 = create_opening(s, "C001", "W001", "WINDOW", width=1200.0, pos=2700.0)
    attrs2 = s.attributes("AA_OPENING_C001")
    assert attrs2["AA_KIND"] == "WINDOW", attrs2
    assert attrs2["AA_HEIGHT"] == "1500.0000", attrs2
    # 四线窗：2 条洞口边线 + 4 条平行细实线（贴墙面 ±t/2、内侧 ±t/4）
    assert len(w1["geom_handles"]) == 7, w1["geom_handles"]

    win = [g for g in block_geometry(path, "AA_OPENING_C001") if g["type"] == "LINE"]
    horiz = sorted({round(g["pts"][0][1], 1) for g in win
                    if abs(g["pts"][0][1] - g["pts"][1][1]) < 1e-6})
    print("窗平行线 y 值:", horiz)
    assert horiz == [-120.0, -60.0, 60.0, 120.0], horiz

    # 2b) 窗框厚是固定构造尺寸（60），不随墙厚等比缩放：
    #     370 墙 => 墙面 ±185、窗框内沿 ±125（不是 ±92.5）
    create_wall(s, "W002", (0.0, -2000.0), (3600.0, -2000.0), thick=370.0)
    create_opening(s, "C002", "W002", "WINDOW", width=1200.0, pos=1800.0)
    win370 = [g for g in block_geometry(path, "AA_OPENING_C002") if g["type"] == "LINE"]
    horiz370 = sorted({round(g["pts"][0][1], 1) for g in win370
                       if abs(g["pts"][0][1] - g["pts"][1][1]) < 1e-6})
    print("370 墙窗平行线 y 值:", horiz370)
    assert horiz370 == [-185.0, -125.0, 125.0, 185.0], horiz370

    # 2c) 窗框厚可以逐樘改：240 墙给 frame=40 => 内沿 ±80；编号可自定义
    create_wall(s, "W003", (0.0, 2000.0), (3600.0, 2000.0), thick=240.0)
    create_opening(s, "C003", "W003", "WINDOW", width=1200.0, pos=1800.0,
                   frame=40.0, no="C-1")
    win40 = [g for g in block_geometry(path, "AA_OPENING_C003") if g["type"] == "LINE"]
    horiz40 = sorted({round(g["pts"][0][1], 1) for g in win40
                      if abs(g["pts"][0][1] - g["pts"][1][1]) < 1e-6})
    print("frame=40 窗平行线 y 值:", horiz40)
    assert horiz40 == [-120.0, -80.0, 80.0, 120.0], horiz40
    assert s.attributes("AA_OPENING_C003")["AA_NO"] == "C-1"
    assert s.attributes("AA_OPENING_C003")["AA_FRAME"] == "40.0000"

    # 2d) 窗框厚非法必须拒绝，且不落任何图元
    expect_error(
        lambda: create_opening(s, "C004", "W003", "WINDOW", width=1200.0, pos=1800.0,
                               frame=-1.0),
        "窗框厚",
    )

    # 3) 墙身必须真的开洞：两侧线在 [0,1800] 与 [2100,3300] 处断开
    geom = block_geometry(path, "AA_WALL_W001")
    sides = [g for g in geom if g["type"] == "LINE"]
    spans = sorted({(round(min(p[0] for p in g["pts"]), 1), round(max(p[0] for p in g["pts"]), 1))
                    for g in sides})
    assert len(sides) == 4, sides
    assert spans == [(1800.0, 2100.0), (3300.0, 3600.0)], spans
    print("wall opening ok:", spans)

    # 4) 重叠必须拒绝：[1200, 3000] 与门 [0,1800] 重叠
    expect_error(
        lambda: create_opening(s, "D002", "W001", "DOOR", width=1800.0, pos=2100.0),
        "重叠",
    )

    # 4) 越界必须拒绝：中心 100 宽 900 => 洞口 [-350, 550]
    expect_error(
        lambda: create_opening(s, "D003", "W001", "DOOR", width=900.0, pos=100.0),
        "超出",
    )

    # 5) 依附不存在的墙必须拒绝
    expect_error(
        lambda: create_opening(s, "D004", "W999", "DOOR", width=900.0, pos=450.0),
        "找不到墙",
    )

    # 6) 宽度为负必须拒绝
    expect_error(
        lambda: create_opening(s, "D005", "W001", "DOOR", width=-1.0, pos=2000.0),
        "必须为正",
    )

    # 7) 图例参数：铰点 / 开向 / 扇数 / 门连窗门扇宽
    create_wall(s, "W004", (0.0, 4000.0), (3600.0, 4000.0), thick=240.0)
    # 7a) 900 平开门默认单扇：铰点、开向可逐樘指定（右铰 + 向 -Y 开 => 弧 180°→270°）
    d3 = create_opening(s, "D010", "W004", "DOOR", width=900.0, pos=900.0,
                        hinge=-1, swing=-1, no="M0921")
    assert d3["leaves"] == 1, d3
    assert len(d3["geom_handles"]) == 5, d3["geom_handles"]
    arcs3 = [g for g in block_geometry(path, "AA_OPENING_D010") if g["type"] == "ARC"]
    assert len(arcs3) == 1, arcs3
    assert (round(arcs3[0]["cen"][0], 4), round(arcs3[0]["r"], 4)) == (1350.0, 900.0), arcs3
    assert (round(arcs3[0]["a1"]), round(arcs3[0]["a2"])) == (180, 270), arcs3
    assert s.attributes("AA_OPENING_D010")["AA_HINGE"] == "-1"
    assert s.attributes("AA_OPENING_D010")["AA_SWING"] == "-1"
    leaf3 = [g for g in block_geometry(path, "AA_OPENING_D010") if g["type"] == "LINE"]
    # 门扇线必须往 -Y 侧长出去 900（从 -120 到 -1020），不能穿墙
    assert any(abs(g["pts"][0][0] - 1350.0) < 1e-6 and
               sorted(p[1] for p in g["pts"]) == [-1020.0, -120.0] for g in leaf3), leaf3

    # 7b) 双扇可以强制为单扇（leaves=1）
    d4 = create_opening(s, "D011", "W004", "DOOR", width=1500.0, pos=2200.0,
                        leaves=1, no="M1521")
    assert d4["leaves"] == 1, d4
    arcs4 = [g for g in block_geometry(path, "AA_OPENING_D011") if g["type"] == "ARC"]
    assert len(arcs4) == 1 and abs(arcs4[0]["r"] - 1500.0) < 1e-6, arcs4

    # 7c) 门连窗：门扇带弧 + 窗四线 + 中梃；门扇宽可指定
    create_wall(s, "W005", (0.0, 6000.0), (3600.0, 6000.0), thick=240.0)
    dw = create_opening(s, "MC001", "W005", "DOORWIN", width=2400.0, pos=1800.0,
                        height=2400.0, doorpart=900.0)
    assert dw["no"] == "MC2424", dw
    geo = block_geometry(path, "AA_OPENING_MC001")
    # 2 洞口边线 + 1 门扇线 + 1 弧 + 4 窗线 + 1 中梃 + 1 编号 = 10
    assert len(dw["geom_handles"]) == 10, dw["geom_handles"]
    assert len([g for g in geo if g["type"] == "ARC"]) == 1, geo
    # 中梃落在洞口左端 + 门扇宽 = 600 + 900 = 1500 处
    mullion = [g for g in geo if g["type"] == "LINE"
               and abs(g["pts"][0][0] - g["pts"][1][0]) < 1e-6
               and abs(g["pts"][0][0] - 1500.0) < 1e-6]
    assert len(mullion) == 1, geo
    # 窗段只剩洞口右侧 900 宽：四条平行线只跨 [1500, 3000]
    horiz = [g for g in geo if g["type"] == "LINE"
             and abs(g["pts"][0][1] - g["pts"][1][1]) < 1e-6]
    assert len(horiz) == 4, horiz
    assert all(min(p[0] for p in g["pts"]) >= 1500.0 - 1e-6 for g in horiz), horiz

    # 7d) 非法参数必须拒绝
    expect_error(
        lambda: create_opening(s, "D012", "W004", "DOOR", width=900.0, pos=3000.0,
                               leaves=3),
        "leaves",
    )
    expect_error(
        lambda: create_opening(s, "D013", "W004", "DOOR", width=900.0, pos=3000.0,
                               doorpart=1200.0),
        "门扇宽",
    )

    # 8) 图上一共 12 个参照（5 墙 + 7 门窗），失败调用没有留下任何实体
    info = s.info()
    assert info["counts"].get("Block Reference") == 12, info["counts"]
    print("PASS test_opening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
