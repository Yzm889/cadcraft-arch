"""房间功能验收测试：闭合墙环 + 内偏移面积。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import CadError, Session, create_room, create_wall  # noqa: E402

OUT = ROOT / "samples"


def expect_error(fn, keyword: str) -> None:
    try:
        fn()
    except CadError as e:
        assert keyword in str(e), (keyword, str(e))
        print("  拒绝写入 ok:", str(e))
        return
    raise AssertionError("应当拒绝但没有拒绝：%s" % keyword)


def main() -> int:
    path = OUT / "test_room.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()

    # 3600 x 4800 的矩形房间，墙厚统一 240
    create_wall(s, "W001", (0.0, 0.0), (3600.0, 0.0), thick=240.0)
    create_wall(s, "W002", (3600.0, 0.0), (3600.0, 4800.0), thick=240.0)
    create_wall(s, "W003", (3600.0, 4800.0), (0.0, 4800.0), thick=240.0)
    create_wall(s, "W004", (0.0, 4800.0), (0.0, 0.0), thick=240.0)

    r1 = create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="客厅")
    print("room:", r1["area"], r1["perimeter"])

    # 净面积必须是 (3600-240) x (4800-240) = 3360 x 4560
    expected = 3360.0 * 4560.0
    assert abs(r1["area"] - expected) < 1.0, (r1["area"], expected)  # 浮点容差 1 mm²

    attrs = s.attributes("AA_ROOM_R001")
    assert abs(float(attrs["AA_AREA"]) - expected) < 1.0, attrs
    assert attrs["AA_WALLS"] == "W001;W002;W003;W004", attrs
    assert attrs["AA_NAME"] == "客厅", attrs
    # 房间不再画轮廓线（避免与墙面重合/穿门洞），只剩名称文字
    assert len(r1["geom_handles"]) == 1, r1["geom_handles"]

    # 2) 墙环断裂必须拒绝（把 W003 换成不存在的方向）
    expect_error(
        lambda: create_room(s, "R002", ["W001", "W002", "W004"], name="坏环"),
        "断裂",
    )

    # 3) 不闭合必须拒绝：W001 -> W003 直接跳
    expect_error(
        lambda: create_room(s, "R003", ["W001", "W002"], name="开口"),
        "未闭合",
    )

    # 4) 引用了不存在的墙
    expect_error(
        lambda: create_room(s, "R004", ["W001", "W999", "W003", "W004"]),
        "找不到墙",
    )

    # 5) 失败调用不留痕：1 个房间参照
    refs = [e for e in s.references()
            if e["geometry"]["block"].startswith("AA_ROOM_")]
    assert len(refs) == 1, refs
    print("PASS test_room")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

