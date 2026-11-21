"""基础大放脚样例（v1.0.42，材料填充）：240 墙两级放脚 + 200 墙一级放脚。

产出：demo_foundation.png。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    create_foundation,
    export,
    set_drawing_scale,
)

OUT = ROOT / "samples" / "demo_foundation.dxf"


def main() -> int:
    s = Session(OUT)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)
    create_foundation(s, "FD1", (0.0, 0.0))
    create_foundation(s, "FD2", (7000.0, -300.0), wall=200.0, steps=1,
                      step_h=300.0, step_w=300.0, depth=1200.0, base=200.0, title="基础大放脚（一级）")

    export(s, ROOT / "samples" / "demo_foundation.png",
           window=(-5000.0, -9500.0, 12500.0, 1000.0))
    print("OK demo_foundation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
