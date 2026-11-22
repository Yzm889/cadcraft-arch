# -*- coding: utf-8 -*-
"""把 02 二层平面图当作标准层模板，复制出 03/04/05 层。

只在复制件上改：两间功能房名称、楼层主题、标高、图签。
墙体/门窗/房间/楼梯/轴网/尺寸/图框不重画，因此不会再走一遍几百个构件的生成。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from aa_lib import (  # noqa: E402
    Session, audit, create_stair, create_text, delete_component, drawing_scale, export,
    reconcile, room_data, set_room, set_sheet,
)

from build_kindergarten import append_png_check, validate_floor  # noqa: E402

SCALE = 100.0
SOURCE = OUT / "02_二层平面图.dxf"

# 楼层 -> 输出文件、图签图名、图号、标高、主题、两间功能房新名称
SPEC = {
    3: ("03_三层平面图", "3层平面图", "建施-03", "8.100",
        "图书阅览 / 建构游戏", ("图书阅览室", "建构游戏室")),
    4: ("04_四层平面图", "4层平面图", "建施-04", "12.000",
        "音体 / 美工陶艺", ("音体活动室", "美工陶艺室")),
    5: ("05_五层平面图", "5层平面图", "建施-05", "15.900",
        "教师培训 / 档案资料", ("教师培训室", "档案资料室")),
}


def set_floor_attr(dxf: Path, floor: int) -> None:
    """把复制件里的 AA_FLOOR 属性统一改成目标层号（最后做，避免 CLI 再写回 2）。"""
    lines = dxf.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
    changed = 0
    for i in range(0, len(lines) - 1, 2):
        if lines[i].strip() == "2" and lines[i + 1].strip() == "AA_FLOOR":
            for j in range(i - 2, -1, -2):
                if lines[j].strip() == "1":
                    lines[j + 1] = "  %d" % floor
                    changed += 1
                    break
    if changed == 0:
        raise RuntimeError("%s 里没有找到 AA_FLOOR 属性" % dxf.name)
    dxf.write_text("\n".join(lines) + "\n", encoding="utf-8")


def clone_floor(no: int) -> dict:
    stem, drawing, number, elev, theme, new_names = SPEC[no]
    dxf = OUT / (stem + ".dxf")
    shutil.copy2(SOURCE, dxf)
    s = Session(dxf)

    # 1) 两间功能房改名：只重建这两个房间块，不改墙和门窗
    rooms = room_data(s)
    old_names = [r["name"] for r in rooms if r["name"] in
                 ("美工活动室", "科学建构室")]
    if len(old_names) != 2:
        raise RuntimeError("标准层模板的功能房不是 2 间：%r" % old_names)
    for old, new in zip(old_names, new_names):
        target = next(r for r in rooms if r["name"] == old)
        set_room(s, target["id"], new)

    # 2) 标高 / 主题：删旧注字，按原锚点重建
    for e in s.components("AA_TXT_"):
        a = {x["tag"]: x.get("text", {}).get("value", "")
             for x in e["geometry"].get("attribs", [])}
        text = a.get("AA_TEXT", "")
        if text.startswith("标高 ") or text.startswith("主题："):
            delete_component(s, e["geometry"]["block"])
            at = (float(a["AA_ATX"]), float(a["AA_ATY"]))
            if text.startswith("标高 "):
                create_text(s, "X%dELEV" % no, at, "标高 " + elev,
                            height=2.5, scale=SCALE)
            else:
                create_text(s, "X%dTHEME" % no, at, "主题：" + theme,
                            height=2.2, scale=SCALE)

    # 3) 图签改名、改图号；图框位置/图幅不变
    sheet_id = None
    for e in s.components("AA_SHEET_"):
        a = {x["tag"]: x.get("text", {}).get("value", "")
             for x in e["geometry"].get("attribs", [])}
        if a.get("AA_TYPE") == "SHEET":
            sheet_id = a["AA_ID"]
            break
    if not sheet_id:
        raise RuntimeError("标准层模板找不到图幅")
    sheet = set_sheet(s, sheet_id, drawing=drawing, number=number)

    # 5F 是顶层，唯一必须和标准层不同的地方：楼梯只画“下”，不做上行箭头。
    if no == 5:
        for old_id, new_id, at in (("F2ST1", "F5ST1", (2400, 13120)),
                                   ("F2ST2", "F5ST2", (44400, 13120))):
            delete_component(s, "AA_STAIR_" + old_id)
            create_stair(s, new_id, at, "DOGLEG", width=1500, steps=13, tread=280,
                          rise=150, well=120, landing=1200, angle=90,
                          level="TOP", side="LEFT")

    s.run([], save=True)
    set_floor_attr(dxf, no)

    # 4) 回读 + 图面自检 + PNG
    snap = validate_floor(Session(dxf), no, "F2")
    a = audit(Session(dxf), tol=1.0)
    snap["audit"] = a
    snap["reconcile"] = reconcile(Session(dxf), fix=False, tol=1.0)
    png = OUT / (stem + ".png")
    win = (sheet["at"][0], sheet["at"][1],
           sheet["at"][0] + sheet["outer_wh"][0],
           sheet["at"][1] + sheet["outer_wh"][1])
    res = export(s, png, window=win, scale=drawing_scale(s))
    try:
        from PIL import Image
        im = Image.open(png)
        if im.size[0] < 2400 or im.size[1] < 1600:
            im = im.resize((2400, 1600))
            im.save(png)
        res["size"] = im.size
    except Exception as e:  # noqa: BLE001
        res["size_error"] = str(e)
    res["bytes"] = png.stat().st_size if png.exists() else 0
    snap["png"] = res
    snap["sheet"] = {"size": sheet["size"], "at": sheet["at"],
                     "outer": sheet["outer_wh"]}
    snap["source"] = str(SOURCE.name)
    append_png_check(snap, res, a)

    (OUT / (stem + ".json")).write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    if snap["errors"]:
        raise RuntimeError("%s 验收失败：%s" % (stem, snap["errors"]))
    return snap


def main(argv: list[str]) -> int:
    if not SOURCE.exists():
        raise SystemExit("缺少标准层模板 %s，请先运行 build_kindergarten.py 2" % SOURCE)
    targets = [int(x) for x in argv[1:]] or [3, 4, 5]
    for no in targets:
        snap = clone_floor(no)
        print("%dF -> %s：%d/%d，%s；%s" % (
            no, SPEC[no][0], sum(c["ok"] for c in snap["checks"]),
            len(snap["checks"]), snap["png"]["size"],
            "通过" if not snap["errors"] else snap["errors"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
