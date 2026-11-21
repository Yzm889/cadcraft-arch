"""基础大放脚样例（v1.0.42）：标准 6-6 节点（240 墙 / 500 基底 / 600 垫层）。

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
    OUT.unlink(missing_ok=True)
    s = Session(OUT)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)
    create_foundation(s, "FD1", (0.0, 0.0))

    export(s, ROOT / "samples" / "demo_foundation.png",
           window=(-9000.0, -15000.0, 9000.0, 1500.0))
    print("OK demo_foundation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
