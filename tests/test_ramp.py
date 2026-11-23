"""C2 坡道验收：8/6 LINE + 箭头/注字、坡度边界、拒绝、回读、回滚。

对应规格：docs/spec-M-VERT-电梯坡道阳台.md §4；TC-RP-01..07 + 回滚用例。
图层不新增：边线/端线/中心线/扶手 AA-STEP，箭头 AA-STAIR-ARROW，注字 AA-STAIR-TEXT。
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
    create_ramp,
    layer_of_block,
    layer_table,
)

OUT = ROOT / "samples"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _geom(path: Path, block: str) -> dict[str, int]:
    out = {"LINE": 0, "SOLID": 0, "TEXT": 0}
    for g in block_geometry(path, block):
        out[g["type"]] = out.get(g["type"], 0) + 1
    return out


def main() -> int:
    path = OUT / "test_ramp.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    # TC-RP-01 正常：1:12、宽 1500、长 3600、带扶手、箭头上坡
    rp = create_ramp(s, "RP001", (0.0, 0.0), (3600.0, 0.0),
                     width=1500.0, slope=12, rail=True, arrow="UP")
    assert abs(rp["length"] - 3600.0) < 1e-6, rp
    assert rp["warnings"] == [], rp
    g = _geom(path, "AA_RAMP_RP001")
    assert g["LINE"] == 8, g
    assert g["SOLID"] == 1, g
    assert g["TEXT"] == 1, g
    assert layer_of_block(path, "AA_RAMP_RP001") - {"0"} == {
        LAYERS["step"], LAYERS["stairarrow"], LAYERS["stairtext"]}
    attrs = s.attributes("AA_RAMP_RP001")
    assert attrs["AA_TYPE"] == "RAMP" and attrs["AA_ID"] == "RP001", attrs
    assert attrs["AA_W"] == "1500.0000" and attrs["AA_LEN"] == "3600.0000", attrs
    assert attrs["AA_SLOPE"] == "12.0000", attrs
    assert attrs["AA_RAIL"] == "1" and attrs["AA_ARROW"] == "UP", attrs
    assert attrs["AA_LABEL"] == "i=1:12", attrs
    assert attrs["AA_ANGLE"] == "0.0000", attrs

    # 不新增图层：层表里不应出现 AA-RAMP 之类
    names = set(layer_table(path))
    assert LAYERS["step"] in names and LAYERS["stairarrow"] in names, names
    assert not any("RAMP" in n for n in names), names

    # TC-RP-02 坡度边界：8 warning、20 通过、13 不 warning
    r8 = create_ramp(s, "RP002", (0.0, 5000.0), (3600.0, 5000.0), slope=8)
    assert r8["warnings"] and "1:12" in r8["warnings"][0], r8
    r20 = create_ramp(s, "RP003", (0.0, 8000.0), (3600.0, 8000.0), slope=20)
    assert r20["warnings"] == [], r20
    r13 = create_ramp(s, "RP004", (0.0, 11000.0), (3600.0, 11000.0), slope=13)
    assert r13["warnings"] == [], r13

    # TC-RP-03 坡度非法：7 / 21 拒绝，字节不变
    before = _sha(path)
    for sid, slope in (("RP901", 7), ("RP902", 21)):
        try:
            create_ramp(s, sid, (0.0, 15000.0), (3600.0, 15000.0), slope=slope)
        except CadError:
            pass
        else:
            raise AssertionError("坡度 %s 应被拒绝" % slope)
    assert _sha(path) == before, "坡度拒绝后字节应不变"

    # TC-RP-04 宽度/长度非法
    before = _sha(path)
    for sid, kwargs in (
        ("RP911", dict(width=800.0)),
        ("RP912", dict(width=1500.0)),
    ):
        p2 = (3600.0, 18000.0) if sid == "RP911" else (800.0, 18000.0)
        try:
            create_ramp(s, sid, (0.0, 18000.0), p2, **kwargs)
        except CadError:
            pass
        else:
            raise AssertionError("宽/长非法应被拒绝：%s" % sid)
    assert _sha(path) == before

    # TC-RP-05 无扶手：6 LINE + 1 SOLID + 1 TEXT
    create_ramp(s, "RP005", (0.0, 21000.0), (3600.0, 21000.0),
                rail=False, arrow="DOWN")
    g5 = _geom(path, "AA_RAMP_RP005")
    assert g5["LINE"] == 6 and g5["SOLID"] == 1 and g5["TEXT"] == 1, g5
    a5 = s.attributes("AA_RAMP_RP005")
    assert a5["AA_RAIL"] == "0" and a5["AA_ARROW"] == "DOWN", a5

    # TC-RP-06 重号：拒绝且字节不变
    before = _sha(path)
    try:
        create_ramp(s, "RP001", (0.0, 24000.0), (3600.0, 24000.0))
    except CadError as exc:
        assert "已存在" in str(exc), exc
    else:
        raise AssertionError("重号应被拒绝")
    assert _sha(path) == before

    # TC-RP-07 回读：--show 走 attributes；这里直接读
    assert s.attributes("AA_RAMP_RP001")["AA_ID"] == "RP001"

    # 额外：实现后 LISP 失败时整图字节回滚，块/箭头/文字都不留
    before = _sha(path)
    orig_lisp = s.lisp

    def _boom(*_a, **_k):
        raise CadError("模拟坡道失败")

    s.lisp = _boom
    try:
        try:
            create_ramp(s, "RP095", (0.0, 27000.0), (3600.0, 27000.0))
        except CadError as exc:
            assert "模拟坡道失败" in str(exc), exc
        else:
            raise AssertionError("模拟失败应被拒绝")
    finally:
        s.lisp = orig_lisp
    assert _sha(path) == before, "失败后整图字节应回滚"
    assert s.reference("AA_RAMP_RP095") is None

    print("PASS test_ramp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
