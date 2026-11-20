"""图档级比例验收（v0.9.6）：先定出图比例，再按该比例画所有构件。

口径：
  · `set_drawing_scale` 把比例写进 `AA_CFG_SCALE` 标记，重开图档仍在；
  · 定成 1:50 之后新画的轴号 / 房间名 / 图幅，直接按 1:50 取 mm 规格（字高减半、圈径减半）；
  · `create_sheet(size="AUTO")` 按图形外廓挑能放下的最小图幅，放不下自动升一级并回传 promoted。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    create_axis_grid,
    create_room,
    create_sheet,
    create_wall,
    drawing_extent,
    drawing_scale,
    set_drawing_scale,
)

OUT = ROOT / "samples"


def _pairs(path: Path):
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    return [(lines[i], lines[i + 1]) for i in range(0, len(lines) - 1, 2)]


def _block_vals(path: Path, block: str, ent: str, code: str) -> list[float]:
    out: list[float] = []
    inside, kind = False, ""
    for c, v in _pairs(path):
        if c == "0" and v == "BLOCK":
            inside, kind = False, ""
        elif c == "2" and not inside and v == block:
            inside = True
        elif inside and c == "0" and v == "ENDBLK":
            inside = False
        elif inside and c == "0":
            kind = v
        elif inside and c == code and kind == ent:
            out.append(float(v))
    return out


def main() -> int:
    path = OUT / "test_scale_pre.dxf"
    if path.exists():
        path.unlink()

    # 1) 空图默认 1:100；定成 1:50 后标记落盘，重开仍是 50
    s = Session(path)
    s.new_metric()
    assert drawing_scale(s) == 100.0, drawing_scale(s)
    res = set_drawing_scale(s, 50, rescale=False)
    assert res["changed"] == 1 and res["scale"] == 50.0, res
    s2 = Session(path)
    assert drawing_scale(s2) == 50.0, drawing_scale(s2)

    # 2) 定完比例才画轴网：轴号字 3mm×50=150、圈半径 8mm/2×50=200
    create_axis_grid(s, "AX001", 3, 3600, 2, 4500, ext=1000)
    h = _block_vals(path, "AA_AXGRID_AX001", "TEXT", "40")
    r = _block_vals(path, "AA_AXGRID_AX001", "CIRCLE", "40")
    assert h and all(145 <= v <= 155 for v in h), h
    assert r and all(195 <= v <= 205 for v in r), r

    # 3) 墙 + 房间：房间名 2.5mm×50=125
    create_wall(s, "W001", (0, 0), (7200, 0), thick=240)
    create_wall(s, "W002", (0, 0), (0, 4500), thick=240)
    create_wall(s, "W003", (7200, 0), (7200, 4500), thick=240)
    create_wall(s, "W004", (0, 4500), (7200, 4500), thick=240)
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="客厅")
    rh = _block_vals(path, "AA_ROOM_R001", "TEXT", "40")
    assert rh and abs(rh[0] - 125.0) < 1.0, rh

    # 4) 图幅 AUTO：比例沿用图档标记 50，不指定也按 50；尺寸必须真能装下
    ext = drawing_extent(s)
    sheet = create_sheet(s, "S001", size="AUTO", project="示例工程")
    assert sheet["scale"] == 50.0, sheet
    inner_w, inner_h = sheet["inner"]
    assert (ext[2] - ext[0]) <= inner_w and (ext[3] - ext[1]) <= inner_h, (ext, inner_w, inner_h)
    assert sheet["created"] if "created" in sheet else True

    # 5) 显式给小图幅放不下时自动升一级并回传 promoted
    if path.exists():
        path.unlink()
    s3 = Session(path)
    s3.new_metric()
    set_drawing_scale(s3, 50, rescale=False)
    create_wall(s3, "W001", (0, 0), (14000, 0), thick=240)
    small = create_sheet(s3, "S001", size="A4", project="示例工程")
    assert small["size"] != "A4" and small["promoted"], small

    print("1:50 轴号字/圈半径:", h[:2], r[:2], "| 房间字高:", rh[0])
    print("AUTO 图幅:", sheet["size"], "比例 1:%g" % sheet["scale"], "| 升级:", small["promoted"])
    print("PASS test_scale_pre")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
