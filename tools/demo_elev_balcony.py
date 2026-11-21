"""立面阳台/雨篷样例（v1.0.39）：两层立面 + 二层阳台 + 一层门头雨篷。

产出：demo_elev_balcony.png。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    create_elev_balcony,
    create_elevation,
    export,
    set_drawing_scale,
)

OUT = ROOT / "samples" / "demo_elev_balcony.dxf"


def main() -> int:
    s = Session(OUT)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)
    create_elevation(s, "E1", (0.0, 0.0), 6000.0,
                     [{"height": 3600}, {"height": 3600}],
                     openings=[{"floor": 1, "x": 3200.0, "w": 1600.0, "h": 2100.0,
                                "sill": 0.0, "kind": "DOOR"}],
                     roof="FLAT", dims=False, marks=True)
    create_elev_balcony(s, "EB1", (1200.0, 3500.0), 2400.0)
    create_elev_balcony(s, "EB2", (3200.0, 2100.0), 1600.0, kind="AWNING", slab=120.0)

    export(s, ROOT / "samples" / "demo_elev_balcony.png",
           window=(-4500.0, -900.0, 10700.0, 9400.0))
    print("OK demo_elev_balcony")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
