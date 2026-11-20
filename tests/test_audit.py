"""图面自检 audit 验收（v0.9.8，B1）。

要点：
  · 正常图（四面墙闭合 + 房间文字 + 图幅）audit 必须 0 issue（不误报）
  · 坏图要能抓到：墙端点没接上（wall_endpoint）、房间文字重叠（room_text_overlap）、
    图形超出图幅（outside_sheet）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    audit,
    create_room,
    create_sheet,
    create_wall,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_audit.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()

    # 1. 干净图：6000×4800 闭合房间 + 房间名 + A4 图幅
    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0))
    create_wall(s, "W002", (6000.0, 0.0), (6000.0, 4800.0))
    create_wall(s, "W003", (6000.0, 4800.0), (0.0, 4800.0))
    create_wall(s, "W004", (0.0, 4800.0), (0.0, 0.0))
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], "客厅")
    create_sheet(s, "SH001", "A4", at=(-3000.0, -3000.0))

    clean = audit(s)
    assert clean["count"] == 0, clean
    assert clean["by_kind"] == {}, clean

    # 2. 同一房间再存一次 → 文字重叠
    create_room(s, "R002", ["W001", "W002", "W003", "W004"], "客厅")
    dup = audit(s)
    kinds = dup["by_kind"]
    assert kinds.get("room_text_overlap", 0) >= 1, dup
    assert dup["errors"] == 0, dup        # 重叠只是 warn

    # 3. 一根悬空墙 → 两端都没接上
    create_wall(s, "W900", (50000.0, 0.0), (52000.0, 0.0))
    bad = audit(s)
    assert bad["by_kind"].get("wall_endpoint", 0) >= 2, bad
    assert bad["by_kind"].get("outside_sheet", 0) >= 1, bad
    assert bad["errors"] >= 3, bad

    # 4. 容差放大后，悬空墙仍然算没接上（远离任何墙，容差 5 也救不了）
    loose = audit(s, tol=50.0)
    assert loose["by_kind"].get("wall_endpoint", 0) >= 2, loose

    print("干净图:", clean["count"], "重复房间:", dup["by_kind"],
          "悬空墙:", bad["by_kind"])
    print("PASS test_audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
