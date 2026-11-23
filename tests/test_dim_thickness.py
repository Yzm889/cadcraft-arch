"""M-DIM ② 墙厚标注验收。

口径：annotate(thickness=True) 给每道墙注一道墙厚尺寸——
  - 尺寸线垂直于墙、放在**墙端之外**（避开第一道尺寸线的文字带），
    p13/p14 落在墙的两个面上，测量值 == 墙厚；
  - 文字被 CAD 推到 p14 一侧，所以 p14 取在相邻墙那一边（室外空当）；
  - 墙端是 T 接 / 共线延续 / 落点或文字进了房间 -> 换另一端；都不行 -> 跳过并报告；
  - 一个墙角只放一道，相邻两墙不挤在同一个角上。
断言：落点几何、四个角各一道、全部在房间外、verify/audit 不添错、
      内墙 T 接被跳过、开放墙端可放、幂等、默认 annotate 清掉、rescale 跟随、CLI/MCP。
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_mcp  # noqa: E402
from aa_lib import (  # noqa: E402
    LAYERS, Session, _in_polygon, annotate, auto_rooms, audit, create_opening,
    create_wall, normalize_around, rescale_annotations, room_data, verify, wall_data,
)

OUT = ROOT / "samples"
PATH = OUT / "test_dim_thickness.dxf"
CLI_PATH = OUT / "test_dim_thickness_cli.dxf"
MCP_PATH = OUT / "test_dim_thickness_mcp.dxf"
PATH2 = OUT / "test_dim_thickness_rescale.dxf"
OPEN_PATH = OUT / "test_dim_thickness_open.dxf"

O_OFF, W_OFF = 900.0, 1600.0
GAP = 250.0            # 墙厚尺寸线离墙端的最小空当：图面 2.5mm @1:100


def build(path: Path, inner: bool = True) -> Session:
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    for wid, p1, p2 in (("W001", (0.0, 0.0), (6000.0, 0.0)),
                        ("W002", (6000.0, 0.0), (6000.0, 4800.0)),
                        ("W003", (6000.0, 4800.0), (0.0, 4800.0)),
                        ("W004", (0.0, 4800.0), (0.0, 0.0))):
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL")
        normalize_around(s, wid)
    if inner:      # 内隔墙，两端都是 T 接
        create_wall(s, "W005", (3000.0, 0.0), (3000.0, 4800.0), thick=200.0, kind="PARTITION")
        normalize_around(s, "W005")
        create_opening(s, "D002", "W005", "DOOR", 900.0, 1500.0, 2100.0)
    create_opening(s, "D001", "W001", "DOOR", 1000.0, 1000.0, 2100.0)
    create_opening(s, "C001", "W002", "WINDOW", 1500.0, 2400.0, 1500.0)
    assert auto_rooms(s)["rooms"] == (2 if inner else 1)
    return s


def dims(s: Session) -> list[dict]:
    return [e for e in s.entities().get("entities", []) if e["type"] == "Dimension"]


def frame(w: dict) -> tuple:
    """墙的局部坐标架：p1、沿墙单位向量、法向、墙长。"""
    p1, p2 = tuple(w["p1"]), tuple(w["p2"])
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    ln = math.hypot(dx, dy)
    ux, uy = dx / ln, dy / ln
    return p1, ux, uy, -uy, ux, ln


def thick_dims(s: Session) -> list[tuple[dict, dict]]:
    """挑出墙厚尺寸：测量值 == 某墙厚，两点各在墙的一个面上且沿墙同站位。返回 (墙, 实体)。"""
    out = []
    for e in dims(s):
        g = e["geometry"]
        m = float(g["measurement"])
        for w in wall_data(s):
            if w["thick"] <= 0 or abs(m - w["thick"]) > 0.01:
                continue
            p1, ux, uy, nx, ny, _ln = frame(w)
            q = [nx * (p["x"] - p1[0]) + ny * (p["y"] - p1[1]) for p in (g["p13"], g["p14"])]
            a = [ux * (p["x"] - p1[0]) + uy * (p["y"] - p1[1]) for p in (g["p13"], g["p14"])]
            if (abs(abs(q[0]) - m / 2) < 0.5 and abs(abs(q[1]) - m / 2) < 0.5
                    and q[0] * q[1] < 0 and abs(a[0] - a[1]) < 1.0):
                out.append((w, e))
                break
    return out


def corner_of(w: dict, e: dict) -> tuple[float, float]:
    g = e["geometry"]
    return ((g["p13"]["x"] + g["p14"]["x"]) / 2.0, (g["p13"]["y"] + g["p14"]["y"]) / 2.0)


def main() -> int:
    s = build(PATH)

    # 0) 默认不注墙厚；audit 基线
    base = annotate(s, O_OFF, W_OFF)
    assert base["dims"] == 10 and base["thickness"] == 0, base   # 内墙门 D002 默认不标
    assert thick_dims(s) == [], thick_dims(s)
    a0 = audit(s)

    # 1) 四道外墙各一道，落在四个不同的墙角
    res = annotate(s, O_OFF, W_OFF, thickness=True)
    assert res["thickness"] == 4 and res["thickness_skipped"] == [], res
    assert res["dims"] == 14, res
    td = thick_dims(s)
    assert len(td) == 4, len(td)
    assert sorted(w["id"] for w, _e in td) == ["W001", "W002", "W003", "W004"]
    corners = [corner_of(w, e) for w, e in td]
    assert len({(round(x), round(y)) for x, y in corners}) == 4, corners

    polys = [tuple(r["pts"]) for r in room_data(s)]
    for w, e in td:
        p1, ux, uy, _nx, _ny, ln = frame(w)
        g = e["geometry"]
        assert abs(float(g["measurement"]) - w["thick"]) < 0.01, (w["id"], g)
        assert e["layer"] == LAYERS["dim"], e
        # 墙角 = 这道墙的一个端点
        cx, cy = corner_of(w, e)
        assert (math.dist((cx, cy), p1) <= 1.0 or math.dist((cx, cy), tuple(w["p2"])) <= 1.0), (w["id"], cx, cy)
        # 尺寸线在墙端之外，离墙角 = 邻墙半厚 120 + 空当 250
        dp = g["defpt"]
        along = ux * (dp["x"] - p1[0]) + uy * (dp["y"] - p1[1])
        assert along < -1.0 or along > ln + 1.0, (w["id"], along, ln)
        assert abs(math.dist((dp["x"], dp["y"]), (cx, cy)) - (120.0 + GAP)) < 1.0, (w["id"], dp)
        # 尺寸线与文字都在房间外
        tm = g["textMid"]
        assert not any(_in_polygon((dp["x"], dp["y"]), poly) for poly in polys), (w["id"], dp)
        assert not any(_in_polygon((tm["x"], tm["y"]), poly) for poly in polys), (w["id"], tm)
        # p14 在相邻墙一侧：文字（textMid）与邻墙同侧，且不落进本墙第一道尺寸线的文字带
        #    即 textMid 离本墙中心线的垂距 < opening_off
        perp = abs(-uy * (tm["x"] - p1[0]) + ux * (tm["y"] - p1[1]))
        assert perp < O_OFF, (w["id"], perp)

    # 2) verify / audit 不添错；verify 把墙厚尺寸识别出来、不混进尺寸链
    v = verify(s)
    assert v["count"] == 0, v["issues"]
    assert v["stats"].get("thickness_dims") == 4, v["stats"]
    a1 = audit(s)
    assert a1["count"] == a0["count"], (a0["issues"], a1["issues"])
    assert "dim_over_axis" not in a1["by_kind"], a1["by_kind"]

    # 3) 连内墙一起：W005 两端都是 T 接 -> 跳过并报告
    res2 = annotate(s, O_OFF, W_OFF, exterior_only=False, thickness=True)
    assert res2["thickness"] == 4 and res2["thickness_skipped"] == ["W005"], res2
    assert res2["walls"] == 5 and res2["dims"] == 17, res2      # 内墙也自成一组成一条总尺寸
    assert s.attributes("AA_CFG_DIM").get("AA_EXTERIOR") == "0", s.attributes("AA_CFG_DIM")

    # 4) 幂等；默认 annotate 清掉墙厚尺寸
    again = annotate(s, O_OFF, W_OFF, thickness=True)
    assert again["thickness"] == 4 and len(dims(s)) == 14, again
    off = annotate(s, O_OFF, W_OFF)
    assert off["thickness"] == 0 and len(dims(s)) == 10, off
    assert thick_dims(s) == [], thick_dims(s)
    assert s.attributes("AA_CFG_DIM").get("AA_THICK") == "0"

    # CLI / MCP 用的副本在改比例之前拷
    shutil.copyfile(PATH, CLI_PATH)
    shutil.copyfile(PATH, MCP_PATH)

    # 5) rescale：墙厚尺寸按原选项重画（另起一张没有内墙的图，理由同 test_dim_locate：
    #    带 T 接内墙的图上 rescale 重建房间是既有失败，与 M-DIM 无关）
    s2 = build(PATH2, inner=False)
    annotate(s2, O_OFF, W_OFF, thickness=True)
    rs = rescale_annotations(s2, 50.0)
    assert rs["dims"] == 14, rs
    td = thick_dims(s2)
    assert len(td) == 4, td
    for w, e in td:
        dp = e["geometry"]["defpt"]
        cx, cy = corner_of(w, e)
        assert abs(math.dist((dp["x"], dp["y"]), (cx, cy)) - (120.0 + GAP / 2)) < 1.0, (w["id"], dp)

    # 6) CLI
    cli = [sys.executable, str(ROOT / "tools" / "aa_cmd.py")]
    r = subprocess.run(cli + ["dim", str(CLI_PATH), "--thickness",
                              "--opening-off", "900", "--wall-off", "1600"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr or r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] and out["thickness"] == 4 and out["dims"] == 14, out

    # 7) MCP
    out = aa_mcp.call_tool("aa_dim", {"path": str(MCP_PATH), "opening_off": O_OFF,
                                      "wall_off": W_OFF, "thickness": True})
    assert out["ok"] and out["thickness"] == 4 and out["dims"] == 14, out

    # 8) 开放墙端（没有邻墙）：尺寸线放在墙端之外，空当只有 250
    OPEN_PATH.unlink(missing_ok=True)
    so = Session(OPEN_PATH)
    so.new_metric()
    create_wall(so, "W1", (0.0, 0.0), (4000.0, 0.0), thick=240.0, kind="EXTERNAL")
    ro = annotate(so, O_OFF, W_OFF, thickness=True)
    assert ro["thickness"] == 1 and ro["thickness_skipped"] == [], ro
    tdo = thick_dims(so)
    assert len(tdo) == 1, tdo
    w, e = tdo[0]
    dp = e["geometry"]["defpt"]
    assert dp["x"] < -1.0 or dp["x"] > 4001.0, dp
    cx, cy = corner_of(w, e)
    assert abs(math.dist((dp["x"], dp["y"]), (cx, cy)) - GAP) < 1.0, dp

    print("PASS test_dim_thickness (thickness=%d, dims=%d)" % (res["thickness"], res["dims"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
