"""M2 屋面细部样例（v1.0.56）：平屋顶 + 分格线 + 内天沟 + 坡度注字。

输出 samples/demo_roof_detail.dxf + demo_roof_detail.png。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    audit,
    create_roof,
    create_roof_detail,
    create_text,
    export,
    read_roof_detail,
)

OUT = ROOT / "samples"
SCALE = 100.0


def main() -> int:
    path = OUT / "demo_roof_detail.dxf"
    s = Session(path)
    s.new_metric(scale=SCALE)
    create_roof(s, "RF1", (0.0, 0.0), "FLAT", 12000.0, 8000.0,
                600.0, 300.0, parapet=240.0)
    res = create_roof_detail(
        s, "RD1", "RF1",
        grid={"nx": 4, "ny": 3},
        inner_gutter={"sides": ["S", "N"], "width": 400.0},
        slope=2.0, scale=SCALE,
    )
    create_text(s, "T1", (0.0, -2600.0), "屋顶平面：分格 4×3 / 内天沟 i=2%",
                height=3.5, scale=SCALE)
    got = read_roof_detail(Session(path), "RD1")
    a = audit(Session(path), tol=1.0)
    out = OUT / "demo_roof_detail.png"
    export(s, out, window=(-2200.0, -3400.0, 14200.0, 10200.0), scale=SCALE)
    print("屋面细部:", {"grid": got["grid"], "gutter": got["inner_gutter"],
                       "slope": got["slope_text"], "arrows": got["slope_arrows"],
                       "audit": a["count"], "png": out.stat().st_size})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
