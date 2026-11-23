"""C3 阳台验收：6 LINE（可选 +1 TEXT）、压洞口/越界拒绝、内墙 warning、回滚。

对应规格：docs/spec-M-VERT-电梯坡道阳台.md §5；TC-BA-01..07 + 失败回滚用例。
图层不新增：外沿/边线/栏板线 AA-STEP，注字 AA-STAIR-TEXT。
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
    create_balcony,
    create_opening,
    create_wall,
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
    path = OUT / "test_balcony.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    # TC-BA-01 正常：外墙 W1、区间 0–3000、挑 1200、栏板 100、默认无注字
    w1 = create_wall(s, "W1", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    wall_lines_before = _geom(path, "AA_WALL_W1")
    ba = create_balcony(s, "BA001", "W1", pos=1500.0,
                        width=3000.0, depth=1200.0, rail=100.0)
    assert ba["warnings"] == [], ba
    g = _geom(path, "AA_BALCONY_BA001")
    assert g["LINE"] == 6, g
    assert g["TEXT"] == 0, g
    assert layer_of_block(path, "AA_BALCONY_BA001") - {"0"} == {LAYERS["step"]}
    attrs = s.attributes("AA_BALCONY_BA001")
    assert attrs["AA_TYPE"] == "BALCONY" and attrs["AA_ID"] == "BA001", attrs
    assert attrs["AA_WALLID"] == "W1", attrs
    assert attrs["AA_POS"] == "1500.0000", attrs
    assert attrs["AA_W"] == "3000.0000" and attrs["AA_D"] == "1200.0000", attrs
    assert attrs["AA_RAIL"] == "100.0000", attrs
    assert attrs["AA_LABEL"] == "" and attrs["AA_ANGLE"] == "0.0000", attrs
    # 外沿 y=1200、栏板内线 y=1100；不修改墙块
    ys = sorted({round(p[1], 3) for gline in block_geometry(path, "AA_BALCONY_BA001")
                 if gline["type"] == "LINE" for p in gline["pts"]})
    assert 1200.0 in ys and 1100.0 in ys, ys
    assert _geom(path, "AA_WALL_W1") == wall_lines_before, "阳台不应修改墙块"

    # 无新图层
    names = set(layer_table(path))
    assert not any("BALCONY" in n for n in names), names

    # TC-BA-02 压洞口：同墙已有 D002，阳台区间重叠 → 拒绝，字节不变
    create_wall(s, "W2", (0.0, 6000.0), (6000.0, 6000.0), thick=240.0, kind="EXTERNAL")
    create_opening(s, "D002", "W2", "DOOR", width=900.0, pos=1500.0)
    before = _sha(path)
    try:
        create_balcony(s, "BA901", "W2", pos=1500.0, width=3000.0)
    except CadError as exc:
        assert "洞口" in str(exc) or "重叠" in str(exc), exc
    else:
        raise AssertionError("压洞口应被拒绝")
    assert _sha(path) == before
    assert s.reference("AA_OPENING_D002") is not None

    # TC-BA-03 越界：W3 长 3000，阳台 3000 宽放 pos=2500 → 拒绝
    create_wall(s, "W3", (0.0, 12000.0), (3000.0, 12000.0), thick=240.0, kind="EXTERNAL")
    before = _sha(path)
    try:
        create_balcony(s, "BA902", "W3", pos=2500.0, width=3000.0)
    except CadError as exc:
        assert "越界" in str(exc) or "墙" in str(exc), exc
    else:
        raise AssertionError("越界应被拒绝")
    assert _sha(path) == before

    # TC-BA-04 内墙：只 warning，不拒绝
    create_wall(s, "W4", (0.0, 18000.0), (6000.0, 18000.0), thick=240.0, kind="INTERNAL")
    ba4 = create_balcony(s, "BA004", "W4", pos=1500.0, width=3000.0)
    assert ba4["warnings"] and "外墙" in ba4["warnings"][0], ba4

    # TC-BA-05 深度/栏板越界
    create_wall(s, "W5", (0.0, 24000.0), (6000.0, 24000.0), thick=240.0, kind="EXTERNAL")
    before = _sha(path)
    for sid, kwargs in (
        ("BA911", dict(depth=500.0)),
        ("BA912", dict(depth=2500.0)),
        ("BA913", dict(rail=40.0)),
        ("BA914", dict(rail=400.0)),
    ):
        try:
            create_balcony(s, sid, "W5", pos=1500.0, **kwargs)
        except CadError:
            pass
        else:
            raise AssertionError("深度/栏板越界应被拒绝：%s" % sid)
    assert _sha(path) == before

    # TC-BA-06 重号
    before = _sha(path)
    try:
        create_balcony(s, "BA001", "W1", pos=4500.0, width=1200.0)
    except CadError as exc:
        assert "已存在" in str(exc), exc
    else:
        raise AssertionError("重号应被拒绝")
    assert _sha(path) == before

    # TC-BA-07 回读 + 可选注字
    create_wall(s, "W6", (0.0, 30000.0), (6000.0, 30000.0), thick=240.0, kind="EXTERNAL")
    ba7 = create_balcony(s, "BA007", "W6", pos=1500.0, label="阳台")
    assert _geom(path, "AA_BALCONY_BA007")["TEXT"] == 1
    a7 = s.attributes("AA_BALCONY_BA007")
    assert a7["AA_LABEL"] == "阳台", a7
    assert ba7["label"] == "阳台"

    # 额外：LISP 失败 → 整图字节回滚，块/线/文字都不留
    create_wall(s, "W7", (0.0, 36000.0), (6000.0, 36000.0), thick=240.0, kind="EXTERNAL")
    before = _sha(path)
    orig_lisp = s.lisp

    def _boom(*_a, **_k):
        raise CadError("模拟阳台失败")

    s.lisp = _boom
    try:
        try:
            create_balcony(s, "BA095", "W7", pos=1500.0)
        except CadError as exc:
            assert "模拟阳台失败" in str(exc), exc
        else:
            raise AssertionError("模拟失败应被拒绝")
    finally:
        s.lisp = orig_lisp
    assert _sha(path) == before, "失败后整图字节应回滚"
    assert s.reference("AA_BALCONY_BA095") is None

    print("PASS test_balcony")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
