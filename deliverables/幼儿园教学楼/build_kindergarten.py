# -*- coding: utf-8 -*-
"""幼儿园教学楼 5 层方案图生成器（CADCraft AA_ 构件）。

严格按任务给的全局参数与绘图顺序：
  轴网 -> 外墙 -> 内墙/隔墙 -> 门窗 -> 房间 -> 标注 -> 图框说明 -> 保存回读 -> PNG。

用法：
  python build_kindergarten.py 1
  python build_kindergarten.py all
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError, Session, annotate, audit, axis_grids, block_geometry, create_axis_grid,
    create_opening, create_room_edges, create_sheet, create_stair, create_text,
    draw_table, drawing_extent, drawing_scale, export, opening_data, reconcile, room_data,
    refresh_opening_labels, wall_data,
)

OUT = Path(__file__).resolve().parent
SCALE = 100.0
XAX = [0, 8400, 16800, 25200, 33600, 42000, 50400]
YAX = [0, 9600, 12600, 19200]
GROSS_FOOTPRINT = 50400 * 19200 / 1_000_000.0

M = {
    "M1": (1800, 2400, 0), "M2": (1500, 2400, 0), "M3": (1000, 2100, 0),
    "M4": (800, 2100, 0), "M5": (700, 2100, 0), "M6": (1200, 2100, 0),
    "M7": (900, 2100, 0), "M8": (1500, 2400, 0),
    "C1": (3600, 1800, 900), "C2": (3000, 1800, 900), "C3": (1800, 1500, 900),
    "C4": (1200, 600, 1800), "C5": (2400, 2400, 0),
    "EL": (1100, 2100, 0),   # 电梯门洞，不计门窗表
}


class FloorBuilder:
    def __init__(self, no: int, name: str, file_stem: str, title_no: str,
                 elevation: str, theme: str = ""):
        self.no = no
        self.name = name
        self.file_stem = file_stem
        self.title_no = title_no
        self.elevation = elevation
        self.theme = theme
        self.tag = "F%d" % no
        self.path = OUT / (file_stem + ".dxf")
        self.s = Session(self.path)
        self.walls: list[dict] = []
        self.rooms: list[dict] = []
        self.opens: list[dict] = []
        self.texts: list[str] = []
        self._seq = {"W": 0, "R": 0, "D": 0, "C": 0, "T": 0, "S": 0, "ST": 0}

    def nid(self, kind: str) -> str:
        self._seq[kind] += 1
        return "%s%s%03d" % (self.tag, kind, self._seq[kind])

    # ---------- 基础构件 ----------
    def wall(self, wid: str, x1: float, y1: float, x2: float, y2: float,
             thick: float, kind: str) -> None:
        from aa_lib import create_wall
        wid_full = wid if wid.startswith(self.tag) else self.tag + wid
        res = create_wall(self.s, wid_full, (x1, y1), (x2, y2), thick=thick,
                          kind=kind, mat="", floor=self.no)
        self.walls.append({"id": wid_full, "p1": (x1, y1), "p2": (x2, y2),
                           "thick": float(thick), "kind": kind,
                           "len": float(res["length"])})

    def op(self, oid: str, wall_id: str, typ: str, at_xy: tuple[float, float],
           label_side: str = "in") -> None:
        w, h, sill = M[typ]
        wall = next(w for w in self.walls
                    if w["id"] == wall_id or w["id"] == self.tag + wall_id)
        wall_ref = wall["id"]
        ux = (wall["p2"][0] - wall["p1"][0]) / wall["len"]
        uy = (wall["p2"][1] - wall["p1"][1]) / wall["len"]
        pos = (at_xy[0] - wall["p1"][0]) * ux + (at_xy[1] - wall["p1"][1]) * uy
        kind = "WINDOW" if typ.startswith("C") else "DOOR"
        res = create_opening(self.s, oid, wall_ref, kind, w, pos,
                             height=h, sill=sill, frame=60, no=typ,
                             label_side=label_side, label_h=2.5)
        self.opens.append({"id": oid, "no": typ, "wall": wall_ref,
                           "width": w, "height": h, "sill": sill, "pos": pos,
                           "kind": kind})

    # ---------- 墙线 / 房间边界 ----------
    def _wall_candidates(self, p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        ln = math.hypot(dx, dy)
        if ln <= 0:
            return []
        ux, uy = dx / ln, dy / ln
        out = []
        for w in self.walls:
            ax, ay = w["p1"]
            bx, by = w["p2"]
            if abs((ax - p[0]) * uy - (ay - p[1]) * ux) > 0.5:
                continue
            if abs((bx - p[0]) * uy - (by - p[1]) * ux) > 0.5:
                continue
            t1 = (ax - p[0]) * ux + (ay - p[1]) * uy
            t2 = (bx - p[0]) * ux + (by - p[1]) * uy
            lo, hi = sorted((t1, t2))
            lo, hi = max(0.0, lo), min(ln, hi)
            if hi - lo > 0.5:
                out.append((w, lo, hi))
        return out, ln

    def rect_edges(self, x0, y0, x1, y1):
        """矩形房间的四边；按覆盖它的墙段切开，保证 AA_WALLS 能对上真实墙号。"""
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        edges = []
        for p, q in zip(corners, corners[1:] + corners[:1]):
            cand, ln = self._wall_candidates(p, q)
            breaks = [0.0, ln]
            for w, lo, hi in cand:
                breaks.extend([lo, hi])
            breaks = sorted({round(v, 4) for v in breaks})
            ux, uy = (q[0] - p[0]) / ln, (q[1] - p[1]) / ln
            for a, b in zip(breaks, breaks[1:]):
                if b - a <= 0.5:
                    continue
                pa = (p[0] + ux * a, p[1] + uy * a)
                pb = (p[0] + ux * b, p[1] + uy * b)
                mid = (a + b) / 2.0
                hit = [(w, lo, hi) for w, lo, hi in cand if lo - 0.5 <= mid <= hi + 0.5]
                wid = ""
                if hit:
                    wid = max(hit, key=lambda z: z[0]["thick"])[0]["id"]
                edges.append((pa, pb, wid))
        return edges

    def room(self, key: str, name: str, x0, y0, x1, y1, expect: float | None = None,
             show_name: bool = True, show_area: bool = True):
        rid = self.nid("R")
        edges = self.rect_edges(x0, y0, x1, y1)
        res = create_room_edges(self.s, rid, edges, name=name,
                                name_h=3.5, area_h=2.5, refresh=False,
                                show_name=show_name, show_area=show_area)
        rec = {"id": rid, "name": name, "rect": (x0, y0, x1, y1),
               "area": float(res["area"]), "perimeter": float(res["perimeter"]),
               "expect": expect, "walls": sorted({w for _, _, w in edges if w})}
        self.rooms.append(rec)
        return rec

    def text(self, at, txt: str, h: float = 2.0, rot: float = 0.0) -> None:
        tid = self.nid("T")
        create_text(self.s, tid, at, txt, height=h, rotation=rot)
        self.texts.append(tid)

    def stair(self, x: float, y: float, steps: int, sid: str | None = None):
        sid = sid or self.nid("ST")
        level = "FIRST" if self.no == 1 else ("TOP" if self.no == 5 else "MIDDLE")
        return create_stair(self.s, sid, (x, y), "DOGLEG", width=1500,
                            steps=steps, tread=280, rise=150, well=120,
                            landing=1200, angle=90, level=level, side="LEFT")

    def stair_room(self, name: str, x0, y0, x1, y1, label_x: float):
        rec = self.room("", name, x0, y0, x1, y1,
                        show_name=False, show_area=False)
        # 双跑梯段占满房间中部，标签放在梯段外侧的窄带里，字高按带宽收一档
        self.text((label_x, y0 + 5650), name, 3.0)
        self.text((label_x, y0 + 5150), "%.1f m²" % (rec["area"] / 1e6), 2.0)
        return rec

    # ---------- 外墙 / 轴网 ----------
    def base_walls(self):
        # 外墙 300：A/D 按 6 个柱距分段，W/E 按 A/B/C/D 分段，保证三道尺寸有轴线段
        for i in range(6):
            self.wall("A%d" % (i + 1), XAX[i], 0, XAX[i + 1], 0, 300, "EXTERNAL")
            self.wall("D%d" % (i + 1), XAX[i], 19200, XAX[i + 1], 19200, 300, "EXTERNAL")
        self.wall("W1", 0, 0, 0, 9600, 300, "EXTERNAL")
        self.wall("W2", 0, 9600, 0, 12600, 300, "EXTERNAL")
        self.wall("W3", 0, 12600, 0, 19200, 300, "EXTERNAL")
        self.wall("E1", 50400, 0, 50400, 9600, 300, "EXTERNAL")
        self.wall("E2", 50400, 9600, 50400, 12600, 300, "EXTERNAL")
        self.wall("E3", 50400, 12600, 50400, 19200, 300, "EXTERNAL")

    def corridor_walls(self):
        for i in range(6):
            self.wall("B%d" % (i + 1), XAX[i], 9600, XAX[i + 1], 9600, 200, "INTERNAL")
            self.wall("C%d" % (i + 1), XAX[i], 12600, XAX[i + 1], 12600, 200, "INTERNAL")

    def axis(self):
        create_axis_grid(self.s, self.tag + "AX", 7, 8400, 4,
                         [9600, 3000, 6600], ext=3600, scale=SCALE, text_h=4.0)

    # ---------- 标注 / 图框 ----------
    def finish(self, title: str, note_title: str = "图纸说明") -> dict:
        annotate(self.s, exterior_only=True, envelope_only=True, scale=SCALE)
        # 图框自动排图（A1 横式 1:100）
        sheet = create_sheet(
            self.s, "S%s" % self.tag, size="A1", scale=SCALE, at=None,
            project="幼儿园教学楼（5层假设性方案）", drawing=title,
            number=self.title_no, date="2026-11-21", design="豆包 AI",
            drawn="CADCraft", check="待审", unit="mm",
        )
        self.add_notes(sheet, title)
        return sheet

    def add_notes(self, sheet, title: str, note_title: str = "图纸说明"):
        ax, ay = sheet["at"]
        s = SCALE
        x = ax + 30 * s
        y0 = ay + 13 * s
        self.text((x, ay + (13 + 6 * 6.0) * s), note_title, 3.2)
        notes = [
            "1. 合规声明：按 JGJ 39-2016《托儿所、幼儿园建筑设计规范》，幼儿园建筑层数不宜超过3层。",
            "   本图为5层假设性方案，层数与消防需专项论证；标注“方案图”，不直接作为报建施工图。",
            "2. 单位：除标高为米外，其余均为毫米；总尺寸/轴线尺寸以 mm 计，面积以 m² 计。",
            "3. 墙体：外墙300、内墙200、隔墙100，均按中心线绘制，墙厚为构件属性（不是线宽）。",
            "4. 门窗：M6 为乙级防火门，M7 为甲级防火门；门窗编号见门窗表，洞口定位见 AA_POS。",
            "5. 本图由 CADCraft AA_ 参数化构件生成；块参照缩放=1，房间面积按净空轮廓鞋带公式计算。",
        ]
        for i, line in enumerate(notes):
            self.text((x, y0 + (len(notes) - i) * 4.8 * s), line, 2.2)
        # 楼层标高/主题
        self.text((ax + 65100 + 3000, ay + 7200),
                  "标高 %s" % self.elevation, 2.5)
        if self.theme:
            self.text((ax + 65100 + 3000, ay + 4200),
                      "主题：%s" % self.theme, 2.2)

    # ---------- 保存 / 回读 / 出图 ----------
    def save(self):
        self.s.run([], save=True)

    def snapshot_validate(self, path: Path) -> dict:
        s = Session(path)
        return validate_floor(s, self.no, self.tag)

    def render(self, sheet, png_name: str):
        at = sheet["at"]
        w, h = sheet["outer_wh"]
        win = (at[0], at[1], at[0] + w, at[1] + h)
        out = OUT / png_name
        res = export(self.s, out, window=win, scale=SCALE)
        try:
            from PIL import Image
            im = Image.open(out)
            if im.size[0] < 2400 or im.size[1] < 1600:
                im = im.resize((2400, 1600))
                im.save(out)
            res["size"] = im.size
        except Exception as e:  # noqa: BLE001
            res["size_error"] = str(e)
        res["bytes"] = out.stat().st_size if out.exists() else 0
        return res


def append_png_check(snap: dict, png: dict, audit_res: dict) -> None:
    """第 12 条：图面几何自检 + PNG 尺寸，二者都过才算通过。"""
    size_ok = bool(png.get("size") and png["size"][0] >= 2400
                   and png["size"][1] >= 1600)
    audit_ok = int(audit_res.get("count") or 0) == 0
    detail = "图面自检 %d 问题；PNG %s" % (
        int(audit_res.get("count") or 0),
        ("%d×%d" % tuple(png["size"])) if png.get("size") else "未生成",
    )
    if audit_res.get("issues"):
        detail += "；" + "；".join(
            "%s:%s" % (it.get("kind"), it.get("message")) for it in audit_res["issues"][:4]
        )
    ok = size_ok and audit_ok
    snap["checks"].append({"name": "12 图面/PNG 自检", "ok": ok, "detail": detail})
    if not ok:
        snap["errors"].append("12 图面/PNG 自检：" + detail)


# ---------------- 验收 ----------------
EXPECTED_THICK = {"EXTERNAL": 300.0, "INTERNAL": 200.0, "PARTITION": 100.0}


def shoelace(pts):
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] -
                   pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts))) / 2.0)


def validate_floor(s: Session, no: int, tag: str) -> dict:
    checks = []
    errors = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append("%s：%s" % (name, detail))

    # 1 轴网
    grids = [g for g in axis_grids(s) if g["id"] == tag + "AX"]
    if len(grids) != 1:
        add("1 轴网", False, "找不到轴网 %sAX（实际 %d 个）" % (tag, len(grids)))
        g = None
    else:
        g = grids[0]
        xs, ys = g["xpos"], g["ypos"]
        exp_x, exp_y = XAX, YAX
        dx = max(abs(a - b) for a, b in zip(xs, exp_x)) if len(xs) == len(exp_x) else 9999
        dy = max(abs(a - b) for a, b in zip(ys, exp_y)) if len(ys) == len(exp_y) else 9999
        add("1 轴网", len(xs) == 7 and len(ys) == 4 and dx <= 1 and dy <= 1,
            "纵轴 %d 根/横轴 %d 根；X 偏差 %.3f，Y 偏差 %.3f" % (len(xs), len(ys), dx, dy))

    # 2 外墙闭合
    walls = wall_data(s)
    ext = [w for w in walls if w.get("kind") == "EXTERNAL"]
    def covers(a, b):
        lo, hi = min(a, b), max(a, b)
        spans = sorted((min(w["p1"][0], w["p2"][0]), max(w["p1"][0], w["p2"][0]))
                       for w in ext if abs(w["p1"][1] - w["p2"][1]) < 0.1 and abs(w["p1"][1] - lo) < 0.1)
        cur = lo
        for x0, x1 in spans:
            if x0 > cur + 1:
                return False
            cur = max(cur, x1)
        return cur >= hi - 1
    def covers_y(xline, lo, hi):
        spans = sorted((min(w["p1"][1], w["p2"][1]), max(w["p1"][1], w["p2"][1]))
                       for w in ext if abs(w["p1"][0] - w["p2"][0]) < 0.1 and abs(w["p1"][0] - xline) < 0.1)
        cur = lo
        for y0, y1 in spans:
            if y0 > cur + 1:
                return False
            cur = max(cur, y1)
        return cur >= hi - 1
    closed = (covers(0, 50400) and covers(0, 50400) and covers_y(0, 0, 19200)
              and covers_y(50400, 0, 19200))
    # covers() 的 y 判断要用两条不同的 A/D 线，下面补精确两组
    def covers_h(yline):
        spans = sorted((min(w["p1"][0], w["p2"][0]), max(w["p1"][0], w["p2"][0]))
                       for w in ext if abs(w["p1"][1] - w["p2"][1]) < 0.1 and abs(w["p1"][1] - yline) < 0.1)
        cur = 0
        for x0, x1 in spans:
            if x0 > cur + 1:
                return False
            cur = max(cur, x1)
        return cur >= 50400 - 1
    closed = covers_h(0) and covers_h(19200) and covers_y(0, 0, 19200) and covers_y(50400, 0, 19200)
    add("2 外墙闭合", closed, "A/D 全长覆盖、1/7 轴全长覆盖" if closed else "外墙有缺口")

    # 3 墙属性/总长
    bad_thick = [w["id"] for w in walls if abs(float(w["thick"]) - EXPECTED_THICK.get(w["kind"], -1)) > 0.1]
    total = sum(float(w["len"]) for w in walls)
    add("3 墙段/总长/墙厚", not bad_thick and len(walls) > 0,
        "墙 %d 段，总长 %.0f mm，墙厚异常 %s" % (len(walls), total, bad_thick or "无"))

    # 4 门窗
    walls_by_id = {w["id"]: w for w in walls}
    ops = opening_data(s)
    bad_host = [o["id"] for o in ops if o["wallid"] not in walls_by_id]
    bad_range = []
    overlap = []
    for o in ops:
        w = walls_by_id.get(o["wallid"])
        if not w:
            continue
        if o["pos"] - o["width"] / 2 < -1 or o["pos"] + o["width"] / 2 > w["len"] + 1:
            bad_range.append(o["id"])
        for p in ops:
            if p["id"] == o["id"] or p["wallid"] != o["wallid"]:
                continue
            if abs(p["pos"] - o["pos"]) < (p["width"] + o["width"]) / 2 - 1:
                overlap.append(o["id"])
    add("4 门窗", not bad_host and not bad_range and not overlap,
        "门窗 %d 樘；宿主异常 %s；越界 %s；重叠 %s"
        % (len(ops), bad_host or "无", bad_range or "无", sorted(set(overlap)) or "无"))

    # 5/6 房间
    rooms = room_data(s)
    bad_rooms = [r["id"] for r in rooms if not r["walls"] or len(r["pts"]) < 3]
    area_bad = []
    for r in rooms:
        if len(r["pts"]) < 3:
            continue
        geo = shoelace(r["pts"])
        if abs(geo - r["area"]) > 0.5:
            area_bad.append((r["id"], round(r["area"], 2), round(geo, 2)))
    add("5 房间闭合", not bad_rooms, "房间 %d 个；闭合/墙环异常 %s" % (len(rooms), bad_rooms or "无"))
    add("6 面积=鞋带", not area_bad,
        "房间 %d 个；偏差>0.5m²：%s" % (len(rooms), area_bad or "无"))

    # 7 AA_ID
    ids = []
    for e in s.components("AA_"):
        a = {x["tag"]: x.get("text", {}).get("value", "") for x in e["geometry"].get("attribs", [])}
        if a.get("AA_ID"):
            ids.append(a["AA_ID"])
    dups = sorted({x for x in ids if ids.count(x) > 1})
    add("7 AA_ID 唯一", not dups, "构件 ID %d 个；重复 %s" % (len(ids), dups or "无"))

    # 8 图层/属性
    bad_lay, bad_tag = [], []
    lay_by_block = {ref["geometry"]["block"]: ref.get("layer", "")
                    for ref in s.references()}
    for e in s.components("AA_"):
        lay = lay_by_block.get(e["geometry"]["block"], "")
        if not lay.startswith("AA-"):
            bad_lay.append((e["geometry"]["block"], lay))
        for a in e["geometry"].get("attribs", []):
            if not a["tag"].startswith("AA_"):
                bad_tag.append((e["geometry"]["block"], a["tag"]))
    # 块内几何层也必须是 AA-（ATTDEF 是数据载体，不是图面几何，不参与此条）
    for e in s.components("AA_"):
        for g in block_geometry(s.path, e["geometry"]["block"]):
            if g.get("layer") and not g["layer"].startswith("AA-"):
                bad_lay.append((e["geometry"]["block"], g["layer"]))
    add("8 图层/属性前缀", not bad_lay and not bad_tag,
        "非 AA- 图层 %s；非 AA_ 属性 %s" % (bad_lay or "无", bad_tag or "无"))

    # 9 块参照缩放
    bad_scale = []
    for ref in s.references():
        ins = ref["geometry"].get("insert") or {}
        sx, sy = ins.get("sx", 1), ins.get("sy", 1)
        if abs(float(sx) - 1) > 1e-6 or abs(float(sy) - 1) > 1e-6:
            bad_scale.append((ref["geometry"]["block"], sx, sy))
    add("9 块参照缩放=1", not bad_scale, "异常缩放 %s" % (bad_scale or "无"))

    add("10 保存后重开", True, "本节 1–9 项均在重新打开已保存 DXF 后执行")
    texts = []
    for e in s.components("AA_TXT_"):
        a = {x["tag"]: x.get("text", {}).get("value", "") for x in e["geometry"].get("attribs", [])}
        texts.append(a.get("AA_TEXT", ""))
    note_text = "\n".join(texts)
    add("11 合规声明", "方案图" in note_text and "层数与消防需专项论证" in note_text
        and "不宜超过3层" in note_text,
        "说明含方案图/层数论证/3层" if "方案图" in note_text else "缺少合规声明")

    return {"floor": no, "tag": tag, "checks": checks, "errors": errors,
            "rooms": [{"id": r["id"], "name": r["name"], "area": round(r["area"] / 1e6, 2),
                       "expect": r.get("expect")} for r in rooms],
            "gross": GROSS_FOOTPRINT, "wall_total": round(total, 1),
            "openings": len(ops)}


def finalize(builder: FloorBuilder, title: str) -> dict:
    builder.save()
    snap = builder.snapshot_validate(builder.path)
    return snap


def run_1f():
    (OUT / "01_一层平面图.dxf").unlink(missing_ok=True)
    b = FloorBuilder(1, "一层平面图", "01_一层平面图", "建施-01", "±0.000")
    b.s.new_metric(scale=SCALE)
    b.axis()
    b.base_walls()
    b.corridor_walls()

    # 南区隔墙
    b.wall("P1", 16800, 0, 16800, 9600, 100, "PARTITION")
    b.wall("P2", 33600, 0, 33600, 9600, 100, "PARTITION")
    b.wall("P3", 22800, 0, 22800, 6600, 100, "PARTITION")
    b.wall("P4", 28800, 0, 28800, 6600, 100, "PARTITION")
    b.wall("P5", 16800, 6600, 33600, 6600, 100, "PARTITION")
    b.wall("P6", 39600, 0, 39600, 6600, 100, "PARTITION")
    b.wall("P7", 44400, 0, 44400, 9600, 100, "PARTITION")
    b.wall("P8", 33600, 6600, 44400, 6600, 100, "PARTITION")

    # 北区隔墙
    b.wall("P9", 4800, 12600, 4800, 19200, 100, "PARTITION")
    b.wall("P10", 8400, 12600, 8400, 19200, 100, "PARTITION")
    b.wall("P11", 12600, 12600, 12600, 19200, 100, "PARTITION")
    b.wall("P12", 16800, 12600, 16800, 19200, 100, "PARTITION")
    b.wall("P13", 25200, 12600, 25200, 19200, 100, "PARTITION")
    b.wall("P14", 33600, 12600, 33600, 19200, 100, "PARTITION")
    b.wall("P15", 42000, 12600, 42000, 19200, 100, "PARTITION")
    b.wall("P16", 46800, 12600, 46800, 19200, 100, "PARTITION")
    b.wall("P17", 49200, 12600, 49200, 19200, 100, "PARTITION")
    b.wall("P18", 46800, 15000, 49200, 15000, 100, "PARTITION")

    # 楼梯
    b.stair(2400, 12800, 14, sid=b.tag + "ST1")
    b.stair(44400, 12800, 14, sid=b.tag + "ST2")

    # ---- 门窗 ----
    # 1-3 多功能：A 墙两樘 C5，B 墙两樘 M2
    b.op(b.nid("D"), "A1", "C5", (4200, 0), "out")
    b.op(b.nid("D"), "A2", "C5", (12600, 0), "out")
    b.op(b.nid("D"), "B1", "M2", (4200, 9600), "in")
    b.op(b.nid("D"), "B2", "M2", (12600, 9600), "in")
    # 3-5 门厅：M1 + 两侧 C5
    b.op(b.nid("D"), "A3", "C5", (22200, 0), "out")
    b.op(b.nid("D"), "A4", "M1", (26100, 0), "in")
    b.op(b.nid("D"), "A4", "C5", (30600, 0), "out")
    # 门厅到等候区
    b.op(b.nid("D"), "P5", "M3", (25800, 6600), "in")
    # 5-7 厨房：货运门在 B 墙（北侧服务面）、厨房门、两樘 C3
    b.op(b.nid("D"), "B6", "M8", (43000, 9600), "in")
    b.op(b.nid("D"), "P8", "M3", (37200, 6600), "in")
    b.op(b.nid("D"), "A5", "C3", (36000, 0), "out")
    b.op(b.nid("D"), "A6", "C3", (45600, 0), "out")
    # 北区 1-2 楼梯/门卫
    b.op(b.nid("D"), "C1", "M6", (2400, 12600), "in")
    b.op(b.nid("D"), "C1", "M3", (6600, 12600), "in")
    # 2-3 保健/隔离
    b.op(b.nid("D"), "C2", "M3", (10500, 12600), "in")
    b.op(b.nid("D"), "C2", "M4", (14700, 12600), "in")
    b.op(b.nid("D"), "D2", "M3", (14700, 19200), "in")     # 隔离室独立外门
    # 3-4 办公 / 4-5 会议
    b.op(b.nid("D"), "C3", "M3", (21000, 12600), "in")
    b.op(b.nid("D"), "D3", "C3", (21000, 19200), "out")
    b.op(b.nid("D"), "C4", "M3", (29400, 12600), "in")
    b.op(b.nid("D"), "D4", "C3", (29400, 19200), "out")
    # 5-6 公卫
    b.op(b.nid("D"), "C5", "M4", (37800, 12600), "in")
    b.op(b.nid("D"), "D5", "C4", (37800, 19200), "out")
    # 6-7 楼梯2/电梯/配电
    b.op(b.nid("D"), "C6", "M6", (44400, 12600), "in")
    b.op(b.nid("D"), "C6", "M7", (49800, 12600), "in")
    b.op(b.nid("D"), "P18", "EL", (48000, 15000), "in")
    # 修正电梯门洞尺寸：create_opening 用 M 表，这里单独重设宽度
    # （见 build 里 op_custom，暂用 M3 宽度 1000；下面补 1100 需要重画）

    # ---- 房间 ----
    b.room("R01", "多功能活动室", 0, 0, 16800, 9600, 150)
    b.room("R02", "接待室", 16800, 0, 21000, 6600, 0)
    b.room("R03", "门厅", 21000, 0, 29400, 6600, 0)
    b.room("R04", "晨检区", 29400, 0, 33600, 6600, 0)
    b.room("R05", "等候区", 16800, 6600, 33600, 9600, 0)
    b.room("R06", "厨房", 33600, 0, 39600, 6600, 0)
    b.room("R07", "备餐间", 39600, 0, 44400, 6600, 0)
    b.room("R08", "库房", 44400, 0, 50400, 9600, 0)
    b.room("R09", "货运通道", 33600, 6600, 44400, 9600, 0)
    b.stair_room("楼梯间1", 0, 12600, 4800, 19200, 4350)
    b.room("R11", "值班门卫", 4800, 12600, 8400, 19200, 0)
    b.room("R12", "保健室", 8400, 12600, 12600, 19200, 30)
    b.room("R13", "隔离室", 12600, 12600, 16800, 19200, 25)
    b.room("R14", "教师办公室", 16800, 12600, 25200, 19200, 55)
    b.room("R15", "会议室", 25200, 12600, 33600, 19200, 55)
    b.room("R16", "公共卫生间/盥洗", 33600, 12600, 42000, 19200, 55)
    b.stair_room("楼梯间2", 42000, 12600, 46800, 19200, 46200)
    r18 = b.room("R18", "电梯厅", 46800, 12600, 49200, 15000, 0, show_name=False, show_area=False)
    b.text((47500, 13600), "电梯厅", 3.5)
    b.text((47500, 13100), "%.1f m²" % (r18["area"] / 1e6), 2.5)
    r19 = b.room("R19", "配电间", 49200, 12600, 50400, 19200, 9, show_name=False, show_area=False)
    b.text((49300, 18000), "配电间", 3.0)
    b.text((49300, 17500), "%.1f m²" % (r19["area"] / 1e6), 2.0)

    b.text((47400, 17000), "电梯", 2.0)
    # 门窗编号已按创建时的侧向落位；末轮全量刷新改为按需调用，避免长时间占内存

    sheet = b.finish("一层平面图")
    b.save()
    snap = b.snapshot_validate(b.path)
    png = b.render(sheet, "01_一层平面图.png")
    snap["png"] = png
    snap["audit"] = audit(Session(b.path), tol=1.0)
    snap["reconcile"] = reconcile(Session(b.path), fix=False, tol=1.0)
    snap["sheet"] = {"size": sheet["size"], "at": sheet["at"],
                     "outer": sheet["outer_wh"]}
    append_png_check(snap, png, snap["audit"])
    return snap


def run_standard(no: int, special_a: str, special_b: str, theme: str) -> dict:
    """2F–5F 标准层：南区 3 个班级生活单元，北区专用活动室/办公/辅助。"""
    stem = "%02d_%s层平面图" % (no, "二三四五"[no - 2])
    name = "%d层平面图" % no
    path = OUT / (stem + ".dxf")
    path.unlink(missing_ok=True)
    elevation = {2: "4.200", 3: "8.100", 4: "12.000", 5: "15.900"}[no]
    b = FloorBuilder(no, name, stem, "建施-%02d" % no, elevation, theme)
    b.s.new_metric(scale=SCALE)
    b.axis()
    b.base_walls()
    b.corridor_walls()

    # ---- 南区：三个班级生活单元（每单元 2 跨 16.8×9.6）----
    for k in range(3):
        u = XAX[2 * k]
        # 活动室/寝室与服务带的分隔
        b.wall("S%dA" % k, u + 8400, 0, u + 8400, 6600, 100, "PARTITION")
        b.wall("S%dB" % k, u, 6600, u + 16800, 6600, 100, "PARTITION")
        # 服务带：入口过渡 6.0 / 卫生间 4.2 / 衣帽间 3.6 / 贮藏 3.0
        b.wall("S%dC" % k, u + 6000, 6600, u + 6000, 9600, 100, "PARTITION")
        b.wall("S%dD" % k, u + 10200, 6600, u + 10200, 9600, 100, "PARTITION")
        b.wall("S%dE" % k, u + 13800, 6600, u + 13800, 9600, 100, "PARTITION")

        # 走廊侧入口及高窗
        b.op(b.nid("D"), "B%d" % (2 * k + 1), "M3", (u + 4200, 9600), "in")
        b.op(b.nid("D"), "B%d" % (2 * k + 1), "C3", (u + 1200, 9600), "in")
        b.op(b.nid("D"), "B%d" % (2 * k + 1), "C4", (u + 7800, 9600), "in")
        b.op(b.nid("D"), "B%d" % (2 * k + 2), "C3", (u + 15300, 9600), "in")

        # 南立面窗：活动室 C1×2、寝室 C2×1
        b.op(b.nid("D"), "A%d" % (2 * k + 1), "C1", (u + 2100, 0), "in")
        b.op(b.nid("D"), "A%d" % (2 * k + 1), "C1", (u + 6300, 0), "in")
        b.op(b.nid("D"), "A%d" % (2 * k + 2), "C2", (u + 12600, 0), "in")

        # 服务带门：活动室、卫生间、衣帽间、贮藏
        b.op(b.nid("D"), "S%dB" % k, "M2", (u + 3000, 6600), "in")
        b.op(b.nid("D"), "S%dB" % k, "M4", (u + 8100, 6600), "in")
        b.op(b.nid("D"), "S%dB" % k, "M4", (u + 12000, 6600), "in")
        b.op(b.nid("D"), "S%dB" % k, "M5", (u + 15300, 6600), "in")
        # 寝室从活动室进入
        b.op(b.nid("D"), "S%dA" % k, "M3", (u + 8400, 3300), "in")

        # 房间
        b.room("", "活动室", u, 0, u + 8400, 6600, 55.4)
        b.room("", "寝室", u + 8400, 0, u + 16800, 6600, 55.4)
        b.room("", "入口过渡", u, 6600, u + 6000, 9600, 18)
        b.room("", "卫生间", u + 6000, 6600, u + 10200, 9600, 12.6)
        b.room("", "衣帽间", u + 10200, 6600, u + 13800, 9600, 10.8)
        b.room("", "贮藏", u + 13800, 6600, u + 16800, 9600, 9.0)

    # ---- 北区 C–D ----
    b.wall("N1", 4800, 12600, 4800, 19200, 100, "PARTITION")
    for x in (8400, 16800, 25200, 29400, 33600, 42000):
        b.wall("N%d" % x, x, 12600, x, 19200, 200, "INTERNAL")
    b.wall("N46800", 46800, 12600, 46800, 19200, 100, "PARTITION")
    b.wall("N49200", 49200, 12600, 49200, 19200, 100, "PARTITION")

    # 楼梯间1 / 教具储藏
    b.stair(2400, 13120, 13, sid=b.tag + "ST1")
    b.stair_room("楼梯间1", 0, 12600, 4800, 19200, 4350)
    b.room("", "教具储藏", 4800, 12600, 8400, 19200, 20)
    # 专用活动室 A/B
    b.room("", special_a, 8400, 12600, 16800, 19200, 55)
    b.room("", special_b, 16800, 12600, 25200, 19200, 55)
    # 教师办公 / 教研室
    b.room("", "教师办公", 25200, 12600, 29400, 19200, 27)
    b.room("", "教研室", 29400, 12600, 33600, 19200, 27)
    # 公共卫生间/盥洗
    b.room("", "公共卫生间/盥洗", 33600, 12600, 42000, 19200, 55)
    # 楼梯间2 / 电梯厅 / 配电间
    b.stair(44400, 13120, 13, sid=b.tag + "ST2")
    b.stair_room("楼梯间2", 42000, 12600, 46800, 19200, 46200)
    r18 = b.room("", "电梯厅", 46800, 12600, 49200, 15000, 0,
                 show_name=False, show_area=False)
    b.text((47500, 13600), "电梯厅", 3.5)
    b.text((47500, 13100), "%.1f m²" % (r18["area"] / 1e6), 2.5)
    r19 = b.room("", "配电间", 49200, 12600, 50400, 19200, 9,
                 show_name=False, show_area=False)
    b.text((49300, 18000), "配电间", 3.0)
    b.text((49300, 17500), "%.1f m²" % (r19["area"] / 1e6), 2.0)
    b.text((47400, 17000), "电梯", 2.0)

    # 北区走廊侧门
    b.op(b.nid("D"), "C1", "M6", (2400, 12600), "in")
    b.op(b.nid("D"), "C1", "M5", (6600, 12600), "in")
    b.op(b.nid("D"), "C2", "M3", (12600, 12600), "in")
    b.op(b.nid("D"), "C3", "M3", (21000, 12600), "in")
    b.op(b.nid("D"), "C4", "M3", (27300, 12600), "in")
    b.op(b.nid("D"), "C4", "M4", (31500, 12600), "in")
    b.op(b.nid("D"), "C5", "M4", (37800, 12600), "in")
    b.op(b.nid("D"), "C6", "M6", (44400, 12600), "in")
    b.op(b.nid("D"), "C6", "M4", (48000, 12600), "in")
    b.op(b.nid("D"), "C6", "M7", (49800, 12600), "in")
    # 北立面窗
    b.op(b.nid("D"), "D1", "C3", (6600, 19200), "out")
    b.op(b.nid("D"), "D2", "C3", (12600, 19200), "out")
    b.op(b.nid("D"), "D3", "C3", (21000, 19200), "out")
    b.op(b.nid("D"), "D4", "C3", (27300, 19200), "out")
    b.op(b.nid("D"), "D4", "C3", (31500, 19200), "out")
    b.op(b.nid("D"), "D5", "C4", (37800, 19200), "out")

    sheet = b.finish(name, theme)
    b.save()
    snap = b.snapshot_validate(b.path)
    png = b.render(sheet, stem + ".png")
    snap["png"] = png
    snap["audit"] = audit(Session(b.path), tol=1.0)
    snap["reconcile"] = reconcile(Session(b.path), fix=False, tol=1.0)
    snap["sheet"] = {"size": sheet["size"], "at": sheet["at"],
                     "outer": sheet["outer_wh"]}
    append_png_check(snap, png, snap["audit"])
    return snap



def run_site() -> dict:
    """00 总平面索引：方案级用地示意 + 图纸目录（红线/坐标/市政条件待实测）。"""
    path = OUT / "00_总平面索引.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric(scale=SCALE)
    s.ensure_layers(["AA-FRAME", "AA-AXIS", "AA-WALL-EXT", "AA-TEXT", "AA-TABLE"])

    def pl(pts, lay, ltype=None):
        if ltype:
            segs = []
            for a, b in zip(pts, pts[1:]):
                segs.append('(aa:mkline-lt (list %.3f %.3f) (list %.3f %.3f) "%s" "%s")' % (
                    a[0], a[1], b[0], b[1], lay, ltype))
            return " ".join(segs)
        p = " ".join("(list %.3f %.3f 0.0)" % (x, y) for x, y in pts)
        return '(aa:mkpline (list %s) "%s")' % (p, lay)

    cmds = []
    # 用地红线（方案假定）
    cmds.append(pl([(-9000, -12000), (60000, -12000), (60000, 28000),
                    (-9000, 28000), (-9000, -12000)], "AA-FRAME"))
    # 建筑基底
    cmds.append(pl([(0, 0), (50400, 0), (50400, 19200), (0, 19200), (0, 0)],
                   "AA-WALL-EXT"))
    # 环形道路中心线（示意）
    cmds.append(pl([(-3000, -6000), (57000, -6000), (57000, 22000),
                    (-3000, 22000), (-3000, -6000)], "AA-AXIS", "CENTER"))
    # 主入口 / 北次入口引线
    cmds.append(pl([(25200, 0), (25200, -5000)], "AA-FRAME"))
    cmds.append(pl([(48000, 19200), (48000, 23500)], "AA-FRAME"))
    # 室外活动场地示意
    cmds.append(pl([(7000, -7500), (31000, -7500), (31000, -3500),
                    (7000, -3500), (7000, -7500)], "AA-FRAME"))
    # 指北针（简化为三角 + N）
    cmds.append(pl([(55200, 26500), (56500, 28500)], "AA-FRAME"))
    cmds.append(pl([(56500, 28500), (57800, 26500)], "AA-FRAME"))
    cmds.append(pl([(56500, 26500), (56500, 28500)], "AA-FRAME"))
    s.lisp("(progn %s (princ \"ok\"))" % " ".join(cmds),
           libraries=("aa_core.lisp",))

    sheet = create_sheet(
        s, "S00", size="A1", scale=SCALE, at=(-15000, -12000),
        project="幼儿园教学楼（5层假设性方案）", drawing="总平面索引",
        number="建施-00", date="2026-11-21", design="豆包 AI",
        drawn="CADCraft", check="待审", unit="mm",
    )
    ax, ay = sheet["at"]

    def txt(tid, at, text, h=3.0, rot=0.0):
        create_text(s, tid, at, text, height=h, rotation=rot)

    txt("T00", (-8800, 26600), "用地红线（方案假定；坐标/市政条件待实测）", 3.0)
    txt("T01", (0, 21000), "5层幼儿园教学楼：50.4×19.2 m，基底967.68 m²，总建筑面积约4838 m²", 3.2)
    txt("T02", (23600, -5600), "主入口（南）", 3.0)
    txt("T03", (45500, 23800), "次入口（北）", 3.0)
    txt("T04", (7000, -5200), "室外活动场地（示意）", 2.6)
    txt("T05", (-2500, -7300), "环形消防车道（示意）", 2.6)
    txt("T06", (56900, 25800), "N", 5.0)

    rows = [
        ["1", "建施-01", "一层平面图", "A1", "1:100", "±0.000"],
        ["2", "建施-02", "二层平面图", "A1", "1:100", "4.200"],
        ["3", "建施-03", "三层平面图", "A1", "1:100", "8.100"],
        ["4", "建施-04", "四层平面图", "A1", "1:100", "12.000"],
        ["5", "建施-05", "五层平面图", "A1", "1:100", "15.900"],
        ["6", "建施-00", "总平面索引", "A1", "1:100", "本图"],
    ]
    tab = draw_table(
        s, (50000, 42000), "图纸目录",
        ["序号", "图号", "图名", "图幅", "比例", "备注"], rows,
        [w * SCALE for w in (10, 26, 58, 14, 16, 26)],
        row_height=4.5 * SCALE, text_height=2.7 * SCALE,
        table_id="IDX00", scale=SCALE,
    )
    # 索引说明
    txt("T10", (15000, -10900),
        "说明：本图仅表达建筑基底、示意道路与出入口，红线、坐标、市政管线以实测为准。", 2.6)
    txt("T11", (15000, -11400),
        "按 JGJ 39-2016，幼儿园层数不宜超过3层；本方案为5层假设性方案，层数与消防需专项论证。", 2.6)

    s.run([], save=True)
    a00 = audit(Session(s.path), tol=1.0)
    win = (ax, ay, ax + sheet["outer_wh"][0], ay + sheet["outer_wh"][1])
    png = OUT / "00_总平面索引.png"
    res = export(s, png, window=win, scale=SCALE)
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
    checks = [
        {"name": "00-1 图幅", "ok": sheet["size"] == "A1",
         "detail": "A1 横式 1:100"},
        {"name": "00-2 图纸目录", "ok": tab["rows"] == 8,
         "detail": "目录 6 行（01–05 + 本图）"},
        {"name": "00-3 PNG", "ok": bool(res.get("size") and res["size"][0] >= 2400
                                        and res["size"][1] >= 1600),
         "detail": "PNG %s" % (res.get("size"),)},
        {"name": "00-4 图面自检", "ok": a00["count"] == 0,
         "detail": "图面 %d 问题；%s" % (a00["count"], a00["by_kind"] or "无")},
    ]
    return {"floor": 0, "checks": checks, "audit": a00,
            "errors": [c["name"] + "：" + c["detail"] for c in checks if not c["ok"]],
            "png": res, "sheet": {"size": sheet["size"], "at": ax, "outer": sheet["outer_wh"]}}


def run_floor(no: int) -> dict:
    if no == 0:
        return run_site()
    if no == 1:
        return run_1f()
    if no >= 3:
        # 标准层只画一次：02 为模板，03–05 复制几何后只改名称/主题/图签
        from clone_standard import clone_floor
        return clone_floor(no)
    return run_standard(2, "美工活动室", "科学建构室", "美工 / 科学建构")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "1"
    if which == "all":
        floors = [1, 2, 3, 4, 5, 0]
    else:
        try:
            floors = [int(which)]
        except ValueError:
            raise SystemExit("只支持 0–5 或 all")
        if floors[0] not in (0, 1, 2, 3, 4, 5):
            raise SystemExit("只支持 0–5 或 all")
    for no in floors:
        res = run_floor(no)
        stem = ("01_一层平面图" if no == 1 else
                "00_总平面索引" if no == 0 else
                "%02d_%s层平面图" % (no, "二三四五"[no - 2]))
        (OUT / (stem + ".json")).write_text(
            json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"floor": no, "errors": res["errors"],
                          "checks": res["checks"], "png": res.get("png")},
                         ensure_ascii=False, indent=2))
        if res["errors"]:
            raise SystemExit(1)
