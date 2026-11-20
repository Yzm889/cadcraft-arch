"""详图样例（v1.0.35）：平面索引符号 + 门窗大样（1:20）。

一层平面画 M0921（南墙门）与 C1515（南墙窗），各放一个索引符号；下方出两张 1:20 大样，
各配一个详图符号（同图写 —）。导出两张 PNG：平面（带索引）与 大样（两张并排）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    create_detail_mark,
    create_index_mark,
    create_opening,
    create_opening_detail,
    create_room,
    create_title_mark,
    create_wall,
    export,
    set_drawing_scale,
)

OUT = ROOT / "samples"
SCALE = 100
PZ = 5000.0          # 平面抬高 5m，和大样分开摆
DZ = -14000.0        # 大样所在标高


def main() -> int:
    path = OUT / "demo_detail.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, SCALE, rescale=False)

    for i, (a, b) in enumerate((
        ((0.0, 0.0), (7200.0, 0.0)),
        ((7200.0, 0.0), (7200.0, 4500.0)),
        ((7200.0, 4500.0), (0.0, 4500.0)),
        ((0.0, 4500.0), (0.0, 0.0)),
    ), 1):
        create_wall(s, "W%03d" % i, (a[0], a[1] + PZ), (b[0], b[1] + PZ),
                    thick=240.0, kind="EXTERNAL")

    create_opening(s, "M001", "W001", "DOOR", width=900.0, pos=1200.0,
                   height=2100.0, no="M0921")
    create_opening(s, "C001", "W001", "WINDOW", width=1500.0, pos=4800.0,
                   height=1500.0, sill=900.0, no="C1515")
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="教室")
    create_title_mark(s, "T01", (3600.0, PZ - 2500.0), "一层平面图", SCALE)

    # 平面上的索引符号：指向 1（窗大样）/ 2（门大样），同一张图写 —
    create_index_mark(s, "IX1", (6000.0, PZ + 900.0), "1", "—")
    create_index_mark(s, "IX2", (2400.0, PZ + 900.0), "2", "—")

    # 两张 1:20 大样：窗在左、门在右
    win = create_opening_detail(s, "OD1", (0.0, DZ), "C001", ratio=20)
    door = create_opening_detail(s, "OD2", (14000.0, DZ), "M001", ratio=20)
    create_detail_mark(s, "DM1", (8900.0, DZ + 9700.0), "1", "—")
    create_detail_mark(s, "DM2", (20200.0, DZ + 11300.0), "2", "—")

    export(s, OUT / "demo_detail_plan.png", window=(-2500.0, PZ - 3200.0, 11100.0, PZ + 6000.0))
    export(s, OUT / "demo_detail_big.png", window=(-3700.0, -18200.0, 20572.0, -1800.0))
    print("详图样例: 窗 %.0f 倍 / 门 %.0f 倍" % (win["factor"], door["factor"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
