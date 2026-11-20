"""自动轴网验收：按墙推轴、聚类、编号、线型、回读一致、斜墙跳过、重号拒绝。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError, Session, auto_axis, block_geometry, create_wall, layer_of_block,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def main() -> int:
    path = OUT / "test_axis_auto.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()

    # 竖墙 x=0 / 6000 / 10800（其中 6000 有两段，验证聚类）；横墙 y=0 / 4800
    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W002", (6000.0, 0.0), (10800.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W003", (10800.0, 0.0), (10800.0, 4800.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W004", (10800.0, 4800.0), (0.0, 4800.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W005", (0.0, 4800.0), (0.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W006", (6000.0, 0.0), (6000.0, 4800.0), thick=240.0, kind="PARTITION")
    # 斜墙：不参与轴网，应出现在 skipped
    create_wall(s, "W007", (0.0, 0.0), (2400.0, 2400.0), thick=120.0, kind="PARTITION")

    res = auto_axis(s, "AX001", tol=50.0, ext=2400.0)
    assert res["xpos"] == [0.0, 6000.0, 10800.0], res["xpos"]
    assert res["ypos"] == [0.0, 4800.0], res["ypos"]
    assert res["ver"] == "1;2;3", res["ver"]      # 纵向轴线编数字
    assert res["hor"] == "A;B", res["hor"]        # 横向轴线编字母
    assert res["lines"] == 5, res["lines"]        # 3 竖 + 2 横
    assert [s["id"] for s in res["skipped"]] == ["W007"], res["skipped"]

    geom = block_geometry(path, "AA_AXGRID_AX001")
    lines = [g for g in geom if g["type"] == "LINE"]
    circles = [g for g in geom if g["type"] == "CIRCLE"]
    texts = sorted(g["text"] for g in geom if g["type"] == "TEXT")
    assert len(lines) == 5 and len(circles) == 5, (len(lines), len(circles))
    assert texts == ["1", "2", "3", "A", "B"], texts
    assert all(g["lt"] == "CENTER" for g in lines)

    # 竖轴：x 固定、y 从 -2400 到 4800+2400
    vx = {round(p[0], 3) for g in lines for p in [g["pts"][0]]}
    for x in (0.0, 6000.0, 10800.0):
        assert x in vx, vx
    vertical = [g for g in lines if round(g["pts"][0][0], 3) == 6000.0]
    assert vertical[0]["pts"][0][1] == -2400.0 and vertical[0]["pts"][1][1] == 7200.0, vertical[0]

    # 图层：轴线 AA-AXIS、轴号 AA-AXISTEXT
    layers = layer_of_block(path, "AA_AXGRID_AX001")
    assert "AA-AXIS" in layers and "AA-AXISTEXT" in layers, layers

    # 属性回读：模式 AUTO，位置串落盘
    ref = s.reference("AA_AXGRID_AX001")
    attrs = {a["tag"]: a["text"]["value"] for a in ref["geometry"]["attribs"]}
    assert attrs["AA_MODE"] == "AUTO" and attrs["AA_XPOS"].startswith("0.00;"), attrs
    assert attrs["AA_SKIP"] == "W007", attrs

    # 轴号回填：每堵墙的 AX1/AX2 应等于它起点/终点所在的轴线
    assert res["ax_bound"] >= 1, res.get("ax_bound")
    from aa_lib import wall_data
    got = {w["id"]: (w["ax1"], w["ax2"]) for w in wall_data(s)}
    assert got["W001"] == ("1", "2"), got
    assert got["W002"] == ("2", "3"), got
    assert got["W003"] == ("A", "B"), got       # 竖墙两端落在横轴 A/B
    assert got["W007"] == ("", ""), got         # 斜墙不套轴号

    # 同名重来 -> 拒绝，且文件字节不变
    size = path.stat().st_size
    try:
        auto_axis(s, "AX001")
    except CadError as e:
        assert "已存在" in str(e), e
    assert path.stat().st_size == size

    # 先轴后墙：端点离轴 110mm，--snap-axis 应吸到轴上并自动带出轴号
    p1snap = OUT / "test_axis_snap.dxf"
    if p1snap.exists():
        p1snap.unlink()
    p1snap.write_bytes(path.read_bytes())
    s4 = Session(p1snap)
    r4 = create_wall(s4, "W900", (110.0, 110.0), (5990.0, 110.0), thick=240.0,
                     snap_axis=True)
    assert r4["snapped"]["p1"] == [0.0, 0.0], r4
    assert r4["snapped"]["p2"] == [6000.0, 0.0], r4
    assert r4["length"] == 6000.0, r4
    assert (r4["ax1"], r4["ax2"]) == ("1", "2"), r4

    # 容差：把 6000 的墙挪到 6004 仍应合成一根轴（用新图验证）
    p2 = OUT / "test_axis_auto_tol.dxf"
    if p2.exists():
        p2.unlink()
    s2 = Session(p2)
    s2.new_metric()
    create_wall(s2, "A1", (0.0, 0.0), (0.0, 4000.0), thick=240.0)
    create_wall(s2, "A2", (6004.0, 0.0), (6004.0, 4000.0), thick=240.0)
    r2 = auto_axis(s2, "AX002", tol=50.0)
    assert r2["xpos"] == [0.0, 6004.0], r2["xpos"]
    r3p = OUT / "test_axis_auto_tol2.dxf"
    if r3p.exists():
        r3p.unlink()
    s3 = Session(r3p)
    s3.new_metric()
    create_wall(s3, "B1", (0.0, 0.0), (0.0, 4000.0), thick=240.0)
    create_wall(s3, "B2", (6004.0, 0.0), (6004.0, 4000.0), thick=240.0)
    r3 = auto_axis(s3, "AX003", tol=2.0)
    assert len(r3["xpos"]) == 2, r3["xpos"]

    print("PASS test_axis_auto (x=%s y=%s ver=%s hor=%s)" %
          (res["xpos"], res["ypos"], res["ver"], res["hor"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
