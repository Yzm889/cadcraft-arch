"""门窗编号自动避让回归。

同一条墙上放两樘相邻窗，默认编号会互压；audit 必须先报出，
avoid_opening_labels 再通过换侧/引线把碰撞消掉。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import Session, audit, avoid_opening_labels, create_opening, create_wall  # noqa: E402

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_label_avoid.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W002", (6000.0, 0.0), (6000.0, 3000.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W003", (6000.0, 3000.0), (0.0, 3000.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W004", (0.0, 3000.0), (0.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_opening(s, "C001", "W001", "WINDOW", 300.0, 1000.0, height=1500.0)
    create_opening(s, "C002", "W001", "WINDOW", 300.0, 1400.0, height=1500.0)

    before = audit(s)
    assert before["by_kind"].get("opening_text_overlap", 0) >= 1, before
    assert before["errors"] == 0, before

    res = avoid_opening_labels(s)
    assert res["changed"], res
    assert not res["collisions"], res
    after = audit(s)
    assert after["by_kind"].get("opening_text_overlap", 0) == 0, after
    print("PASS test_label_avoid: changed=%s，剩余碰撞 0" % res["changed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
