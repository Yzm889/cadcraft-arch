"""卫生间大样样例（v1.0.38）：2400×1800 净空 + 坐便/台盆/地漏 + 1% 排水坡。

产出：demo_wc_detail.png（大样 + 详图符号）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    create_detail_mark,
    create_wc_detail,
    export,
    set_drawing_scale,
)

OUT = ROOT / "samples" / "demo_wc_detail.dxf"


def main() -> int:
    s = Session(OUT)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    create_detail_mark(s, "DM1", (-4600.0, 600.0), "3", "—")
    create_wc_detail(s, "WC1", (0.0, 0.0))

    export(s, ROOT / "samples" / "demo_wc_detail.png",
           window=(-7000.0, -5200.0, 15200.0, 11200.0))
    print("OK demo_wc_detail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
