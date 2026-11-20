"""门窗编号侧向（室内 / 室外）验收测试。

验收链：四墙成环 -> 建房间 -> 开窗（默认 in）-> 读块内 TEXT 的局部 y 判断落在哪侧
         -> 改成 out 重画 -> 再判断一次；顺带断言 AA_LABELSIDE 落盘。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session, block_geometry, create_opening, create_room, create_wall,
    opening_data, set_opening,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def label_y(path: Path, block: str) -> float | None:
    for g in block_geometry(path, block):
        if g["type"] == "TEXT":
            return round(g["pts"][0][1], 2)
    return None


def main() -> int:
    path = OUT / "test_label.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()
    for wid, p1, p2 in [
        ("W001", (0.0, 0.0), (6000.0, 0.0)),
        ("W002", (6000.0, 0.0), (6000.0, 4800.0)),
        ("W003", (6000.0, 4800.0), (0.0, 4800.0)),
        ("W004", (0.0, 4800.0), (0.0, 0.0)),
    ]:
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL")
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="A")

    # W001 沿 +X 画，房间在 +Y 侧：默认 in 应落 +370（室内），out 应落 -370（室外）
    create_opening(s, "C001", "W001", "WINDOW", 1500.0, 3000.0, 1500.0, label_side="in")
    y_in = label_y(path, "AA_OPENING_C001")
    assert y_in == 370.0, y_in
    assert opening_data(s)[0]["labelside"] == "in"

    set_opening(s, "C001", label_side="out")
    y_out = y_in and label_y(path, "AA_OPENING_C001")
    assert y_out == -370.0, y_out
    assert opening_data(s)[0]["labelside"] == "out"

    # 再改回来，确认可反复切换且落盘属性同步
    set_opening(s, "C001", label_side="in")
    assert label_y(path, "AA_OPENING_C001") == 370.0
    assert opening_data(s)[0]["labelside"] == "in"

    # leader：引线端到 820（240/2 + 700），文字基线 900，并多一条 45° 引线（窗原本 6 条线 -> 7 条）
    set_opening(s, "C001", label_side="leader")
    y_leader = label_y(path, "AA_OPENING_C001")
    assert y_leader == 900.0, y_leader   # 引线端点 820，文字基线再抬 80
    assert opening_data(s)[0]["labelside"] == "leader"
    kinds = [g["type"] for g in block_geometry(path, "AA_OPENING_C001")]
    assert kinds.count("LINE") == 7, kinds

    # 切回 in，引线要消失、线数回到 6
    set_opening(s, "C001", label_side="in")
    kinds = [g["type"] for g in block_geometry(path, "AA_OPENING_C001")]
    assert kinds.count("LINE") == 6, kinds

    # 非法值拒绝，且文件不被动过（重画会先备份再回滚）
    before = path.stat().st_size
    try:
        set_opening(s, "C001", label_side="middle")
    except SystemExit:
        raise
    except Exception as e:
        assert "label_side" in str(e), e
    assert path.stat().st_size == before

    print("PASS test_label (in=%.0f, out=%.0f)" % (y_in, y_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
