"""楼梯验收（v1.0.3，B6 第 13 项第一版：直跑 + 双跑）。

要点：
  · 直跑：2 条梯段边线 + steps 条踏步线 + 1 条箭头杆 = steps+3 条 LINE，1 个实心箭头
  · 双跑：外轮廓 4 + 平台分界 2 + 梯井 2 + 2×steps 踏步 + 2 箭头杆 = 2×steps+10 条 LINE，2 箭头
  · 总踏步（双跑 2×steps）、进深、梯井/平台可回读；落在 AA-STAIR
  · 重名 / 错类型 / 步数 <2 / 非正尺寸 / 负梯井 拒绝
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
    create_stair,
    layer_of_block,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_stair.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    # 1. 直跑 1200×10 步×280
    st = create_stair(s, "LT1", (0.0, 0.0), "STRAIGHT", 1200.0, 10, 280.0, 150.0, angle=90.0)
    assert abs(st["run"] - 2800.0) < 1e-6, st
    assert abs(st["depth"] - 2800.0) < 1e-6, st
    g1 = block_geometry(path, "AA_STAIR_LT1")
    lines1 = [x for x in g1 if x["type"] == "LINE"]
    solids1 = [x for x in g1 if x["type"] == "SOLID"]
    assert len(lines1) == 13, (len(lines1), [x["type"] for x in g1])   # 2 边 + 10 踏步 + 1 箭头杆
    assert len(solids1) == 1, [x["type"] for x in g1]
    assert len([x for x in g1 if x["type"] == "TEXT"]) == 1, [x["type"] for x in g1]  # "上"
    ys1 = sorted({round(p[1], 3) for x in lines1 for p in x["pts"]})
    assert ys1[0] == 0.0 and ys1[-1] == 2800.0, ys1
    attrs1 = s.attributes("AA_STAIR_LT1")
    assert attrs1["AA_TYPE"] == "STAIR" and attrs1["AA_ID"] == "LT1", attrs1
    assert attrs1["AA_STEPS"] == "10" and attrs1["AA_STEPS_TOTAL"] == "10", attrs1
    assert abs(float(attrs1["AA_DEPTH"]) - 2800.0) < 1e-6, attrs1
    assert layer_of_block(path, "AA_STAIR_LT1") - {"0"} == {
        LAYERS["stair"], LAYERS["stairarrow"], LAYERS["stairtext"]}   # 直跑没有剖断线

    # 2. 双跑：1200 宽、9 步、井 120、平台 1200 → 深 2×1200+2520 = 4920
    dg = create_stair(s, "LT2", (6000.0, 0.0), "DOGLEG", 1200.0, 9, 280.0, 150.0,
                      well=120.0, landing=1200.0, angle=0.0)
    assert abs(dg["depth"] - 4920.0) < 1e-6, dg
    assert dg["steps_total"] == 18, dg
    g2 = block_geometry(path, "AA_STAIR_LT2")
    lines2 = [x for x in g2 if x["type"] == "LINE"]
    assert len(lines2) == 29, (len(lines2), [x["type"] for x in g2])  # 2×9+8 外框/平台/梯井/剖断/2 杆
    assert len([x for x in g2 if x["type"] == "SOLID"]) == 2, [x["type"] for x in g2]
    assert len([x for x in g2 if x["type"] == "TEXT"]) == 2, [x["type"] for x in g2]  # 上、下
    attrs2 = s.attributes("AA_STAIR_LT2")
    assert attrs2["AA_KIND"] == "DOGLEG" and attrs2["AA_STEPS_TOTAL"] == "18", attrs2
    assert abs(float(attrs2["AA_WELL"]) - 120.0) < 1e-6, attrs2
    assert abs(float(attrs2["AA_LANDING"]) - 1200.0) < 1e-6, attrs2
    assert abs(float(attrs2["AA_DEPTH"]) - 4920.0) < 1e-6, attrs2
    assert attrs2["AA_LEVEL"] == "MIDDLE" and attrs2["AA_UPSIDE"] == "LEFT", attrs2
    assert layer_of_block(path, "AA_STAIR_LT2") - {"0"} == {
        LAYERS["stair"], LAYERS["stairarrow"], LAYERS["stairtext"],
        LAYERS["stairbreak"]}  # 中层有红剖断线

    # 2b. 首层：只画第一跑 + 45° 剖断，无箭头
    fs = create_stair(s, "LT3", (12000.0, 0.0), "DOGLEG", 1200.0, 9, 280.0, 150.0,
                      well=120.0, landing=1200.0, angle=0.0, level="FIRST", side="RIGHT")
    g3 = block_geometry(path, "AA_STAIR_LT3")
    assert len([x for x in g3 if x["type"] == "LINE"]) == 9, [x["type"] for x in g3]  # 2 边 + 45° 剖断 + 6 踏步（w=1200）
    assert not [x for x in g3 if x["type"] == "SOLID"], [x["type"] for x in g3]
    assert s.attributes("AA_STAIR_LT3")["AA_UPSIDE"] == "RIGHT"
    assert abs(fs["depth"] - 4920.0) < 1e-6, fs

    # 2c. 顶层：两跑全画，只有"下"
    tp = create_stair(s, "LT4", (18000.0, 0.0), "DOGLEG", 1200.0, 9, 280.0, 150.0,
                      well=120.0, landing=1200.0, angle=0.0, level="TOP")
    g4 = block_geometry(path, "AA_STAIR_LT4")
    assert len([x for x in g4 if x["type"] == "LINE"]) == 27, [x["type"] for x in g4]
    assert len([x for x in g4 if x["type"] == "SOLID"]) == 1, [x["type"] for x in g4]
    texts4 = [x["text"] for x in g4 if x["type"] == "TEXT"]
    assert texts4 == ["下"], texts4
    assert s.attributes("AA_STAIR_LT4")["AA_LEVEL"] == "TOP"
    assert abs(tp["depth"] - 4920.0) < 1e-6, tp

    # 3. 拒绝：重名、错类型、步数 <2、零宽、负梯井、零平台
    for kwargs, msg in (
        (dict(stair_id="LT1", at=(0.0, 0.0)), "重名"),
        (dict(stair_id="LT9", at=(0.0, 0.0), kind="SPIRAL"), "类型"),
        (dict(stair_id="LT9", at=(0.0, 0.0), steps=1), "步数"),
        (dict(stair_id="LT9", at=(0.0, 0.0), width=0.0), "宽"),
        (dict(stair_id="LT9", at=(0.0, 0.0), kind="DOGLEG", well=-50.0), "梯井"),
        (dict(stair_id="LT9", at=(0.0, 0.0), kind="DOGLEG", landing=0.0), "平台"),
    ):
        try:
            create_stair(s, **kwargs)
        except CadError as e:
            assert any(k in str(e) for k in ("已存在", "类型", "整数", "正实数", "不能为负")), (msg, e)
        else:
            raise AssertionError("应被拒绝：%s" % msg)

    print("楼梯: 直跑 %s×%s=%s，双跑 %s 步/深 %s" %
          (st["steps"], st["tread"], st["run"], dg["steps_total"], dg["depth"]))
    print("PASS test_stair")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
