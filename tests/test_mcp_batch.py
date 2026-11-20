"""MCP 事务层验收（v1.0.2）：batch 批量原子、checkpoint/restore 快照回退。

要点：
  · batch 顺序执行多个工具，全部成功才返回 ok=true，results 逐步可查
  · batch 中途失败 → 图纸字节级还原（零残留），返回 failed_index/failed_tool
  · checkpoint 出快照 → 改图 → restore 回到快照字节
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_mcp  # noqa: E402

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_batch.dxf"
    snap_dir = OUT / ".aa_snap"
    for f in (path,):
        f.unlink(missing_ok=True)
    if snap_dir.exists():
        for f in snap_dir.glob("test_batch-*.dxf"):
            f.unlink()

    aa_mcp.call_tool("aa_new", {"path": str(path)})

    # 1. 全部成功：墙 → 墙 → 门窗 → 房间
    res = aa_mcp.call_tool("aa_batch", {"path": str(path), "ops": [
        {"tool": "aa_wall", "args": {"id": "W001", "p1": [0, 0], "p2": [6000, 0], "thick": 240,
                                     "kind": "EXTERNAL", "ax1": "1", "ax2": "2"}},
        {"tool": "aa_wall", "args": {"id": "W002", "p1": [6000, 0], "p2": [6000, 4800],
                                     "thick": 240, "kind": "EXTERNAL"}},
        {"tool": "aa_opening", "args": {"id": "D001", "wall": "W001", "kind": "DOOR",
                                        "width": 1000, "pos": 1000}},
    ]})
    assert res["ok"] is True, res
    assert res["done"] == 3, res
    assert [x["tool"] for x in res["results"]] == ["aa_wall", "aa_wall", "aa_opening"], res

    # 2. 中途失败：第二项洞口越界 → 整批回滚，字节不变
    before = path.read_bytes()
    bad = aa_mcp.call_tool("aa_batch", {"path": str(path), "ops": [
        {"tool": "aa_wall", "args": {"id": "W003", "p1": [0, 4800], "p2": [6000, 4800],
                                     "thick": 240}},
        {"tool": "aa_opening", "args": {"id": "D002", "wall": "W001", "width": 900,
                                        "pos": 9000}},
    ]})
    assert bad["ok"] is False, bad
    assert bad["failed_index"] == 1 and bad["failed_tool"] == "aa_opening", bad
    assert bad["rolled_back"] is True, bad
    assert path.read_bytes() == before, "回滚后图纸字节必须与调用前一致"

    # 3. 快照 → 改图 → 回退
    ck = aa_mcp.call_tool("aa_checkpoint", {"path": str(path), "label": "before-wall"})
    assert ck["ok"] and Path(ck["snapshot"]).exists(), ck
    snap_bytes = path.read_bytes()
    aa_mcp.call_tool("aa_wall", {"path": str(path), "id": "W004",
                                 "p1": [0, 0], "p2": [0, 4800], "thick": 240})
    assert path.read_bytes() != snap_bytes
    rs = aa_mcp.call_tool("aa_restore", {"path": str(path), "snapshot": ck["id"]})
    assert rs["ok"], rs
    assert path.read_bytes() == snap_bytes, "restore 必须字节级还原"

    # 4. 快照不存在 → 明确报错，不静默
    try:
        aa_mcp.call_tool("aa_restore", {"path": str(path), "snapshot": "nope.dxf"})
    except aa_mcp.CadError as e:
        assert "不存在" in str(e), e
    else:
        raise AssertionError("应拒绝：快照不存在")

    for f in snap_dir.glob("test_batch-*.dxf"):
        f.unlink()

    print("batch: 3 步成功；失败回滚字节一致；快照 %s 可回退" % ck["id"])
    print("PASS test_mcp_batch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
