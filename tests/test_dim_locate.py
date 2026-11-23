"""M-DIM ① 门窗定位尺寸（第一道尺寸链）验收。

口径（GB/T 50001 平面三道尺寸：洞口/定位 -> 轴线 -> 总尺寸）：
  annotate(locate=True) 在外墙第一道尺寸线上把链补全：
  墙端 -> 洞口边 -> 洞口边 -> ... -> 墙端；洞口宽那一段就是原有的洞口尺寸，不重复画。
断言：
  - 链完整：每道外墙第一道线上的分段测量值合计 == 墙长（轴线长）；
  - 分段全部落在 AA-DIM 层、与洞口尺寸同一条线（离墙中心线 = opening_off）；
  - 默认 annotate() 行为不变；重跑幂等；关掉 locate 后恢复并清干净；
  - verify 不报 dim_chain_total / dim_chain_overlap；
  - CLI `dim --locate` 与 MCP `aa_dim{locate:true}` 结果一致；
  - rescale 按原选项重画（AA_CFG_DIM 记住选项）。
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
    LAYERS, CadError, Session, annotate, annot_size, auto_rooms, create_opening,
    create_wall, normalize_around, rescale_annotations, verify, wall_data,
)

OUT = ROOT / "samples"
PATH = OUT / "test_dim_locate.dxf"
PATH2 = OUT / "test_dim_locate_rescale.dxf"
CLI_PATH = OUT / "test_dim_locate_cli.dxf"
MCP_PATH = OUT / "test_dim_locate_mcp.dxf"

O_OFF, W_OFF = 900.0, 1600.0


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
        create_opening(s, "D002", "W005", "DOOR", 900.0, 1500.0, 2100.0)   # 内墙门，默认不标
    create_opening(s, "D001", "W001", "DOOR", 1000.0, 1000.0, 2100.0)
    create_opening(s, "C001", "W002", "WINDOW", 1500.0, 2400.0, 1500.0)
    create_opening(s, "C002", "W003", "WINDOW", 1200.0, 1500.0, 1500.0)
    create_opening(s, "C003", "W003", "WINDOW", 1200.0, 4800.0, 1500.0)
    assert auto_rooms(s)["rooms"] == (2 if inner else 1)
    return s


def dims(s: Session) -> list[dict]:
    return [e for e in s.entities().get("entities", []) if e["type"] == "Dimension"]


def first_tier(s: Session, wid: str, tier_off: float = O_OFF) -> list[float]:
    """某道墙第一道尺寸线（离墙中心线 = O_OFF）上的分段测量值，按沿墙起点排序。"""
    w = next(x for x in wall_data(s) if x["id"] == wid)
    p1, p2 = tuple(w["p1"]), tuple(w["p2"])
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    ln = math.hypot(dx, dy)
    ux, uy = dx / ln, dy / ln
    out = []
    for e in dims(s):
        g = e["geometry"]
        dp = g["defpt"]
        off = abs(-(dp["x"] - p1[0]) * uy + (dp["y"] - p1[1]) * ux)
        if abs(off - tier_off) > 1.0:
            continue
        a = g["p13"]
        b = g["p14"]
        ta = (a["x"] - p1[0]) * ux + (a["y"] - p1[1]) * uy
        tb = (b["x"] - p1[0]) * ux + (b["y"] - p1[1]) * uy
        if min(ta, tb) < -1.0 or max(ta, tb) > ln + 1.0:
            continue
        out.append((min(ta, tb), float(g["measurement"])))
    out.sort()
    return [m for _t, m in out]


def dim_flags(s: Session) -> dict:
    if not s.reference("AA_CFG_DIM"):
        return {}
    return s.attributes("AA_CFG_DIM")


def main() -> int:
    s = build(PATH)

    # 0) 默认行为不变：外墙 4 + 外墙洞口 4 + 总尺寸 4 = 12；内墙 W005 及其门不标
    base = annotate(s, O_OFF, W_OFF)
    assert base["dims"] == 12, base
    assert base["locate"] == 0 and base["thickness"] == 0 and base["coords"] == 0, base
    assert not dim_flags(s), dim_flags(s)

    # 1) locate：每道外墙一条完整的链
    res = annotate(s, O_OFF, W_OFF, locate=True)
    # W001 两段 / W002 两段 / W003 三段 / W004 一段 = 8
    assert res["locate"] == 8, res
    assert res["dims"] == 12 + 8, res
    assert res["walls"] == 4 and res["openings"] == 4 and res["totals"] == 4, res

    assert first_tier(s, "W001") == [500.0, 1000.0, 4500.0], first_tier(s, "W001")
    assert first_tier(s, "W002") == [1650.0, 1500.0, 1650.0], first_tier(s, "W002")
    assert first_tier(s, "W003") == [900.0, 1200.0, 2100.0, 1200.0, 600.0], first_tier(s, "W003")
    assert first_tier(s, "W004") == [4800.0], first_tier(s, "W004")
    for wid in ("W001", "W002", "W003", "W004"):
        w = next(x for x in wall_data(s) if x["id"] == wid)
        assert abs(sum(first_tier(s, wid)) - w["len"]) < 0.01, wid
    # 内墙没有第一道尺寸
    assert first_tier(s, "W005") == [], first_tier(s, "W005")

    got = dims(s)
    assert len(got) == 20, len(got)
    assert all(e["layer"] == LAYERS["dim"] for e in got), {e["layer"] for e in got}
    flags = dim_flags(s)
    assert flags.get("AA_LOCATE") == "1" and flags.get("AA_THICK") == "0", flags

    # 2) verify：链合计 == 外道墙长，不报重叠/合计不符
    v = verify(s)
    assert v["count"] == 0, v["issues"]
    assert v["stats"]["dimensions"] == 20, v["stats"]

    # 3) 幂等；关掉 locate 后恢复默认并清干净
    again = annotate(s, O_OFF, W_OFF, locate=True)
    assert again["dims"] == 20 and len(dims(s)) == 20, again
    off = annotate(s, O_OFF, W_OFF)
    assert off["dims"] == 12 and len(dims(s)) == 12, off
    assert first_tier(s, "W001") == [1000.0], first_tier(s, "W001")
    assert dim_flags(s).get("AA_LOCATE") == "0", dim_flags(s)

    # 4) clear=False 时不允许叠加 M-DIM 标注（会重影）
    try:
        annotate(s, O_OFF, W_OFF, clear=False, locate=True)
    except CadError as exc:
        assert "clear" in str(exc), str(exc)
    else:
        raise AssertionError("clear=False + locate 应该拒绝")
    assert len(dims(s)) == 12, len(dims(s))

    # CLI / MCP 用的副本在改比例之前拷（仍是 1:100）
    shutil.copyfile(PATH, CLI_PATH)
    shutil.copyfile(PATH, MCP_PATH)

    # 5) rescale：按 AA_CFG_DIM 记住的选项重画，字高随比例变。
    #    另起一张没有内墙的图：带 T 接内墙的图上 rescale 重建房间本来就失败（既有缺陷，
    #    HEAD 的代码同样复现），不拿它当 M-DIM 的验收条件。
    s2 = build(PATH2, inner=False)
    annotate(s2, O_OFF, W_OFF, locate=True)
    rs = rescale_annotations(s2, 50.0)
    assert rs["dims"] == 20, rs
    t50 = annot_size(9.0, 50.0)      # 1:50 时第一道尺寸线离墙中心线 450
    assert first_tier(s2, "W003", t50) == [900.0, 1200.0, 2100.0, 1200.0, 600.0], first_tier(s2, "W003", t50)
    gp = s2.run([("dimstyle.list", {"name": "AA-DIM"})], save=False).last()
    assert float(gp["style"]["textHeight"]) == 125.0, gp
    assert dim_flags(s2).get("AA_LOCATE") == "1", dim_flags(s2)

    # 6) CLI
    cli = [sys.executable, str(ROOT / "tools" / "aa_cmd.py")]
    r = subprocess.run(cli + ["dim", str(CLI_PATH), "--locate",
                              "--opening-off", "900", "--wall-off", "1600"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr or r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] and out["locate"] == 8 and out["dims"] == 20, out

    # 7) MCP
    out = aa_mcp.call_tool("aa_dim", {"path": str(MCP_PATH), "opening_off": O_OFF,
                                      "wall_off": W_OFF, "locate": True})
    assert out["ok"] and out["locate"] == 8 and out["dims"] == 20, out

    print("PASS test_dim_locate (locate=%d, dims=%d)" % (res["locate"], res["dims"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
