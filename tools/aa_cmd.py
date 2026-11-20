"""cadcraft-arch 命令行入口。

AI 或用户直接用它驱动 CADCraft 画建筑平面：

  python tools/aa_cmd.py new    out.dxf
  python tools/aa_cmd.py axis   out.dxf AX001 --xcount 4 --xspace 4000 --ycount 3 --yspace 5000
  python tools/aa_cmd.py wall   out.dxf W001 --p1 0,0 --p2 3600,0 --thick 240
  python tools/aa_cmd.py opening out.dxf D001 --wall W001 --kind DOOR --width 1800 --pos 900
  python tools/aa_cmd.py room   out.dxf R001 --walls W001,W002,W003,W004 --name 客厅
  python tools/aa_cmd.py split  out.dxf
  python tools/aa_cmd.py merge  out.dxf [--walls W001,W003]
  python tools/aa_cmd.py show   out.dxf

所有命令输出一行 JSON；失败时输出 {"ok":false,"error":...} 并以非零码退出。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aa_lib import (  # noqa: E402
    LAYER_STYLES,
    LAYERS,
    CadError,
    Session,
    annotate,
    auto_axis,
    axis_grids,
    bind_walls_to_axis,
    auto_rooms,
    create_axis_grid,
    create_opening,
    create_room,
    create_wall,
    create_sheet,
    create_title_mark,
    create_north_arrow,
    create_column,
    rescale_annotations,
    set_drawing_scale,
    audit,
    create_elevation_mark,
    create_index_mark,
    create_section_mark,
    drawing_scale,
    export,
    layer_table,
    merge_walls,
    normalize_around,
    openings_report,
    rooms_report,
    set_opening,
    set_room,
    set_sheet,
    set_wall,
    sheet_window,
    split_at_intersections,
)


def _pt(text: str) -> tuple[float, float]:
    a, b = text.split(",")
    return float(a), float(b)


def _csv(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def components_report(session: Session) -> list[dict]:
    out = []
    for e in session.references():
        g = e["geometry"]
        name = g.get("block", "")
        if not name.startswith("AA_"):
            continue
        attrs = {a["tag"].replace("AA_", "").lower(): a.get("text", {}).get("value", "")
                 for a in g.get("attribs", [])}
        out.append({
            "block": name,
            "handle": e["handle"],
            "at": [g["insert"]["x"], g["insert"]["y"]],
            "rotation_deg": round(g.get("rotation", 0.0) * 57.29577951308232, 4),
            "attrs": attrs,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aa_cmd", description="cadcraft-arch 命令行")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="新建公制图纸")
    p_new.add_argument("path")
    p_new.add_argument("--scale", type=float, default=None,
                       help="出图比例分母（如 100 = 1:100）；给了就从开图起按该比例画注记")

    p_scale = sub.add_parser("scale", help="查看/设定图档出图比例（先定比例再画）")
    p_scale.add_argument("path")
    p_scale.add_argument("--set", type=float, default=None, help="设为新比例（已有注记默认整批重画）")
    p_scale.add_argument("--no-rescale", action="store_true", help="只改标记，不重画已有注记")

    p_axis = sub.add_parser("axis", help="生成轴网")
    p_axis.add_argument("path")
    p_axis.add_argument("id")
    p_axis.add_argument("--xcount", type=int, required=True)
    p_axis.add_argument("--xspace", type=float, required=True)
    p_axis.add_argument("--ycount", type=int, required=True)
    p_axis.add_argument("--yspace", type=float, required=True)
    p_axis.add_argument("--xstart", type=float, default=0.0)
    p_axis.add_argument("--ystart", type=float, default=0.0)
    p_axis.add_argument("--ext", type=float, default=1000.0)

    p_axis_auto = sub.add_parser("axis-auto", help="按现有墙段自动生成轴网（竖轴 1/2/3、横轴 A/B/C）")
    p_axis_auto.add_argument("path")
    p_axis_auto.add_argument("id", nargs="?", default="AX001")
    p_axis_auto.add_argument("--tol", type=float, default=50.0,
                            help="同一根轴上的墙段位置聚类容差（mm）")
    p_axis_auto.add_argument("--ext", type=float, default=2400.0, help="轴线端伸出最外轴的距离")
    p_axis_auto.add_argument("--min-len", type=float, default=0.0, help="忽略短于该长度的墙")
    p_axis_auto.add_argument("--no-bind", action="store_true", help="只出轴网，不回填墙的轴号")

    p_axis_bind = sub.add_parser("axis-bind", help="按现有轴网回填每堵墙的 AX1/AX2 轴号")
    p_axis_bind.add_argument("path")
    p_axis_bind.add_argument("--grid", default=None, help="指定轴网编号，默认用图上的")
    p_axis_bind.add_argument("--tol", type=float, default=50.0, help="端点与轴的允许偏差 mm")
    p_axis_bind.add_argument("--only-empty", action="store_true", help="只填空的，不覆盖已有轴号")

    p_column = sub.add_parser("column", help="柱：矩形实心柱 / 圆柱（落在 AA-COLUMN）")
    p_column.add_argument("path")
    p_column.add_argument("id")
    p_column.add_argument("--at", required=True, help="柱中心 x,y")
    p_column.add_argument("--w", type=float, required=True, help="柱宽（圆柱时是直径）")
    p_column.add_argument("--h", type=float, default=None, help="柱高（默认同宽）")
    p_column.add_argument("--kind", default="rect", choices=["rect", "circle"],
                          help="柱类型：rect 矩形 / circle 圆柱")
    p_column.add_argument("--angle", type=float, default=0.0, help="矩形柱转角（度，逆时针）")
    p_column.add_argument("--material", default="", help="材料，如 C30")

    p_title = sub.add_parser("title", help="图名标注：图名 + 比例 + 下画线（GB/T 50001）")
    p_title.add_argument("path")
    p_title.add_argument("id")
    p_title.add_argument("--at", required=True, help="图名文字插入点 x,y")
    p_title.add_argument("--name", required=True, help="图名文字，如 一层平面图")
    p_title.add_argument("--scale", default=None,
                         help="比例分母，如 100 表示 1:100；省略则取图档比例；留空字符串则不注比例")

    p_north = sub.add_parser("north", help="指北针（圆 + 指针）")
    p_north.add_argument("path")
    p_north.add_argument("id")
    p_north.add_argument("--at", required=True, help="圆心 x,y")
    p_north.add_argument("--size", type=float, default=None, help="圆直径（图元单位），默认 2400=24mm@1:100")

    p_elev = sub.add_parser("elev", help="标高符号：三角 + 数值（±0.000 / 3.600）")
    p_elev.add_argument("path")
    p_elev.add_argument("id")
    p_elev.add_argument("--at", required=True, help="标高尖端 x,y（三角尖指向这一点）")
    p_elev.add_argument("--value", required=True, help="标高值（m），如 0 / 3.6 / -0.45")
    p_elev.add_argument("--text", default=None, help="直接给文字（覆盖数值格式）")

    p_index = sub.add_parser("index", help="索引符号：圆 + 直径线，上详图编号下图号")
    p_index.add_argument("path")
    p_index.add_argument("id")
    p_index.add_argument("--at", required=True, help="圆心 x,y")
    p_index.add_argument("--detail", required=True, help="详图编号，如 1 或 5/1")
    p_index.add_argument("--sheetno", default="—", help="图号（同一张图写 —）")

    p_section = sub.add_parser("section", help="剖切符号：位置线 + 投射方向线 + 编号")
    p_section.add_argument("path")
    p_section.add_argument("id")
    p_section.add_argument("--p1", required=True, help="剖切位置线起点 x,y")
    p_section.add_argument("--p2", required=True, help="剖切位置线终点 x,y")
    p_section.add_argument("--dir", default="down", choices=["down", "up", "left", "right"],
                           help="投射方向（往哪边看）")
    p_section.add_argument("--no", default="1", help="剖切编号")

    p_audit = sub.add_parser("audit", help="图面自检：墙未接、门窗越界、文字重叠、尺寸压轴号、出图框")
    p_audit.add_argument("path")
    p_audit.add_argument("--strict", action="store_true", help="有 error 级问题就返回非零")

    p_rescale = sub.add_parser("rescale", help="按新出图比例重画全部注记（轴号/房间名/门窗编号/图名/指北针/尺寸）")
    p_rescale.add_argument("path")
    p_rescale.add_argument("--scale", type=float, required=True, help="新比例分母，如 50 表示 1:50")
    p_rescale.add_argument("--no-dims", action="store_true", help="不重画尺寸标注")

    p_layers = sub.add_parser("layers", help="查看/校正标准图层（颜色、线型、线宽）")
    p_layers.add_argument("path", nargs="?", default=None,
                          help="图纸路径；省略则只列出标准规格，不读图")
    p_layers.add_argument("--fix", action="store_true",
                          help="按标准建层/纠偏（缺层新建，颜色线型线宽不符就改），并回读校验")

    p_wall = sub.add_parser("wall", help="绘制墙体")
    p_wall.add_argument("path")
    p_wall.add_argument("id")
    p_wall.add_argument("--p1", required=True, help="起点 x,y")
    p_wall.add_argument("--p2", required=True, help="终点 x,y")
    p_wall.add_argument("--thick", type=float, default=240.0)
    p_wall.add_argument("--kind", default="INTERNAL",
                        choices=["EXTERNAL", "INTERNAL", "PARTITION"])
    p_wall.add_argument("--mat", default="")
    p_wall.add_argument("--ax1", default="")
    p_wall.add_argument("--ax2", default="")
    p_wall.add_argument("--snap-axis", action="store_true", help="把端点吸附到最近轴线（先轴后墙）")
    p_wall.add_argument("--snap-tol", type=float, default=300.0, help="吸附允许距离 mm")

    p_op = sub.add_parser("opening", help="门窗开洞")
    p_op.add_argument("path")
    p_op.add_argument("id")
    p_op.add_argument("--wall", required=True, help="所属墙编号")
    p_op.add_argument("--kind", default="DOOR", choices=["DOOR", "WINDOW", "DOORWIN"])
    p_op.add_argument("--width", type=float, required=True)
    p_op.add_argument("--pos", type=float, required=True, help="洞口中心到墙起点的距离")
    p_op.add_argument("--height", type=float, default=None)
    p_op.add_argument("--sill", type=float, default=0.0)
    p_op.add_argument("--frame", type=float, default=60.0, help="窗框厚，默认 60")
    p_op.add_argument("--no", default="", help="门窗编号，缺省按尺寸自动生成（M0921 / C1215）")
    p_op.add_argument("--label-side", default="in", choices=["in", "out", "auto", "leader"],
                      help="编号所在侧：in=室内（默认）/ out=室外 / auto=沿用旧行为")

    p_room = sub.add_parser("room", help="闭合墙环生成房间；--auto 自动搜环")
    p_room.add_argument("path")
    p_room.add_argument("id", nargs="?", default=None)
    p_room.add_argument("--walls", default="", help="按环形顺序的墙编号，逗号分隔（--auto 时忽略）")
    p_room.add_argument("--name", default="")
    p_room.add_argument("--no-area", action="store_true", help="房间只注名称，不注面积（天正默认为注面积）")
    p_room.add_argument("--auto", action="store_true", help="自动枚举闭合墙环并逐个建房间")
    p_room.add_argument("--prefix", default="R", help="自动编号前缀，默认 R")
    p_room.add_argument("--min-area", type=float, default=1.0, help="自动搜环时忽略的最小面积 mm²")

    p_show = sub.add_parser("show", help="列出全部 AA_ 构件与属性")
    p_show.add_argument("path")

    p_setw = sub.add_parser("set-wall", help="改墙厚/类型/材质/轴号并重绘（洞口与邻墙同步重建）")
    p_setw.add_argument("path")
    p_setw.add_argument("id")
    p_setw.add_argument("--thick", type=float, default=None)
    p_setw.add_argument("--kind", default=None,
                        choices=["EXTERNAL", "INTERNAL", "PARTITION"])
    p_setw.add_argument("--mat", default=None)
    p_setw.add_argument("--ax1", default=None)
    p_setw.add_argument("--ax2", default=None)

    p_seto = sub.add_parser("set-opening", help="改门窗位置/宽度/类型并重绘")
    p_seto.add_argument("path")
    p_seto.add_argument("id")
    p_seto.add_argument("--pos", type=float, default=None)
    p_seto.add_argument("--width", type=float, default=None)
    p_seto.add_argument("--height", type=float, default=None)
    p_seto.add_argument("--sill", type=float, default=None)
    p_seto.add_argument("--kind", default=None, choices=["DOOR", "WINDOW", "DOORWIN"])
    p_seto.add_argument("--frame", type=float, default=None)
    p_seto.add_argument("--no", default=None)
    p_seto.add_argument("--label-side", default=None, choices=["in", "out", "auto", "leader"],
                        help="编号所在侧：in=室内（默认）/ out=室外 / auto=沿用旧行为")

    p_openings = sub.add_parser("openings", help="门窗表：按编号汇总尺寸与数量，可导出 CSV / 图上表格")
    p_openings.add_argument("path")
    p_openings.add_argument("--csv", default=None, help="导出 CSV 路径（UTF-8 BOM）")
    p_openings.add_argument("--table", default=None, help="在图上插入表格，给左下角 x,y")
    p_openings.add_argument("--title", default="门窗表")

    p_dim = sub.add_parser("dim", help="尺寸标注：外墙墙段长度 + 洞口宽，标在建筑外侧")
    p_dim.add_argument("path")
    p_dim.add_argument("--opening-off", type=float, default=700.0, help="洞口尺寸线离墙面距离")
    p_dim.add_argument("--wall-off", type=float, default=1150.0, help="墙段尺寸线离墙面距离")
    p_dim.add_argument("--all-walls", action="store_true", help="连内墙一起标（默认只标外墙）")

    p_split = sub.add_parser("split", help="墙体相交自动切断")
    p_split.add_argument("path")

    p_merge = sub.add_parser("merge", help="合并共线相接的墙段")
    p_merge.add_argument("path")
    p_merge.add_argument("--walls", default="", help="指定要合并的墙编号（逗号分隔）；省略则按 AA_ROOT 自动聚合")

    p_setroom = sub.add_parser("set-room", help="改房间名称并重绘名称文字")
    p_setroom.add_argument("path")
    p_setroom.add_argument("id")
    p_setroom.add_argument("--name", required=True, help="新名称（空串表示清空）")

    p_rooms = sub.add_parser("rooms", help="房间汇总：面积/周长/墙环，可导出 CSV 或插入图上表格")
    p_rooms.add_argument("path")
    p_rooms.add_argument("--csv", default=None, help="导出 CSV 路径（UTF-8 BOM）")
    p_rooms.add_argument("--table", default=None, help="在图上插入表格，给左下角 x,y")
    p_rooms.add_argument("--title", default="房间面积表")

    p_sheet = sub.add_parser("sheet", help="图框 + 标题栏（GB/T 14689 幅面），默认自动居中排图")
    p_sheet.add_argument("path")
    p_sheet.add_argument("id", nargs="?", default="S001")
    p_sheet.add_argument("--size", default="A3", choices=list("AUTO A0 A1 A2 A3 A4".split()))
    p_sheet.add_argument("--scale", type=float, default=None,
                         help="比例分母（1:100 填 100）；省略则读图档比例标记")
    p_sheet.add_argument("--at", default=None, help="图幅左下角 x,y；省略则按图形外廓自动排图")
    p_sheet.add_argument("--margin", type=float, default=1500.0, help="自动排图时图形到内框的留白")
    p_sheet.add_argument("--project", default="")
    p_sheet.add_argument("--drawing", default="")
    p_sheet.add_argument("--no", dest="number", default="", help="图号")
    p_sheet.add_argument("--date", default="")
    p_sheet.add_argument("--design", default="")
    p_sheet.add_argument("--drawn", default="")
    p_sheet.add_argument("--check", default="")
    p_sheet.add_argument("--unit", default="")

    p_setsheet = sub.add_parser("set-sheet", help="改标题栏内容（保持图幅与位置重画）")
    p_setsheet.add_argument("path")
    p_setsheet.add_argument("id")
    for name in ("project", "drawing", "date", "design", "drawn", "check", "unit"):
        p_setsheet.add_argument("--%s" % name, default=None)
    p_setsheet.add_argument("--no", dest="number", default=None, help="图号")

    p_export = sub.add_parser("export", help="出图：按扩展名导出 png/svg/pdf，可按图幅范围裁切")
    p_export.add_argument("path")
    p_export.add_argument("--out", required=True, help="输出文件（.png / .svg / .pdf）")
    p_export.add_argument("--sheet", default=None, help="按图幅编号自动取窗口（推荐）")
    p_export.add_argument("--window", default=None, help="手工窗口 x0,y0,x1,y1")

    args = ap.parse_args(argv)

    try:
        if args.cmd == "layers" and not args.path:
            emit({"ok": True,
                  "layers": {k: {"name": LAYERS[k], **LAYER_STYLES[k]} for k in LAYERS}})
            return 0

        session = Session(args.path)
        if args.cmd == "new":
            session.new_metric(args.scale)
            emit({"ok": True, "path": str(session.path),
                  "scale": drawing_scale(session)})
            return 0
        if args.cmd == "scale":
            if args.set is None:
                emit({"ok": True, "scale": drawing_scale(session)})
            else:
                emit({"ok": True, **set_drawing_scale(
                    session, args.set, rescale=not args.no_rescale)})
            return 0

        if not session.path.exists():
            raise CadError("图纸不存在：%s" % session.path)

        if args.cmd == "axis":
            emit({"ok": True, **create_axis_grid(
                session, args.id, args.xcount, args.xspace,
                args.ycount, args.yspace, args.xstart, args.ystart, args.ext)})
        elif args.cmd == "layers":
            if args.fix:
                got = session.ensure_layers()
            else:
                got = layer_table(session.path)
            emit({"ok": True, "layers": got,
                  "spec": {k: {"name": LAYERS[k], **LAYER_STYLES[k]} for k in LAYERS}})
        elif args.cmd == "axis-auto":
            emit({"ok": True, **auto_axis(
                session, args.id, args.tol, args.ext, args.min_len)})
        elif args.cmd == "column":
            emit({"ok": True, **create_column(
                session, args.id, _pt(args.at), args.w, args.h,
                args.kind, args.angle, args.material)})
        elif args.cmd == "title":
            emit({"ok": True, **create_title_mark(
                session, args.id, _pt(args.at), args.name, args.scale or None)})
        elif args.cmd == "north":
            emit({"ok": True, **create_north_arrow(
                session, args.id, _pt(args.at), args.size)})
        elif args.cmd == "elev":
            emit({"ok": True, **create_elevation_mark(
                session, args.id, _pt(args.at),
                args.text if args.text else float(args.value))})
        elif args.cmd == "index":
            emit({"ok": True, **create_index_mark(
                session, args.id, _pt(args.at), args.detail, args.sheetno)})
        elif args.cmd == "section":
            emit({"ok": True, **create_section_mark(
                session, args.id, _pt(args.p1), _pt(args.p2), args.dir, args.no)})
        elif args.cmd == "audit":
            res = audit(session)
            emit({"ok": True, **res})
            if args.strict and res["errors"]:
                return 1
            return 0
        elif args.cmd == "rescale":
            emit({"ok": True, **rescale_annotations(
                session, args.scale, rebuild_dims=not args.no_dims)})
        elif args.cmd == "wall":
            res = create_wall(
                session, args.id, _pt(args.p1), _pt(args.p2),
                args.thick, args.kind, args.mat, args.ax1, args.ax2,
                snap_axis=args.snap_axis, snap_tol=args.snap_tol)
            # 画完墙立刻规整它自己与相邻墙的裁剪/合角
            res["normalized"] = normalize_around(session, args.id)
            emit({"ok": True, **res})
        elif args.cmd == "opening":
            emit({"ok": True, **create_opening(
                session, args.id, args.wall, args.kind,
                args.width, args.pos, args.height, args.sill,
                args.frame, args.no, args.label_side)})
        elif args.cmd == "room":
            if args.auto:
                emit({"ok": True, **auto_rooms(
                    session, args.prefix, args.name, args.min_area)})
            else:
                if not args.id or not args.walls:
                    raise CadError("room 需要给出房间编号与 --walls，或用 --auto 自动搜环")
                emit({"ok": True, **create_room(
                    session, args.id, _csv(args.walls), args.name,
                    show_area=not args.no_area)})
        elif args.cmd == "split":
            emit({"ok": True, **split_at_intersections(session)})
        elif args.cmd == "set-wall":
            emit({"ok": True, **set_wall(
                session, args.id, args.thick, args.kind, args.mat, args.ax1, args.ax2)})
        elif args.cmd == "set-opening":
            emit({"ok": True, **set_opening(
                session, args.id, args.pos, args.width,
                args.height, args.sill, args.kind, args.frame, args.no,
                args.label_side)})
        elif args.cmd == "merge":
            emit({"ok": True, **merge_walls(
                session, _csv(args.walls) or None)})
        elif args.cmd == "set-room":
            emit({"ok": True, **set_room(session, args.id, args.name)})
        elif args.cmd == "rooms":
            emit({"ok": True, **rooms_report(
                session, args.csv, _pt(args.table) if args.table else None, args.title)})
        elif args.cmd == "openings":
            emit({"ok": True, **openings_report(
                session, args.csv, _pt(args.table) if args.table else None, args.title)})
        elif args.cmd == "dim":
            emit({"ok": True, **annotate(
                session, args.opening_off, args.wall_off,
                exterior_only=not args.all_walls)})
        elif args.cmd == "sheet":
            emit({"ok": True, **create_sheet(
                session, args.id, args.size, args.scale,
                _pt(args.at) if args.at else None,
                args.project, args.drawing, args.number, args.date,
                args.design, args.drawn, args.check, args.unit, args.margin)})
        elif args.cmd == "set-sheet":
            emit({"ok": True, **set_sheet(
                session, args.id,
                project=args.project, drawing=args.drawing, number=args.number,
                date=args.date, design=args.design, drawn=args.drawn,
                check=args.check, unit=args.unit)})
        elif args.cmd == "export":
            win = None
            if args.window:
                win = [float(v) for v in args.window.split(",")]
            elif args.sheet:
                win = sheet_window(session, args.sheet)
            emit({"ok": True, **export(session, args.out, win)})
        elif args.cmd == "show":
            emit({"ok": True, "components": components_report(session)})
        return 0
    except CadError as e:
        emit({"ok": False, "error": str(e)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
