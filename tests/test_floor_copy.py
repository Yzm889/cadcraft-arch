"""楼层复制验收（v1.0.34）。

源层：4 墙 + 1 门 1 窗 + 1 房间；复制到 2 层，平移 (0, 9000)、前缀 "2"。
验收：层号改成 2、门窗宿主墙换成新墙、房间面积与源层一致、编号带前缀、
目标层已有墙拒绝、同层拒绝、源层无墙拒绝、编号冲突拒绝、偏移非法拒绝。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    copy_floor,
    create_opening,
    create_room,
    create_wall,
    opening_data,
    room_data,
    set_drawing_scale,
    wall_data,
)

OUT = ROOT / "samples"


def build_plan(s: Session, floor: int, x0: float, y0: float, prefix: str = "") -> list[str]:
    ids = []
    for i, (a, b) in enumerate((
        ((x0, y0), (x0 + 6000.0, y0)),
        ((x0 + 6000.0, y0), (x0 + 6000.0, y0 + 4000.0)),
        ((x0 + 6000.0, y0 + 4000.0), (x0, y0 + 4000.0)),
        ((x0, y0 + 4000.0), (x0, y0)),
    ), 1):
        wid = "%sW%03d" % (prefix, i)
        create_wall(s, wid, a, b, thick=240.0, kind="EXTERNAL", floor=floor)
        ids.append(wid)
    return ids


def main() -> int:
    path = OUT / "test_floor_copy.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    w1 = build_plan(s, 1, 0.0, 0.0)
    create_opening(s, "M001", "W001", "DOOR", width=900.0, pos=2000.0,
                   height=2100.0, no="M0921")
    create_opening(s, "C001", "W001", "WINDOW", width=1200.0, pos=4500.0,
                   height=1500.0, sill=900.0, no="C1215")
    create_room(s, "R001", w1, name="普通教室")
    src_room = next(r for r in room_data(s) if r["id"] == "R001")

    res = copy_floor(s, 1, 2, offset=(0.0, 9000.0), prefix="2")
    assert res["counts"] == {"walls": 4, "openings": 2, "rooms": 1}, res
    assert sorted(res["walls"]) == ["2W001", "2W002", "2W003", "2W004"], res["walls"]
    assert sorted(res["openings"]) == ["2C001", "2M001"], res["openings"]

    # 层号：「=2 的墙只有新层那 4 堵
    fl2 = [w for w in wall_data(s) if w["floor"] == 2]
    assert len(fl2) == 4, fl2
    assert all(round(w["p1"][1], 3) >= 9000.0 for w in fl2), fl2

    # 门窗：宿主墙换成新墙，层号跟墙走
    ops2 = [o for o in opening_data(s) if o["floor"] == 2]
    assert len(ops2) == 2, ops2
    assert {o["wallid"] for o in ops2} == {"2W001"}, ops2
    assert {o["no"] for o in ops2} == {"M0921", "C1215"}, ops2

    # 房间：面积与源层一致，围合墙换号
    room2 = next(r for r in room_data(s) if r["id"] == "2R001")
    assert abs(room2["area"] - src_room["area"]) < 1.0, (room2, src_room)
    assert sorted(room2["walls"]) == ["2W001", "2W002", "2W003", "2W004"], room2
    assert room2["name"] == "普通教室", room2

    # 再复制一次到 2 层：已有墙，拒绝
    try:
        copy_floor(s, 1, 2, offset=(0.0, 9000.0), prefix="2")
    except CadError as e:
        assert "已有墙" in str(e), e
    else:
        raise AssertionError("目标层已有墙应被拒绝")

    # 同层 / 源层无墙 / 编号冲突 / 偏移非法
    cases = [
        (lambda: copy_floor(s, 2, 2), "相同"),
        (lambda: copy_floor(s, 5, 6), "没有墙"),
        (lambda: copy_floor(s, 1, 3, offset=(0.0, 18000.0), prefix="2"), "冲突"),
        (lambda: copy_floor(s, 1, 3, offset=(0.0,), prefix="3"), "偏移"),
    ]
    for fn, want in cases:
        try:
            fn()
        except CadError as e:
            assert want in str(e), (want, e)
        else:
            raise AssertionError("应拒绝：%s" % want)

    # 第三层正常复制（换前缀）→ 三层同平面
    res3 = copy_floor(s, 1, 3, offset=(0.0, 18000.0), prefix="3")
    assert res3["counts"]["walls"] == 4 and res3["counts"]["rooms"] == 1, res3
    assert len({w["block"] for w in wall_data(s) if w["floor"] == 3}) == 4

    print("楼层复制: 1→2 / 1→3 各 4 墙 2 门窗 1 房间，面积一致（%.0f mm²）"
          % src_room["area"])
    print("PASS test_floor_copy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
