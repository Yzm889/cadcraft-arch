"""M-OPEN ① 组合门窗（COMBO）验收。

口径：一个洞口里按顺序拼多樘门窗面板（DOOR/WINDOW），面板间画中梃竖线；
洞口两端的洞口边线、编号、开洞（墙侧线断开）与普通门窗一致。
带形窗 = 纯 WINDOW 面板序列（面板即分格，中梃即窗棂分界），同一实现覆盖。

几何（本地坐标 +X 沿墙、+Y 法向，块插在墙起点）：
  洞口边线 2 + 门面板各（门扇线 + 90° 弧）+ 窗面板 4 线 + 中梃（面板数-1）+ 编号 1 TEXT。
门面板铰点/开向沿用全局 hinge/swing；扇数按面板宽自动（>=1200 双扇）。
hinge=+1 时门面板铰在面板左端。

断言：图元计数与坐标、属性回读（AA_PANELS）、编号 ZM3321（组合门窗按尺寸），
拒绝用例（合计不符 / 缺 panels / 非 COMBO 带 panels / 面板类型 / 面板过窄 / 类型非法 / 洞口重叠），
set_opening 同参重画与平移保面板、改宽拒绝，rescale / copy_floor 原样带过去，
CLI --panels 与 MCP panels 数组，门窗表类型"组合门窗"，verify / audit 不添错。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_mcp  # noqa: E402
from aa_lib import (  # noqa: E402
    CadError, Session, audit, auto_rooms, block_geometry, copy_floor,
    create_opening, create_room, create_wall, normalize_around, opening_data,
    openings_report, rescale_annotations, set_drawing_scale, set_opening, verify,
)

OUT = ROOT / "samples"
PATH = OUT / "test_open_combo.dxf"
RIBBON_PATH = OUT / "test_open_combo_ribbon.dxf"
COPY_PATH = OUT / "test_open_combo_copy.dxf"
CLI_PATH = OUT / "test_open_combo_cli.dxf"
MCP_PATH = OUT / "test_open_combo_mcp.dxf"

PANELS = "D900;W1500;D900"          # 合计 3300


def geom(path: Path, block: str) -> list[dict]:
    return block_geometry(path, block)


def counts(g: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in g:
        out[e["type"]] = out.get(e["type"], 0) + 1
    return out


def expect_reject(fn, keyword: str):
    try:
        fn()
    except CadError as exc:
        assert keyword in str(exc), (keyword, str(exc))
        return
    raise AssertionError("应当拒绝但没有拒绝：%s" % keyword)


def main() -> int:
    path = PATH
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    for wid, p1, p2 in (("W001", (0.0, 0.0), (6000.0, 0.0)),
                        ("W002", (6000.0, 0.0), (6000.0, 4800.0)),
                        ("W003", (6000.0, 4800.0), (0.0, 4800.0)),
                        ("W004", (0.0, 4800.0), (0.0, 0.0))):
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL")
        normalize_around(s, wid)
    create_wall(s, "W005", (3000.0, 0.0), (3000.0, 4800.0), thick=200.0, kind="PARTITION")
    normalize_around(s, "W005")

    # 1) 正常：W002（4800，无 T 接）上 D900+W1500+D900 @2400 => 洞口 [750, 4050]
    res = create_opening(s, "CB01", "W002", "COMBO", 3300.0, 2400.0, panels=PANELS)
    assert res["no"] == "ZM3321", res                     # 组合门窗按尺寸：3300x2100
    assert res["width"] == 3300.0, res
    assert res["panels"] == [("DOOR", 900.0), ("WINDOW", 1500.0), ("DOOR", 900.0)], res

    attrs = s.attributes("AA_OPENING_CB01")
    assert attrs["AA_KIND"] == "COMBO", attrs
    assert attrs["AA_WIDTH"] == "3300.0000", attrs
    assert attrs["AA_HEIGHT"] == "2100.0000", attrs        # 组合门窗默认高 2100
    assert attrs["AA_PANELS"] == PANELS, attrs
    assert attrs["AA_NO"] == "ZM3321", attrs

    g = geom(path, "AA_OPENING_CB01")
    c = counts(g)
    # 洞口边线 2 + 门扇线 2 + 窗四线 4 + 中梃 2 = 10 LINE；门弧 2；编号 1 TEXT
    assert c.get("LINE") == 10 and c.get("ARC") == 2 and c.get("TEXT") == 1, c
    assert len(res["geom_handles"]) == 13, res["geom_handles"]

    lines = [e for e in g if e["type"] == "LINE"]
    horiz = sorted({round(e["pts"][0][1], 1) for e in lines
                    if abs(e["pts"][0][1] - e["pts"][1][1]) < 1e-6})
    assert horiz == [-120.0, -60.0, 60.0, 120.0], horiz    # 窗面板四线（贴墙面 ±120、框内沿 ±60）
    full = sorted(round(e["pts"][0][0], 1) for e in lines
                  if abs(e["pts"][0][0] - e["pts"][1][0]) < 1e-6
                  and abs(e["pts"][0][1] + 120.0) < 1e-6)
    assert full == [750.0, 1650.0, 3150.0, 4050.0], full   # 边线 750/4050 + 中梃 1650/3150
    arcs = sorted((round(e["r"], 1), round(e["cen"][0], 1)) for e in g if e["type"] == "ARC")
    assert arcs == [(900.0, 750.0), (900.0, 3150.0)], arcs  # 两扇门各铰在面板左端

    texts = [e["text"] for e in g if e["type"] == "TEXT"]
    assert texts == ["ZM3321"], texts

    # 回读：opening_data 带出面板序列
    od = {o["id"]: o for o in opening_data(s)}
    assert od["CB01"]["panels"] == [("DOOR", 900.0), ("WINDOW", 1500.0), ("DOOR", 900.0)], od["CB01"]

    # 2) 拒绝用例
    expect_reject(lambda: create_opening(s, "X01", "W001", "COMBO", 3200.0, 2000.0, panels=PANELS),
                  "面板宽合计")
    expect_reject(lambda: create_opening(s, "X02", "W001", "COMBO", 3300.0, 2000.0),
                  "panels")
    expect_reject(lambda: create_opening(s, "X03", "W001", "DOOR", 900.0, 500.0, panels="D900"),
                  "kind=COMBO")
    expect_reject(lambda: create_opening(s, "X04", "W001", "COMBO", 3300.0, 2000.0,
                                         panels="B900;W1500;D900"), "面板类型")
    expect_reject(lambda: create_opening(s, "X05", "W001", "COMBO", 1200.0, 2000.0,
                                         panels="D200;W1000"), "面板宽")
    expect_reject(lambda: create_opening(s, "X06", "W001", "BALCONY", 900.0, 500.0),
                  "门窗类型")
    expect_reject(lambda: create_opening(s, "X07", "W002", "COMBO", 3300.0, 2400.0, panels=PANELS),
                  "重叠")

    # 3) 房间 + 编号侧重画（refresh_opening_labels -> set_opening 同参重画）：面板不丢
    assert auto_rooms(s)["rooms"] == 2
    assert s.attributes("AA_OPENING_CB01")["AA_PANELS"] == PANELS
    assert counts(geom(path, "AA_OPENING_CB01")) == {"LINE": 10, "ARC": 2, "TEXT": 1}

    set_opening(s, "CB01")                                 # 同参重画
    assert s.attributes("AA_OPENING_CB01")["AA_PANELS"] == PANELS
    set_opening(s, "CB01", pos=2600.0)                     # 平移：[950, 4250]
    assert s.attributes("AA_OPENING_CB01")["AA_POS"] == "2600.0000", s.attributes("AA_OPENING_CB01")
    assert s.attributes("AA_OPENING_CB01")["AA_PANELS"] == PANELS
    expect_reject(lambda: set_opening(s, "CB01", width=3400.0), "面板宽合计")

    # 4) rescale：整批重画后面板原样带回
    rescale_annotations(s, 50.0)
    assert s.attributes("AA_OPENING_CB01")["AA_PANELS"] == PANELS
    assert counts(geom(path, "AA_OPENING_CB01")) == {"LINE": 10, "ARC": 2, "TEXT": 1}
    assert verify(s)["count"] == 0, verify(s)["issues"]
    assert audit(s)["count"] == 0, audit(s)["issues"]

    # 5) 门窗表：组合门窗成行
    rep = openings_report(s)
    row = next(r for r in rep["rows"] if r["编号"] == "ZM3321")
    assert row["类型"] == "组合门窗" and row["樘数"] == 1 and row["宽(mm)"] == "3300", row

    # 6) 带形窗：纯窗面板序列（5x1200=6000 @6600 墙，两端各留 300 垛）
    rp = RIBBON_PATH
    rp.unlink(missing_ok=True)
    sr = Session(rp)
    sr.new_metric()
    create_wall(sr, "W009", (0.0, -3000.0), (6600.0, -3000.0), thick=240.0, kind="EXTERNAL")
    rib = create_opening(sr, "RB01", "W009", "COMBO", 6000.0, 3300.0,
                         panels="W1200;W1200;W1200;W1200;W1200")
    assert rib["no"] == "ZM6021", rib
    cg = counts(geom(rp, "AA_OPENING_RB01"))
    # 边线 2 + 5 面板 x4 线 + 中梃 4 = 26 LINE；无门无弧
    assert cg == {"LINE": 26, "TEXT": 1}, cg
    mids = sorted(round(e["pts"][0][0], 1) for e in geom(rp, "AA_OPENING_RB01")
                  if e["type"] == "LINE" and abs(e["pts"][0][0] - e["pts"][1][0]) < 1e-6
                  and abs(e["pts"][0][1] + 120.0) < 1e-6)
    assert mids == [300.0, 1500.0, 2700.0, 3900.0, 5100.0, 6300.0], mids

    # 7) 楼层复制：组合门窗按构件数据重建，面板序列带过去
    cp = COPY_PATH
    cp.unlink(missing_ok=True)
    sc = Session(cp)
    sc.new_metric()
    set_drawing_scale(sc, 100, rescale=False)
    wids = []
    for i, (a, b) in enumerate((
            ((0.0, 0.0), (6000.0, 0.0)),
            ((6000.0, 0.0), (6000.0, 4000.0)),
            ((6000.0, 4000.0), (0.0, 4000.0)),
            ((0.0, 4000.0), (0.0, 0.0))), 1):
        wid = "W%03d" % i
        create_wall(sc, wid, a, b, thick=240.0, kind="EXTERNAL", floor=1)
        wids.append(wid)
    create_opening(sc, "CB01", "W001", "COMBO", 3300.0, 2400.0, panels=PANELS)
    create_room(sc, "R001", wids, "活动室")
    cf = copy_floor(sc, 1, 2, offset=(0.0, 5000.0), prefix="2")
    assert cf["openings"] == ["2CB01"], cf
    ca = sc.attributes("AA_OPENING_2CB01")
    assert ca["AA_PANELS"] == PANELS and ca["AA_KIND"] == "COMBO" and ca["AA_WALLID"] == "2W001", ca
    assert counts(geom(cp, "AA_OPENING_2CB01")) == {"LINE": 10, "ARC": 2, "TEXT": 1}

    # 8) CLI：--panels "D900;W1500;D900"
    cli = [sys.executable, str(ROOT / "tools" / "aa_cmd.py")]
    CLI_PATH.unlink(missing_ok=True)
    for args in (["new", str(CLI_PATH)],
                 ["wall", str(CLI_PATH), "W001", "--p1", "0,0", "--p2", "6000,4800",
                  "--thick", "240", "--kind", "EXTERNAL"]):
        r = subprocess.run(cli + args, capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr or r.stdout
    r = subprocess.run(cli + ["opening", str(CLI_PATH), "CB01", "--wall", "W001",
                              "--kind", "COMBO", "--width", "3300", "--pos", "2400",
                              "--panels", PANELS],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr or r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] and out["no"] == "ZM3321" and out["width"] == 3300.0, out
    assert [tuple(p) for p in out["panels"]] == [("DOOR", 900.0), ("WINDOW", 1500.0), ("DOOR", 900.0)], out

    # 9) MCP：panels 数组（字典形式）；先用 Python 建墙
    MCP_PATH.unlink(missing_ok=True)
    sm = Session(MCP_PATH)
    sm.new_metric()
    create_wall(sm, "W001", (0.0, 0.0), (6000.0, 4800.0), thick=240.0, kind="EXTERNAL")
    out = aa_mcp.call_tool("aa_opening", {
        "path": str(MCP_PATH), "id": "CB01", "wall": "W001", "kind": "COMBO",
        "width": 3300, "pos": 2400,
        "panels": [{"kind": "DOOR", "width": 900}, {"kind": "WINDOW", "width": 1500},
                   {"kind": "DOOR", "width": 900}]})
    assert out["ok"] and out["no"] == "ZM3321", out

    print("PASS test_open_combo (panels=%s, geom=13, ribbon=26 lines)" % PANELS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
