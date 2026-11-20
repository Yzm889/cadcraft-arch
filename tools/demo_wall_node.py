"""墙身节点样例（v1.0.36）：窗台节点 + 女儿墙节点（1:20）。

两张节点并排，各配详图符号（3、4），导出 samples/demo_wall_node.png。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    create_detail_mark,
    create_wall_node,
    export,
    set_drawing_scale,
)

OUT = ROOT / "samples"
SCALE = 100


def main() -> int:
    path = OUT / "demo_wall_node.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, SCALE, rescale=False)

    sill = create_wall_node(s, "WN1", (0.0, 0.0), "SILL", ratio=20)
    para = create_wall_node(s, "WN2", (12000.0, 0.0), "PARAPET", ratio=20)

    create_detail_mark(s, "DM3", (-1600.0, 9600.0), "3", "—")
    create_detail_mark(s, "DM4", (20800.0, 8400.0), "4", "—")

    export(s, OUT / "demo_wall_node.png", window=(-3200.0, -6300.0, 21100.0, 10200.0))
    print("墙身节点样例: 窗台 %.0f 倍 / 女儿墙 %.0f 倍"
          % (sill["factor"], para["factor"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
