"""M-VERT-1 电梯验收：井道校验、10 线（轿厢+对重）、四向门、单次插入、失败零残留。

对应规格：docs/spec-M-VERT-电梯坡道阳台.md §13（C1 定稿）。
T30 实测边界：仅南向门有 T30 证据；北/东/西为自研旋转行为，不声称与天正确认。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_lib  # noqa: E402
from aa_lib import (  # noqa: E402
    LAYERS,
    CadError,
    Session,
    block_geometry,
    create_elevator,
    create_wall,
    layer_of_block,
    layer_table,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_shaft(s: Session, prefix: str, at: tuple[float, float],
                shaft: tuple[float, float] = (2200.0, 2200.0),
                thick: float = 240.0) -> dict[str, str]:
    """按净空中心 at 造 4 堵井道墙（内表面 = 净空边界）。"""
    cx, cy = at
    hw, hd = shaft[0] / 2.0, shaft[1] / 2.0
    half = thick / 2.0
    x0, x1 = cx - hw - half, cx + hw + half
    y0, y1 = cy - hd - half, cy + hd + half
    ids = {"N": prefix + "N", "E": prefix + "E", "S": prefix + "S", "W": prefix + "W"}
    create_wall(s, ids["S"], (x0, y0), (x1, y0), thick=thick, kind="EXTERNAL", bind_axis=False)
    create_wall(s, ids["N"], (x0, y1), (x1, y1), thick=thick, kind="EXTERNAL", bind_axis=False)
    create_wall(s, ids["W"], (x0, y0), (x0, y1), thick=thick, kind="EXTERNAL", bind_axis=False)
    create_wall(s, ids["E"], (x1, y0), (x1, y1), thick=thick, kind="EXTERNAL", bind_axis=False)
    return ids


def _lines(path: Path, block: str) -> list[dict]:
    return [g for g in block_geometry(path, block) if g["type"] == "LINE"]


def main() -> int:
    path = OUT / "test_elevator.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    # 1. 南向门正常插入（T30 有实测证据的方向）
    walls = _make_shaft(s, "SH1", (0.0, 0.0))
    el = create_elevator(
        s, "EL001", (0.0, 0.0), shaft=(2200.0, 2200.0), car=(1600.0, 1400.0),
        door=1100.0, door_h=2100.0, door_side="S", cw_side="N",
        shaft_walls=walls, gap=100.0, cw_gap=50.0,
    )
    assert abs(el["car_offset"] - 116.0) < 1e-9, el
    assert abs(el["door_gap"] - 284.0) < 1e-9, el
    assert el["cw"] == [1280.0, 182.0], el

    lines = _lines(path, "AA_ELEVATOR_EL001")
    texts = [g for g in block_geometry(path, "AA_ELEVATOR_EL001") if g["type"] == "TEXT"]
    assert len(lines) == 10, (len(lines), [g["type"] for g in block_geometry(path, "AA_ELEVATOR_EL001")])
    assert len(texts) == 0, texts
    assert layer_of_block(path, "AA_ELEVATOR_EL001") - {"0"} == {LAYERS["elevator"]}

    attrs = s.attributes("AA_ELEVATOR_EL001")
    assert attrs["AA_TYPE"] == "ELEVATOR" and attrs["AA_ID"] == "EL001", attrs
    assert attrs["AA_W"] == "2200.0000" and attrs["AA_D"] == "2200.0000", attrs
    assert attrs["AA_CAR_W"] == "1600.0000" and attrs["AA_CAR_D"] == "1400.0000", attrs
    assert attrs["AA_DOOR"] == "1100.0000" and attrs["AA_HEIGHT"] == "2100.0000", attrs
    assert attrs["AA_DOOR_SIDE"] == "S" and attrs["AA_CW_SIDE"] == "N", attrs
    assert attrs["AA_CW_W"] == "1280.0000" and attrs["AA_CW_D"] == "182.0000", attrs
    assert attrs["AA_ANGLE"] == "180.0000", attrs

    assert "AA_ELEVATOR_EL001" in s.info()["blocks"], s.info()["blocks"]
    assert s.reference("AA_OPENING_EL001-D") is not None, "电梯门洞块不存在"
    op = s.attributes("AA_OPENING_EL001-D")
    assert op["AA_WIDTH"] == "1100.0000" and op["AA_HEIGHT"] == "2100.0000", op
    assert op["AA_NO"] == "EL001-D" and op["AA_WALLID"] == walls["S"], op

    # 2. 图层：AA-ELEVATOR 黄 2 / 实线 / 0.18
    table = layer_table(path)
    got = table[LAYERS["elevator"]]
    assert got["color"] == 2, got
    assert str(got["linetype"]).lower() == "continuous", got
    assert abs(float(got["lineweight"]) - 0.18) < 0.011, got

    # 3. 四向门（南向有 T30 证据；其余为自研旋转行为）
    expected_angle = {"N": "0.0000", "E": "-90.0000", "S": "180.0000", "W": "90.0000"}
    opposite = {"N": "S", "S": "N", "E": "W", "W": "E"}
    for i, side in enumerate(("N", "E", "S", "W"), start=2):
        at = (6000.0 * (i - 1), 0.0)
        ws = _make_shaft(s, "SH%d" % i, at)
        ident = "EL%03d" % i
        create_elevator(
            s, ident, at, shaft=(2200.0, 2200.0), car=(1600.0, 1400.0),
            door=1100.0, door_h=2100.0, door_side=side, cw_side=opposite[side],
            shaft_walls=ws, gap=100.0, cw_gap=50.0,
        )
        a = s.attributes("AA_ELEVATOR_" + ident)
        assert a["AA_DOOR_SIDE"] == side and a["AA_CW_SIDE"] == opposite[side], a
        assert a["AA_ANGLE"] == expected_angle[side], a
        assert a["AA_DOOR_WALL"] == ws[side], a

    # 4. 相邻对重侧拒绝（TC-EL-13），字节不变
    ws = _make_shaft(s, "SH9", (30000.0, 0.0))
    before = _sha(path)
    try:
        create_elevator(
            s, "EL099", (30000.0, 0.0), door_side="S", cw_side="E",
            shaft_walls=ws,
        )
        raise AssertionError("相邻对重侧应被拒绝")
    except CadError as exc:
        assert "C1 仅支持对重与门相对" in str(exc), exc
    assert _sha(path) == before, "拒绝后图纸字节应不变"

    # 5. 缺井道墙 / 内表面尺寸不符：拒绝且字节不变
    before = _sha(path)
    try:
        create_elevator(s, "EL098", (0.0, 0.0), shaft_walls={"N": walls["N"]})
        raise AssertionError("缺墙应被拒绝")
    except CadError:
        pass
    assert _sha(path) == before
    try:
        create_elevator(s, "EL097", (0.0, 0.0), shaft=(2000.0, 2000.0),
                        shaft_walls=walls)
        raise AssertionError("井道净尺寸不符应被拒绝")
    except CadError:
        pass
    assert _sha(path) == before

    # 6. 同编号重复：拒绝且字节不变（单次插入）
    before = _sha(path)
    try:
        create_elevator(s, "EL001", (0.0, 0.0), shaft_walls=walls)
        raise AssertionError("同编号应被拒绝")
    except CadError:
        pass
    assert _sha(path) == before
    assert len([b for b in s.info()["blocks"] if b == "AA_ELEVATOR_EL001"]) == 1

    # 7. 门洞冲突：拒绝且零残留
    ws2 = _make_shaft(s, "SH10", (36000.0, 0.0))
    from aa_lib import create_opening
    create_opening(s, "D900", ws2["S"], "DOOR", width=900.0, pos=1220.0)
    before = _sha(path)
    try:
        create_elevator(s, "EL096", (36000.0, 0.0), shaft_walls=ws2)
        raise AssertionError("门洞冲突应被拒绝")
    except CadError:
        pass
    assert _sha(path) == before
    assert s.reference("AA_ELEVATOR_EL096") is None

    # 8. 块已建、门洞失败：整图字节回滚，电梯块/门洞块都不留
    ws3 = _make_shaft(s, "SH11", (42000.0, 0.0))
    before = _sha(path)
    orig_open = aa_lib.create_opening

    def _boom(*_a, **_k):
        raise CadError("模拟门洞失败")

    aa_lib.create_opening = _boom
    try:
        try:
            create_elevator(s, "EL095", (42000.0, 0.0), shaft_walls=ws3)
            raise AssertionError("模拟门洞失败时应整体回滚")
        except CadError as exc:
            assert "模拟门洞失败" in str(exc), exc
    finally:
        aa_lib.create_opening = orig_open
    assert _sha(path) == before, "门洞失败后整图字节应回滚"
    assert s.reference("AA_ELEVATOR_EL095") is None
    assert s.reference("AA_OPENING_EL095-D") is None

    print("PASS test_elevator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
