"""屋顶平面样例（v1.0.29）：平屋顶 + 女儿墙压顶 + 上人孔。

6000×4000 平屋面，外挑 600、檐沟 300、女儿墙 240，屋面上一个 700×700 上人孔，
轴网 1/2/3（3000 间距）× A/B（4000 间距）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    annot_size,
    create_axis_grid,
    create_roof,
    create_title_mark,
    export,
    set_drawing_scale,
)

OUT = ROOT / "samples"
SCALE = 100


def main() -> int:
    OUT.mkdir(exist_ok=True)
    path = OUT / "demo_roof_parapet.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, SCALE, rescale=False)

    create_axis_grid(s, "AX001", 3, 3000.0, 2, 4000.0, ext=annot_size(14.0, SCALE))
    r = create_roof(s, "RF1", (0.0, 0.0), "FLAT", 6000.0, 4000.0,
                    overhang=600.0, gutter=300.0, parapet=240.0,
                    hatch={"x": 3000.0, "y": 2000.0, "size": 700.0})
    assert r["parapet"] == 240.0 and r["hatch"] == (3000.0, 2000.0, 700.0), r
    create_title_mark(s, "T01", (3000.0, -1400.0), "屋顶平面图", SCALE)

    export(s, OUT / "demo_roof_parapet.png")
    export(s, OUT / "demo_roof_parapet_zoom.png",
           window=(-700, -700, 7100, 4570))
    print("屋顶样例: 平屋顶 6000×4000 女儿墙 240 + 上人孔 700 @(3000,2000)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
