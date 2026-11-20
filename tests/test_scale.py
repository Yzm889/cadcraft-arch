"""标注比例联动验收（v0.9.4）。

口径：图上所有"按 mm 出图"的注记，字高/圈径必须 = mm × 比例分母。
1:100 时轴号字 300、圈半径 400；改成 1:50 后字 150、圈半径 200（纸上同样 3mm/8mm）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    auto_axis,
    block_geometry,
    create_opening,
    create_north_arrow,
    create_room,
    create_sheet,
    create_title_mark,
    create_wall,
    rescale_annotations,
    rooms_report,
)

OUT = ROOT / "samples"


def _pairs(path: Path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lines = [ln.strip() for ln in lines]
    return [(lines[i], lines[i + 1]) for i in range(0, len(lines) - 1, 2)]


def _block_vals(path: Path, block: str, ent: str, code: str) -> list[float]:
    """在 DXF 的 BLOCKS 段里取指定块内某类实体的某个组码（40 = 字高/半径）。"""
    out: list[float] = []
    inside = False
    kind = ""
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


def text_heights(path: Path, block: str) -> list[float]:
    return _block_vals(path, block, "TEXT", "40")


def circle_radii(path: Path, block: str) -> list[float]:
    return _block_vals(path, block, "CIRCLE", "40")


def main() -> int:
    path = OUT / "test_scale.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()

    # 一张 6000×4000 的小图：墙 + 门 + 房间 + 轴网 + 尺寸 + 图名 + 指北针，全部按 1:100
    create_wall(s, "W001", (0, 0), (6000, 0), thick=240, kind="EXTERNAL")
    create_wall(s, "W002", (6000, 0), (6000, 4000), thick=240, kind="EXTERNAL")
    create_wall(s, "W003", (6000, 4000), (0, 4000), thick=240, kind="EXTERNAL")
    create_wall(s, "W004", (0, 4000), (0, 0), thick=240, kind="EXTERNAL")
    create_opening(s, "D001", "W001", "DOOR", width=900, pos=1500)
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="客厅")
    auto_axis(s, "AX001", 50, 2400)
    create_title_mark(s, "T001", (0, -2500), "一层平面图", 100)
    create_north_arrow(s, "N001", (9000, 3600))
    rooms_report(s, table_at=(0.0, -4200.0))       # 表格也按 mm 出图（2.5mm 字）

    h100 = text_heights(path, "AA_AXGRID_AX001")
    r100 = circle_radii(path, "AA_AXGRID_AX001")
    assert min(h100) >= 290 and max(h100) <= 310, h100          # 3mm@100
    assert min(r100) >= 399 and max(r100) <= 401, r100          # 4mm@100
    room100 = text_heights(path, "AA_ROOM_R001")
    assert abs(room100[0] - 250.0) < 1.0, room100               # 2.5mm@100
    open100 = text_heights(path, "AA_OPENING_D001")
    assert min(open100) >= 170 and max(open100) <= 190, open100  # 1.8mm@100
    title100 = text_heights(path, "AA_SYM_T001")
    assert max(title100) >= 490 and max(title100) <= 510, title100   # 5mm@100

    # 换 1:50：同样一张纸上还是 3mm/8mm/2.5mm/1.8mm/5mm，所以图元数字减半
    res = rescale_annotations(s, 50)
    assert res["grids"] and res["rooms"] == 1 and res["openings"] == 1, res
    h50 = text_heights(path, "AA_AXGRID_AX001")
    r50 = circle_radii(path, "AA_AXGRID_AX001")
    assert 140 <= min(h50) and max(h50) <= 160, h50
    assert 199 <= min(r50) and max(r50) <= 201, r50
    assert abs(text_heights(path, "AA_ROOM_R001")[0] - 125.0) < 1.0
    assert 85 <= min(text_heights(path, "AA_OPENING_D001")) <= 95
    assert 245 <= max(text_heights(path, "AA_SYM_T001")) <= 255
    tab50 = text_heights(path, "AA_TABLE_T001")
    assert 120 <= min(tab50) <= 130, tab50            # 表格字高 2.5mm -> 125

    # 图幅按 1:50 套上后，drawing_scale 自动从 AA_SHEET 读 50：新建注记继续按 50 取规格
    create_sheet(s, "S001", size="A3", scale=50)
    create_title_mark(s, "T002", (0, -3500), "一层平面图", None)
    assert 245 <= max(text_heights(path, "AA_SYM_T002")) <= 255, \
        text_heights(path, "AA_SYM_T002")

    print("1:100 轴号字/圈半径:", h100[:2], r100[:2])
    print("1:50  轴号字/圈半径:", h50[:2], r50[:2])
    print("PASS test_scale")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
