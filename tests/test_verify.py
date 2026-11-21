"""全图复核 verify 验收（v1.0.49）。

要点：
  · 正常图：轴网 + 墙 + 门窗表 + 楼层表 + 立面 + 三道尺寸，verify 0 issue
  · 坏图要能抓到：轴号重复、墙轴号引用不存在、门窗表漏樘、
    立面楼层行与楼层表不一致、尺寸链分段合计与外道总尺寸不一致
  · verify 只读，不改图；缺表/缺轴网不算错误
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    annotate,
    create_axis_grid,
    create_elevation,
    create_floor_table,
    create_opening,
    create_opening_table,
    create_room,
    create_wall,
    verify,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_verify.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    # 12m × 4.8m，南墙拆成三段（做尺寸链），三层轴网
    create_axis_grid(s, "AX1", 3, 6000.0, 2, 4800.0)
    create_wall(s, "W001", (0.0, 0.0), (4000.0, 0.0), kind="EXTERNAL")
    create_wall(s, "W002", (4000.0, 0.0), (8000.0, 0.0), kind="EXTERNAL")
    create_wall(s, "W003", (8000.0, 0.0), (12000.0, 0.0), kind="EXTERNAL")
    create_wall(s, "W004", (12000.0, 0.0), (12000.0, 4800.0), kind="EXTERNAL")
    create_wall(s, "W005", (12000.0, 4800.0), (0.0, 4800.0), kind="EXTERNAL")
    create_wall(s, "W006", (0.0, 4800.0), (0.0, 0.0), kind="EXTERNAL")
    create_room(s, "R001", ["W001", "W002", "W003", "W004", "W005", "W006"], "教室")

    create_opening(s, "D1", "W001", "DOOR", width=900.0, pos=1500.0, height=2100.0)
    create_opening(s, "C1", "W003", "WINDOW", width=1200.0, pos=2000.0,
                   height=1500.0, sill=900.0)

    create_opening_table(s, "MC1", (0.0, -7000.0))
    floors = [
        {"no": "1", "height": 3900.0, "plan": "建施-01", "name": "一层"},
        {"no": "2", "height": 3600.0, "plan": "建施-02", "name": "二层"},
    ]
    create_floor_table(s, "FT1", (0.0, -11000.0), floors)
    elev = create_elevation(s, "EL1", (0.0, 7000.0), 12000.0, floors, roof="FLAT")
    annotate(s)

    clean = verify(s)
    assert clean["count"] == 0, clean
    assert clean["errors"] == 0 and clean["warnings"] == 0, clean
    assert clean["stats"]["axes"] == 1 and clean["stats"]["dimensions"] > 0, clean
    assert clean["stats"]["opening_tables"] == 1, clean
    assert clean["stats"]["floor_tables"] == 1 and clean["stats"]["floor_sources"] == 1, clean

    # 1) 轴号重复：直接改轴网属性，不改几何
    grid = next(e for e in s.components("AA_AXGRID_")
                if e["geometry"]["block"] == "AA_AXGRID_AX1")
    s.run([("attedit", {"handle": grid["handle"],
                        "values": {"AA_VER": "1;1;3"}})], save=True)
    axis = verify(s)
    assert axis["by_kind"].get("axis_label_duplicate", 0) >= 1, axis

    # 2) 墙轴号引用不存在
    create_wall(s, "W900", (20000.0, 0.0), (21000.0, 0.0), ax1="9")
    ref = verify(s)
    assert ref["by_kind"].get("axis_wall_ref", 0) >= 1, ref

    # 3) 门窗表漏了后加的门窗
    create_opening(s, "D2", "W005", "DOOR", width=800.0, pos=2000.0, height=2100.0,
                   no="M0821")
    table = verify(s)
    assert table["by_kind"].get("opening_table_missing", 0) >= 1, table

    # 4) 立面楼层行被改掉一层
    s.run([("attedit", {"handle": elev["handle"],
                        "values": {"AA_ROWS": "1~0.0000~3900.0000"}})], save=True)
    floor = verify(s)
    assert floor["by_kind"].get("floor_source_mismatch", 0) >= 1, floor

    # 5) 删掉南墙中间一段尺寸：剩下分段合计 8000，外道总尺寸 12000
    dims = [e for e in s.entities().get("entities", [])
            if e.get("type") == "Dimension"]
    middle = None
    for e in dims:
        g = e["geometry"]
        p13, p14 = g.get("p13") or {}, g.get("p14") or {}
        if (abs(float(g.get("measurement") or 0.0) - 4000.0) <= 1.0
                and abs(float(p13.get("y", 0.0))) <= 1.0
                and abs(float(p14.get("y", 0.0))) <= 1.0
                and 3000.0 < min(float(p13["x"]), float(p14["x"])) < 9000.0):
            middle = e
            break
    assert middle is not None, "找不到中间段尺寸"
    s.run([("erase", {"handles": [middle["handle"]]})], save=True)
    chain = verify(s)
    assert chain["by_kind"].get("dim_chain_total", 0) >= 1, chain

    # 只读：文件内容在 verify 前后不变
    before = path.read_bytes()
    verify(s)
    assert path.read_bytes() == before, "verify 不应改图"

    print("干净图:", clean["count"], "轴号:", axis["by_kind"],
          "门窗表:", table["by_kind"], "楼层:", floor["by_kind"],
          "尺寸链:", chain["by_kind"])
    print("PASS test_verify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
