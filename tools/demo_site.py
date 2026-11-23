"""M2 总平面样例（v1.0.55）：红线 / 建筑轮廓 / 道路 / 出入口 / 指北针 / 坐标尺寸。

输出 samples/demo_site.dxf + demo_site.png。红线是示意，不代表实测权属界线。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import Session, audit, create_site, create_text, export, read_site  # noqa: E402

OUT = ROOT / "samples"
SCALE = 500.0


def main() -> int:
    path = OUT / "demo_site.dxf"
    s = Session(path)
    s.new_metric(scale=SCALE)

    res = create_site(
        s, "SITE01",
        [(0, 0), (60000, 0), (60000, 40000), (0, 40000)],
        buildings=[
            (4000, 4000, 26000, 17000, "幼儿园教学楼"),
            (32000, 4000, 44000, 14000, "室外活动场地"),
            (48000, 26000, 56000, 35000, "设备用房"),
        ],
        roads=[
            (6000, [(0, 25000), (60000, 25000)]),
            (5000, [(30000, 25000), (30000, 40000)]),
        ],
        entrances=[
            {"at": (15000, 0), "label": "主入口", "dir": (0, -1)},
            {"at": (30000, 40000), "label": "次入口", "dir": (0, 1)},
        ],
        north=(53000, 9000),
        scale=SCALE,
    )
    create_text(s, "T01", (3000, 52000), "幼儿园教学楼总平面示意（1:500）",
                height=6.0, scale=SCALE)
    create_text(s, "T02", (3000, -13000),
                "说明：红线/道路为方案示意，坐标与市政条件以实测和专项论证为准。",
                height=3.0, scale=SCALE)

    got = read_site(Session(path), "SITE01")
    a = audit(Session(path), tol=1.0)
    out = OUT / "demo_site.png"
    export(s, out, window=(-9000, -15000, 70000, 56000), scale=SCALE)
    print("总平面:", {"area": got["area"], "buildings": len(got["buildings"]),
                     "roads": len(got["roads"]), "entrances": len(got["entrances"]),
                     "audit": a["count"], "png": out.stat().st_size})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
