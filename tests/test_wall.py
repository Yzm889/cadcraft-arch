"""墙体功能验收测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import Session, create_wall  # noqa: E402

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def main() -> int:
    path = OUT / "test_wall.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()

    # 1) 水平墙：3600 长、240 厚
    w1 = create_wall(s, "W001", (0.0, 0.0), (3600.0, 0.0), thick=240.0,
                     kind="EXTERNAL", mat="CONCRETE", ax1="A", ax2="B")
    print("wall1:", json.dumps(w1, ensure_ascii=False))
    assert abs(w1["length"] - 3600.0) < 1e-4, w1
    assert abs(w1["angle_deg"]) < 1e-6, w1
    # 墙块内只画两侧墙面线（中心线不画，避免横穿门窗洞口）
    assert len(w1["geom_handles"]) == 2, w1["geom_handles"]

    attrs = s.attributes("AA_WALL_W001")
    assert attrs["AA_THICK"] == "240.0000", attrs
    assert attrs["AA_LEN"] == "3600.0000", attrs
    assert attrs["AA_KIND"] == "EXTERNAL", attrs
    assert attrs["AA_AX1"] == "A" and attrs["AA_AX2"] == "B", attrs

    # 2) 斜墙：3-4-5 直角三角形，长度必须精确为 5000
    w2 = create_wall(s, "W002", (0.0, 0.0), (3000.0, 4000.0), thick=120.0,
                     kind="PARTITION", mat="LIGHT")
    assert abs(w2["length"] - 5000.0) < 1e-4, w2
    assert abs(w2["angle_deg"] - 53.13010235415598) < 1e-4, w2["angle_deg"]
    attrs2 = s.attributes("AA_WALL_W002")
    assert attrs2["AA_LEN"] == "5000.0000", attrs2

    # 3) 两条墙 => 两个块参照、两个独立块定义
    info = s.info()
    assert info["counts"].get("Block Reference") == 2, info["counts"]
    assert "AA_WALL_W001" in info["blocks"] and "AA_WALL_W002" in info["blocks"], info["blocks"]

    # 4) 包围盒：斜墙沿 +X 3..5 方向延伸，取两条墙的并集
    ext = info["extents"]
    print("extents:", ext)
    assert ext[0][0] <= -40 and ext[0][1] <= -100, ext          # 墙线偏移（斜墙投影）
    assert ext[1][0] >= 3600.0, ext                            # 水平墙终点
    assert ext[1][1] >= 4000.0, ext                            # 斜墙终点

    print("PASS test_wall")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
