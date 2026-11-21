"""注字/引注验收（v1.0.41）：create_text / create_leader + 回读 + 拒绝分支。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError, Session, create_text, create_leader, read_text, read_leader,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_text.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()

    t = create_text(s, "T1", (0.0, 0.0), "外墙 240", height=3.5)
    assert t["text"] == "外墙 240" and abs(t["height"] - 350.0) < 1e-6, t
    assert t["bbox"][0] == 0.0 and t["bbox"][1] == 0.0, t["bbox"]
    assert t["bbox"][2] > t["bbox"][0] and t["bbox"][3] > t["bbox"][1], t["bbox"]
    q = read_text(s, "T1")
    assert q["text"] == "外墙 240" and abs(q["height"] - 350.0) < 1e-6, q

    # 旋转 90°：bbox 变成竖条，宽度应接近字高
    t2 = create_text(s, "T2", (6000.0, 0.0), "详图索引", height=3.0, rotation=90.0)
    bx = t2["bbox"]
    assert abs((bx[2] - bx[0]) - 300.0) < 1e-6, bx
    assert (bx[3] - bx[1]) > 1000.0, bx

    l = create_leader(s, "L1", (3000.0, 2400.0), "C1515", to=(5000.0, 3200.0))
    assert abs(l["shelf"] - 500.0) < 1e-6 and l["to"] == [5000.0, 3200.0], l
    q = read_leader(s, "L1")
    assert q["text"] == "C1515" and q["at"] == [3000.0, 2400.0], q

    cases = [
        (lambda: create_text(s, "T1", (0.0, 0.0), "重号"), "已存在"),
        (lambda: create_text(s, "T3", (0.0, 0.0), "  "), "不能为空"),
        (lambda: create_text(s, "T3", (0.0, 0.0), "x", height=0.0), "字高"),
        (lambda: create_text(s, "T3", (0.0, 0.0), "x", rotation=400), "旋转角"),
        (lambda: create_leader(s, "L1", (0.0, 0.0), "重号"), "已存在"),
        (lambda: create_leader(s, "L2", (0.0, 0.0), "x", to=(0.0, 0.0)), "重合"),
        (lambda: create_leader(s, "L2", (0.0, 0.0), "x", shelf=0.0), "横段"),
    ]
    for fn, msg in cases:
        try:
            fn()
        except CadError as e:
            assert msg in str(e), (msg, str(e))
        else:
            raise AssertionError("应当拒绝：" + msg)

    print("PASS test_text (text=2, leader=1, rejects=%d)" % len(cases))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
