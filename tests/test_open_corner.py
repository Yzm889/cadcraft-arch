"""M-OPEN 转角窗验收（v1.0.64 首个可执行口径）。

口径：两堵互相垂直、共用一个端点的外墙；两侧各一樘纯窗 COMBO 洞口，
从共用角点向墙内延伸；转角柱落在墙中心线交点，4 条 AA-OPEN 线；
两侧洞口共享编号并写 AA_CORNER。任一侧失败整图回滚。

断言：两侧块/柱块存在，洞口位置从角点起算，AA_CORNER 回读，
拒绝（不共角 / 不垂直 / 超墙长 / 含门面板 / 柱过宽 / 重复编号 / 重叠），
失败回滚零残留，CLI 与 MCP 入口可用。
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
    CadError, Session, block_geometry, create_corner_window, create_opening,
    create_wall, opening_data,
)

OUT = ROOT / "samples"
PATH = OUT / "test_open_corner.dxf"
CLI_PATH = OUT / "test_open_corner_cli.dxf"
MCP_PATH = OUT / "test_open_corner_mcp.dxf"


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


def make_base(path: Path) -> Session:
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W002", (0.0, 0.0), (0.0, 4800.0), thick=240.0, kind="EXTERNAL")
    return s


def main() -> int:
    # 1) 正常：W001/W002 共用原点，A 侧 1800、B 侧 1500
    s = make_base(PATH)
    res = create_corner_window(
        s, "CW01", "W001", "W002", 1800.0, 1500.0,
        height=1500.0, sill=900.0, frame=60.0, post=300.0, no="CW01",
    )
    assert res["block"] == "AA_CORNER_CW01"
    assert res["walls"] == ["W001", "W002"]
    assert [o["width"] for o in res["openings"]] == [1800.0, 1500.0]
    assert [o["pos"] for o in res["openings"]] == [900.0, 750.0]
    assert res["openings"][0]["corner"] == "CW01"
    assert res["openings"][1]["corner"] == "CW01"

    assert s.block_exists("AA_OPENING_CW01-A")
    assert s.block_exists("AA_OPENING_CW01-B")
    g = block_geometry(PATH, "AA_CORNER_CW01")
    assert counts(g) == {"LINE": 4}, counts(g)
    corners = [(e["pts"][0], e["pts"][1]) for e in g]
    assert corners[0][0] == (-150.0, -150.0)
    assert corners[2][0] == (150.0, 150.0)

    # 洞口属性：从角点向墙内，编号共享
    od = opening_data(s)
    cw = [o for o in od if o["corner"] == "CW01"]
    assert len(cw) == 2, cw
    assert {o["no"] for o in cw} == {"CW01"}
    assert {o["wallid"] for o in cw} == {"W001", "W002"}
    assert cw[0]["kind"] == "COMBO" and cw[1]["kind"] == "COMBO"
    assert cw[0]["panels"] == [("WINDOW", 1800.0)]
    assert cw[1]["panels"] == [("WINDOW", 1500.0)]

    # 2) 拒绝：墙不共角 / 不垂直 / 超墙长 / 门面板 / 柱过宽 / 重复编号
    s2 = Session(OUT / "test_open_corner_reject.dxf")
    s2.path.unlink(missing_ok=True)
    s2.new_metric()
    create_wall(s2, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s2, "W002", (0.0, 0.0), (0.0, 4800.0), thick=240.0, kind="EXTERNAL")
    create_wall(s2, "W003", (3000.0, 1000.0), (3000.0, 4000.0), thick=240.0, kind="EXTERNAL")
    create_wall(s2, "W004", (0.0, 0.0), (3000.0, 3000.0), thick=240.0, kind="EXTERNAL")

    expect_reject(lambda: create_corner_window(s2, "C1", "W001", "W003", 1800.0, 1500.0),
                  "共用")
    expect_reject(lambda: create_corner_window(s2, "C2", "W001", "W004", 1800.0, 1500.0),
                  "垂直")
    expect_reject(lambda: create_corner_window(s2, "C3", "W001", "W002", 9000.0, 1500.0),
                  "超过墙长")
    expect_reject(lambda: create_corner_window(
        s2, "C4", "W001", "W002", 1800.0, 1500.0, panels_a="D900;W900"),
        "WINDOW 面板")
    expect_reject(lambda: create_corner_window(
        s2, "C5", "W001", "W002", 600.0, 600.0, post=700.0),
        "转角柱宽")
    res2 = create_corner_window(s2, "C6", "W001", "W002", 1800.0, 1500.0)
    expect_reject(lambda: create_corner_window(s2, "C6", "W001", "W002", 1800.0, 1500.0),
                  "已存在")

    # 3) 失败回滚：B 侧已有洞口与转角窗重叠；A 侧已插入也必须整图回滚
    s2.path.unlink(missing_ok=True)
    s2 = make_base(s2.path)
    create_opening(s2, "X01", "W002", "WINDOW", 1500.0, 750.0, height=1500.0, sill=900.0)
    before = s2.path.read_bytes()
    expect_reject(lambda: create_corner_window(
        s2, "CW02", "W001", "W002", 1800.0, 1500.0, post=300.0), "重叠")
    assert s2.path.read_bytes() == before
    assert not s2.block_exists("AA_CORNER_CW02")
    assert not s2.block_exists("AA_OPENING_CW02-A")
    assert not s2.block_exists("AA_OPENING_CW02-B")
    assert s2.block_exists("AA_OPENING_X01")

    # 4) CLI
    CLI_PATH.unlink(missing_ok=True)
    s = make_base(CLI_PATH)
    cmd = [sys.executable, str(ROOT / "tools" / "aa_cmd.py"), "corner-opening",
           str(CLI_PATH), "CW03", "--wall-a", "W001", "--wall-b", "W002",
           "--len-a", "1800", "--len-b", "1500", "--post", "300",
           "--height", "1500", "--sill", "900", "--no", "CW03"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    assert data["ok"] is True
    assert data["block"] == "AA_CORNER_CW03"

    # 5) MCP
    MCP_PATH.unlink(missing_ok=True)
    s = make_base(MCP_PATH)
    data = aa_mcp.call_tool("aa_corner_opening", {
        "path": str(MCP_PATH), "id": "CW04", "wall_a": "W001", "wall_b": "W002",
        "len_a": 1800, "len_b": 1500, "post": 300, "no": "CW04",
    })
    assert data.get("isError") is not True, data
    assert data["block"] == "AA_CORNER_CW04"

    print("OPEN-CORNER PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
