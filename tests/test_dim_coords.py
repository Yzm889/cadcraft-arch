"""M-DIM ④ 坐标标注验收。

口径：annotate(coords=True) 在建筑外廓每个墙角（墙中心线交点）注两行坐标：
  X=<纵坐标>（北，图面 y）/ Y=<横坐标>（东，图面 x），单位 m、两位小数——
  按测量坐标习惯 X 为纵坐标、Y 为横坐标（与总平面 site 的 "x,y" 无标注写法不同，这里有字母前缀）。
摆法：墙角的室外对角象限、最外道总尺寸线（22mm）再往外 12mm 起，整块文字在象限内，
      不跨轴线、不压轴号圈、不压尺寸文字。
断言：四个角各两行、数值正确、落 AA-DIM 层、几何不碰、audit/verify 不添错、
      幂等、默认 annotate 清掉、rescale 字高跟随、CLI/MCP。
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_mcp  # noqa: E402
from aa_lib import (  # noqa: E402
    LAYERS, Session, _text_w, annotate, annot_size, auto_rooms, audit,
    block_geometry, create_axis_grid, create_opening, create_wall, normalize_around,
    read_text, rescale_annotations, verify,
)

OUT = ROOT / "samples"
PATH = OUT / "test_dim_coords.dxf"
CLI_PATH = OUT / "test_dim_coords_cli.dxf"
MCP_PATH = OUT / "test_dim_coords_mcp.dxf"

O_OFF, W_OFF = 900.0, 1600.0
T_OFF = annot_size(22.0, 100.0)        # 最外道总尺寸线离墙中心线 2200
H = annot_size(2.5, 100.0)             # 坐标字高 250
# 角点编号按 (x, y) 排序：先比 x 再比 y -> 1 左下、2 左上、3 右下、4 右上
CORNERS = {1: (0.0, 0.0), 2: (0.0, 4800.0), 3: (6000.0, 0.0), 4: (6000.0, 4800.0)}
WANT = {1: ("X=0.00", "Y=0.00"), 2: ("X=4.80", "Y=0.00"),
        3: ("X=0.00", "Y=6.00"), 4: ("X=4.80", "Y=6.00")}


def build(path: Path) -> Session:
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    create_axis_grid(s, "AX001", xcount=2, xspace=6000.0, ycount=2, yspace=4800.0,
                     xstart=0.0, ystart=0.0, ext=1600.0)
    for wid, p1, p2 in (("W001", (0.0, 0.0), (6000.0, 0.0)),
                        ("W002", (6000.0, 0.0), (6000.0, 4800.0)),
                        ("W003", (6000.0, 4800.0), (0.0, 4800.0)),
                        ("W004", (0.0, 4800.0), (0.0, 0.0))):
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL")
        normalize_around(s, wid)
    create_opening(s, "D001", "W001", "DOOR", 1000.0, 1000.0, 2100.0)
    create_opening(s, "C001", "W002", "WINDOW", 1500.0, 2400.0, 1500.0)
    assert auto_rooms(s)["rooms"] == 1
    return s


def coord_boxes(s: Session, sc: float) -> dict[str, tuple[float, float, str, tuple]]:
    """坐标注字：id -> (box, text)。box = (x0, y0, x1, y1)。"""
    out = {}
    for e in s.components("AA_TXT_DIMC"):
        attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in e["geometry"]["attribs"]}
        tid = attrs["AA_ID"]
        t = read_text(s, tid)
        w = _text_w(t["text"], t["height"])
        out[tid] = (t["at"][0], t["at"][1], t["at"][0] + w, t["at"][1] + t["height"], t["text"], e.get("layer"))
    return out


def overlaps(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def rect_circle(box: tuple, cx: float, cy: float, r: float) -> bool:
    px = min(max(cx, box[0]), box[2])
    py = min(max(cy, box[1]), box[3])
    return math.dist((px, py), (cx, cy)) <= r


def main() -> int:
    s = build(PATH)

    # 0) 默认不注坐标；audit 基线
    base = annotate(s, O_OFF, W_OFF)
    assert base["dims"] == 10 and base["coords"] == 0, base
    assert s.components("AA_TXT_DIMC") == []
    a0 = audit(s)

    # 1) 四个角各两行，数值正确，落 AA-DIM
    res = annotate(s, O_OFF, W_OFF, coords=True)
    assert res["coords"] == 4 and res["dims"] == 10, res
    boxes = coord_boxes(s, 100.0)
    assert len(boxes) == 8, sorted(boxes)
    for idx, (wx, wy) in WANT.items():
        assert read_text(s, "DIMC%dX" % idx)["text"] == wx, read_text(s, "DIMC%dX" % idx)
        assert read_text(s, "DIMC%dY" % idx)["text"] == wy, read_text(s, "DIMC%dY" % idx)
    assert {v[5] for v in boxes.values()} == {LAYERS["dim"]}, {v[5] for v in boxes.values()}
    assert s.attributes("AA_CFG_DIM").get("AA_COORDS") == "1"

    # 2) 摆法：在墙角的室外对角象限，近边离墙角 >= 总尺寸线偏移，整块不出象限
    for idx, (cx, cy) in CORNERS.items():
        ox = 1.0 if cx > 3000 else -1.0
        oy = 1.0 if cy > 2400 else -1.0
        for suffix in ("X", "Y"):
            b = boxes["DIMC%d%s" % (idx, suffix)]
            if ox < 0:
                assert b[2] <= cx - T_OFF + 0.5, (idx, suffix, b)
            else:
                assert b[0] >= cx + T_OFF - 0.5, (idx, suffix, b)
            if oy < 0:
                assert b[3] <= cy - T_OFF + 0.5, (idx, suffix, b)
            else:
                assert b[1] >= cy + T_OFF - 0.5, (idx, suffix, b)
            # 字高按 2.5mm
            assert abs((b[3] - b[1]) - H) < 0.5, (idx, suffix, b)
        # 两行不重叠，X 在上、Y 在下，左端对齐
        bx, by = boxes["DIMC%dX" % idx], boxes["DIMC%dY" % idx]
        assert bx[1] > by[3] and abs(bx[0] - by[0]) < 0.5, (bx, by)

    # 3) 不压轴号圈、不压尺寸文字
    circles = [(g["pts"][0][0], g["pts"][0][1], float(g["r"]))
               for g in block_geometry(PATH, "AA_AXGRID_AX001") if g["type"] == "CIRCLE"]
    assert len(circles) == 4, circles
    hd = annot_size(2.5, 100.0)
    dim_boxes = []
    for e in s.entities().get("entities", []):
        if e["type"] != "Dimension":
            continue
        g = e["geometry"]
        mid = g["textMid"]
        w = _text_w("%g" % float(g["measurement"]), hd)
        rot = ((g.get("kind") or {}).get("linear") or {}).get("rotation", 0.0)
        if abs(math.sin(float(rot))) > 0.5:
            dim_boxes.append((mid["x"] - hd / 2, mid["y"] - w / 2, mid["x"] + hd / 2, mid["y"] + w / 2))
        else:
            dim_boxes.append((mid["x"] - w / 2, mid["y"] - hd / 2, mid["x"] + w / 2, mid["y"] + hd / 2))
    assert len(dim_boxes) == 10, len(dim_boxes)
    for tid, b in boxes.items():
        for cx, cy, r in circles:
            assert not rect_circle(b, cx, cy, r), (tid, b, (cx, cy, r))
        for db in dim_boxes:
            assert not overlaps(b, db), (tid, b, db)

    # 4) audit / verify 不添错
    v = verify(s)
    assert v["count"] == 0, v["issues"]
    a1 = audit(s)
    assert a1["count"] == a0["count"], (a0["issues"], a1["issues"])

    # 5) 幂等；默认 annotate 清掉坐标注字
    again = annotate(s, O_OFF, W_OFF, coords=True)
    assert again["coords"] == 4 and len(coord_boxes(s, 100.0)) == 8, again
    off = annotate(s, O_OFF, W_OFF)
    assert off["coords"] == 0 and s.components("AA_TXT_DIMC") == [], off
    assert s.attributes("AA_CFG_DIM").get("AA_COORDS") == "0"

    # CLI / MCP 用的副本在改比例之前拷
    shutil.copyfile(PATH, CLI_PATH)
    shutil.copyfile(PATH, MCP_PATH)

    # 6) rescale：字高跟随比例，数值不变
    annotate(s, O_OFF, W_OFF, coords=True)
    rs = rescale_annotations(s, 50.0)
    assert rs["dims"] == 10, rs
    t = read_text(s, "DIMC4X")
    assert t["text"] == "X=4.80" and t["height"] == 125.0, t
    assert len(coord_boxes(s, 50.0)) == 8

    # 7) CLI
    cli = [sys.executable, str(ROOT / "tools" / "aa_cmd.py")]
    r = subprocess.run(cli + ["dim", str(CLI_PATH), "--coords",
                              "--opening-off", "900", "--wall-off", "1600"],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr or r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] and out["coords"] == 4 and out["dims"] == 10, out

    # 8) MCP
    out = aa_mcp.call_tool("aa_dim", {"path": str(MCP_PATH), "opening_off": O_OFF,
                                      "wall_off": W_OFF, "coords": True})
    assert out["ok"] and out["coords"] == 4 and out["dims"] == 10, out

    print("PASS test_dim_coords (coords=%d)" % res["coords"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
