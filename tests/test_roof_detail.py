"""M2 屋面细部验收（v1.0.56）：分格线 / 内天沟 / 坡度注字可回读。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_mcp  # noqa: E402
from aa_lib import (  # noqa: E402
    CadError,
    Session,
    block_geometry,
    create_roof,
    create_roof_detail,
    read_roof_detail,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)
PATH = OUT / "test_roof_detail.dxf"
CLI_PATH = OUT / "test_roof_detail_cli.dxf"
MCP_PATH = OUT / "test_roof_detail_mcp.dxf"


def fresh(path: Path) -> Session:
    s = Session(path)
    s.new_metric(scale=100)
    create_roof(s, "RF1", (0.0, 0.0), "FLAT", 6000.0, 4000.0, 600.0, 300.0)
    return s


def geom_counts(path: Path, block: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for g in block_geometry(path, block):
        out[g["type"]] = out.get(g["type"], 0) + 1
    return out


def main() -> int:
    fresh(PATH)
    res = create_roof_detail(
        Session(PATH), "RD1", "RF1",
        grid={"nx": 3, "ny": 2},
        inner_gutter={"sides": ["S", "N"], "width": 300.0},
        slope=2.0,
    )
    assert res["grid"]["lines"] == 3, res["grid"]
    assert res["inner_gutter"]["bands"] == 2, res["inner_gutter"]
    assert res["slope_arrows"] == 2 and res["slope_text"] == "i=2%", res

    got = read_roof_detail(Session(PATH), "RD1")
    assert got["roof"] == "RF1" and got["grid"]["nx"] == 3 and got["grid"]["ny"] == 2, got
    assert got["grid_lines"] == 3, got
    assert got["inner_gutter"]["sides"] == ["S", "N"], got
    assert abs(got["inner_gutter"]["width"] - 300.0) < 1e-6, got
    assert abs(got["slope"] - 2.0) < 1e-6 and got["slope_arrows"] == 2, got
    assert got["slope_text"] == "i=2%", got
    assert got["at"] == (0.0, 0.0) and got["scale"] == 100.0, got
    counts = geom_counts(PATH, "AA_ROOFD_RD1")
    assert counts.get("LINE") == 9, counts      # 3 分格 + 4 雨水口中线 + 2 找坡杆
    assert counts.get("LWPOLYLINE") == 6, counts  # 2 天沟带 + 4 雨水口方框
    assert counts.get("SOLID") == 2 and counts.get("TEXT") == 1, counts
    print("屋面细部回读 ok:", {"grid": got["grid_lines"], "gutter": got["inner_gutter"]["bands"],
                              "slope": got["slope_text"], "geom": counts})

    # 分格间距口径（另一屋顶，GABLE 两坡）
    s = Session(PATH)
    create_roof(s, "RF2", (10000.0, 0.0), "GABLE", 6000.0, 4000.0, ridge="X")
    res = create_roof_detail(Session(PATH), "RD2", "RF2",
                             grid={"xspace": 1500.0, "yspace": 1000.0}, slope=3.0)
    # GABLE 净区 4800×2800（外挑 600），按最接近的整分格取整：3×3
    assert res["grid"]["nx"] == 3 and res["grid"]["ny"] == 3, res["grid"]
    assert res["slope_arrows"] == 2 and res["slope_text"] == "i=3%", res
    assert abs(res["grid"]["xspace"] - 1600.0) < 1e-6, res["grid"]

    # 拒绝：未知屋顶 / 重号 / 空选项 / 分格数 0 / 天沟方向错 / 天沟过宽 / 坡度 0
    cases = [
        ({"detail_id": "RDX", "roof_id": "RF9", "slope": 2.0}, "找不到屋顶"),
        ({"detail_id": "RD1", "roof_id": "RF1", "slope": 2.0}, "已存在"),
        ({"detail_id": "RDY", "roof_id": "RF1"}, "至少给"),
        ({"detail_id": "RDY", "roof_id": "RF1", "grid": {"nx": 0, "ny": 2}}, "≥1"),
        ({"detail_id": "RDY", "roof_id": "RF1", "inner_gutter": {"sides": ["Z"], "width": 300}}, "N/S/E/W"),
        ({"detail_id": "RDY", "roof_id": "RF1", "inner_gutter": {"sides": ["S"], "width": 3000}}, "净区的一半"),
        ({"detail_id": "RDY", "roof_id": "RF1", "slope": 0}, "坡度百分数"),
    ]
    for kw, msg in cases:
        try:
            create_roof_detail(Session(PATH), **kw)
        except CadError as exc:
            assert msg in str(exc), (msg, str(exc))
        else:
            raise AssertionError("应该拒绝：%s" % kw)
    print("拒绝用例 ok")

    # CLI：生成 + --show 回读
    cli = [sys.executable, str(ROOT / "tools" / "aa_cmd.py")]
    fresh(CLI_PATH)
    r = subprocess.run(cli + ["roof-detail", str(CLI_PATH), "RDC", "--roof", "RF1",
                              "--grid", "3,2", "--inner-gutter", "S:300",
                              "--slope", "2", "--scale", "100"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr or r.stdout
    created = json.loads(r.stdout)
    assert created["ok"] and created["grid"]["lines"] == 3, created
    r = subprocess.run(cli + ["roof-detail", str(CLI_PATH), "--show", "RDC"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr or r.stdout
    shown = json.loads(r.stdout)
    assert shown["slope_text"] == "i=2%" and shown["grid_lines"] == 3, shown
    print("CLI ok:", created["grid"], shown["slope_text"])

    # MCP：生成 + show 回读
    fresh(MCP_PATH)
    out = aa_mcp.call_tool("aa_roof_detail", {
        "path": str(MCP_PATH), "id": "RDM", "roof": "RF1",
        "grid": {"nx": 2, "ny": 2}, "slope": 2.5})
    assert out["ok"] and out["grid"]["lines"] == 2, out
    shown = aa_mcp.call_tool("aa_roof_detail", {"path": str(MCP_PATH), "show": "RDM"})
    assert shown["slope_text"] == "i=2.5%", shown
    print("MCP ok:", len(aa_mcp.TOOLS), "工具，", shown["grid"])

    print("PASS test_roof_detail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
