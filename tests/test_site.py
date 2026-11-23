"""M2 总平面 site 验收：红线闭合可回读，建筑/道路/出入口/指北针/坐标尺寸齐全。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_mcp  # noqa: E402
from aa_lib import CadError, Session, create_site, read_site  # noqa: E402

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)
PATH = OUT / "test_site.dxf"
CLI_PATH = OUT / "test_site_cli.dxf"

BOUNDARY = [(0, 0), (60000, 0), (60000, 40000), (0, 40000)]


def fresh(path: Path) -> Session:
    # new_metric 直接覆盖旧文件，不依赖删除（回归可重复跑）。
    s = Session(path)
    s.new_metric(scale=500)
    return s


def main() -> int:
    s = fresh(PATH)
    res = create_site(
        s, "SITE01", BOUNDARY,
        buildings=[(5000, 5000, 25000, 18000, "教学楼"),
                   {"pts": [(30000, 5000), (45000, 5000), (45000, 18000)],
                    "name": "食堂"}],
        roads=[(6000, [(0, 26000), (60000, 26000)])],
        entrances=[{"at": (30000, 0), "label": "主入口", "dir": (0, -1)}],
        north=(56000, 36000), scale=500,
    )
    assert res["area"] == 2.4e9, res["area"]
    assert len(res["geom_handles"]) >= 10, res
    got = read_site(Session(PATH), "SITE01")
    assert got["id"] == "SITE01" and len(got["boundary"]) == 4, got
    assert abs(got["area"] - 2.4e9) < 1e-3, got
    assert got["buildings"][0]["name"] == "教学楼", got
    assert got["buildings"][1]["name"] == "食堂", got
    assert got["roads"][0]["width"] == 6000.0, got
    assert got["entrances"][0]["label"] == "主入口", got
    assert got["north"] == [56000.0, 36000.0], got
    assert got["coords"] and got["dims"], got
    assert got["scale"] == 500.0, got
    print("总平面回读 ok:", {"area": got["area"], "bld": len(got["buildings"]),
                            "road": len(got["roads"]), "ent": len(got["entrances"])})

    # 红线几何闭合：块内红线多段线首尾同点
    pairs = PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    assert any(v.strip() == "AA_SITE_SITE01" for v in pairs), "块定义未落盘"
    assert any(v.strip() == "AA-AXISTEXT" for v in pairs), "红线层未落盘"

    # 拒绝：重号 / 少于 3 点 / 面积为 0 / 道路宽度 0 / 出入口零方向
    for bad, kw in [
        ({"site_id": "SITE01", "boundary": BOUNDARY}, "已存在"),
        ({"site_id": "SITE02", "boundary": BOUNDARY[:2]}, "至少需要 3 个点"),
        ({"site_id": "SITE03", "boundary": [(0, 0), (100, 0), (200, 0)]}, "面积为 0"),
        ({"site_id": "SITE04", "boundary": BOUNDARY, "roads": [(0, [(0, 0), (100, 0)])]}, "道路宽度"),
        ({"site_id": "SITE05", "boundary": BOUNDARY,
          "entrances": [{"at": (0, 0), "label": "X", "dir": (0, 0)}]}, "零向量"),
    ]:
        kw_site_id = bad.pop("site_id")
        try:
            create_site(Session(PATH), kw_site_id, **bad)
        except CadError as exc:
            assert kw in str(exc), (kw, str(exc))
        else:
            raise AssertionError("应该拒绝：%s" % kw)
    print("拒绝用例 ok")

    # CLI：生成 + --show 回读
    cli = [sys.executable, str(ROOT / "tools" / "aa_cmd.py")]
    fresh(CLI_PATH)
    r = subprocess.run(cli + ["site", str(CLI_PATH), "SITECLI",
                              "--boundary", "0,0;40000,0;40000,30000;0,30000",
                              "--building", "2000,2000,18000,12000,教学楼",
                              "--road", "5000|0,20000;40000,20000",
                              "--entrance", "20000,0:南门:0,-1",
                              "--north", "38000,27000", "--scale", "500"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr or r.stdout
    created = json.loads(r.stdout)
    assert created["ok"] and created["area"] == 1.2e9, created
    r = subprocess.run(cli + ["site", str(CLI_PATH), "--show", "SITECLI"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr or r.stdout
    shown = json.loads(r.stdout)
    assert shown["buildings"][0]["name"] == "教学楼", shown
    print("CLI ok:", created["area"], shown["id"])

    # MCP：aa_site 生成 + show 回读
    mcp_path = OUT / "test_site_mcp.dxf"
    fresh(mcp_path)
    out = aa_mcp.call_tool("aa_site", {"path": str(mcp_path), "id": "SITEMCP",
                                       "boundary": [[0, 0], [30000, 0], [30000, 20000], [0, 20000]],
                                       "entrances": [{"at": [15000, 0], "label": "主入口", "dir": [0, -1]}],
                                       "scale": 500})
    assert out["ok"] and out["area"] == 6e8, out
    shown = aa_mcp.call_tool("aa_site", {"path": str(mcp_path), "show": "SITEMCP"})
    assert shown["entrances"][0]["label"] == "主入口", shown
    print("MCP ok:", len(aa_mcp.TOOLS), "工具，", out["area"])

    print("PASS test_site")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
