"""cadcraft-arch 的 MCP 服务器：把原子指令暴露成标准 MCP 工具。

传输：stdio，newline-delimited JSON-RPC 2.0（MCP 规范；不是 LSP 的 Content-Length 头）。
入口：python tools/aa_mcp.py --serve        # 由 MCP 客户端以子进程方式拉起
自检：python tools/aa_mcp.py --selftest     # 打印工具表并退出

设计原则与 CLI 一致：
  - 每个工具只管一件事（new/axis/wall/opening/room/room_auto/split/merge/set_*/show）；
  - 工具返回值是**回读校验后的结构化结果**，不是"我以为画上了"；
  - 校验失败返回 isError=true + 具体原因，且图纸不留半成品。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    annotate,
    LAYERS,
    LAYER_STYLES,
    auto_axis,
    auto_rooms,
    create_axis_grid,
    create_opening,
    create_room,
    create_wall,
    create_sheet,
    export,
    layer_table,
    merge_walls,
    normalize_around,
    opening_data,
    openings_report,
    room_data,
    rooms_report,
    set_opening,
    set_room,
    set_sheet,
    set_wall,
    sheet_window,
    split_at_intersections,
    wall_data,
)

SERVER_INFO = {"name": "cadcraft-arch", "version": "0.9.0"}
PROTOCOL_VERSION = "2024-11-05"


def _num(v: Any, name: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise CadError("参数 %s 必须是数字（收到 %r）" % (name, v))


def _pt(v: Any, name: str) -> tuple[float, float]:
    if not isinstance(v, (list, tuple)) or len(v) < 2:
        raise CadError("参数 %s 必须是 [x, y]（收到 %r）" % (name, v))
    return (_num(v[0], name), _num(v[1], name))


def _opt(v: Any) -> float | None:
    return None if v in (None, "") else float(v)


def _session(path: str, must_exist: bool = True) -> Session:
    s = Session(Path(path))
    if must_exist and not s.path.exists():
        raise CadError("图纸不存在：%s" % s.path)
    return s


TOOLS: list[dict[str, Any]] = [
    {
        "name": "aa_new",
        "description": "新建公制建筑图纸（单位 mm）。已存在则报错，不覆盖。",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "图纸绝对路径（.dxf）"}},
            "required": ["path"],
        },
    },
    {
        "name": "aa_axis",
        "description": "生成轴网：xcount 道纵轴（间距 xspace）+ ycount 道横轴（间距 yspace），含轴号。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "轴网编号，如 AX001"},
                "xcount": {"type": "integer", "description": "纵轴根数（≥1）"},
                "xspace": {"type": "number", "description": "纵轴间距 mm"},
                "ycount": {"type": "integer", "description": "横轴根数（≥1）"},
                "yspace": {"type": "number", "description": "横轴间距 mm"},
                "xstart": {"type": "number", "description": "纵轴起点 x", "default": 0},
                "ystart": {"type": "number", "description": "横轴起点 y", "default": 0},
                "ext": {"type": "number", "description": "轴线两端出头长度 mm", "default": 1000},
            },
            "required": ["path", "id", "xcount", "xspace", "ycount", "yspace"],
        },
    },
    {
        "name": "aa_axis_auto",
        "description": "按现有墙段自动生成轴网：竖墙推纵向轴线（编 1/2/3），横墙推横向轴线（编 A/B/C），"
                       "同轴墙段按 tol 聚类，轴线两端外伸 ext；斜墙跳过并在 skipped 中返回。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "轴网编号，如 AX001", "default": "AX001"},
                "tol": {"type": "number", "description": "同一根轴上的墙段位置聚类容差 mm", "default": 50},
                "ext": {"type": "number", "description": "轴线端伸出最外轴的距离 mm", "default": 2400},
                "min_len": {"type": "number", "description": "忽略短于该长度的墙 mm", "default": 0},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_layers",
        "description": "查看/校正标准图层：轴线红点划线、墙体白粗线、门窗青细线、标注绿细线等；"
                       "fix=true 时缺层新建、颜色/线型/线宽不符就改，并回读校验。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "fix": {"type": "boolean", "description": "是否按标准校正并回读校验", "default": False},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_wall",
        "description": "画一堵墙（中心线 p1→p2）。画完自动与相邻墙做裁剪与转角合角，并回读校验。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "墙编号，图纸内唯一，如 W001"},
                "p1": {"type": "array", "items": {"type": "number"}, "description": "起点 [x, y]"},
                "p2": {"type": "array", "items": {"type": "number"}, "description": "终点 [x, y]"},
                "thick": {"type": "number", "description": "墙厚 mm", "default": 240},
                "kind": {"type": "string", "enum": ["EXTERNAL", "INTERNAL", "PARTITION"],
                         "description": "墙类型", "default": "INTERNAL"},
                "mat": {"type": "string", "description": "材质", "default": ""},
                "ax1": {"type": "string", "description": "关联轴号 1", "default": ""},
                "ax2": {"type": "string", "description": "关联轴号 2", "default": ""},
            },
            "required": ["path", "id", "p1", "p2"],
        },
    },
    {
        "name": "aa_opening",
        "description": "在墙上开门/窗：洞口区间在墙身真实开洞（墙面线断开只留垛线），门窗符号独立成块。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "门窗编号，如 D001 / C001"},
                "wall": {"type": "string", "description": "所属墙编号"},
                "kind": {"type": "string", "enum": ["DOOR", "WINDOW", "DOORWIN"], "default": "DOOR"},
                "width": {"type": "number", "description": "洞口宽度 mm"},
                "pos": {"type": "number", "description": "洞口中心到墙起点的距离 mm"},
                "height": {"type": "number", "description": "洞口高度 mm（可选）"},
                "sill": {"type": "number", "description": "窗台高 mm", "default": 0},
                "frame": {"type": "number", "description": "窗框厚 mm（构造尺寸，默认 60，可逐樘改）",
                          "default": 60},
                "no": {"type": "string", "description": "门窗编号，缺省按尺寸生成（M0921 / C1215）",
                       "default": ""},
                "label_side": {"type": "string", "enum": ["in", "out", "auto"],
                               "description": "编号所在侧：in=室内（默认）/ out=室外 / auto=沿用旧行为",
                               "default": "in"},
            },
            "required": ["path", "id", "wall", "width", "pos"],
        },
    },
    {
        "name": "aa_room",
        "description": "由显式墙环建房间：按环形顺序给墙编号，算净面积/周长并落房间名称。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "房间编号，如 R001"},
                "walls": {"type": "array", "items": {"type": "string"},
                          "description": "按环形顺序的墙编号"},
                "name": {"type": "string", "description": "房间名称（可空）", "default": ""},
            },
            "required": ["path", "id", "walls"],
        },
    },
    {
        "name": "aa_room_auto",
        "description": "自动搜房间：枚举全部闭合墙环（T 接/交叉自动打断，只用于搜索、不改图纸），逐个建房间并回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "prefix": {"type": "string", "description": "编号前缀", "default": "R"},
                "name": {"type": "string", "description": "统一名称（留空则用编号）", "default": ""},
                "min_area": {"type": "number", "description": "忽略的最小净面积 mm²", "default": 1.0},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_split",
        "description": "墙体相交自动切断：交点落在墙内部才切，T 形衔接/转角不切；门窗不跨切点。",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "图纸绝对路径"}},
            "required": ["path"],
        },
    },
    {
        "name": "aa_merge",
        "description": "合并共线相接的墙段（split 的逆操作）。省略 walls 则按 AA_ROOT 自动聚合。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "walls": {"type": "array", "items": {"type": "string"},
                          "description": "显式指定要合并的墙编号（可选）"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_set_wall",
        "description": "改墙参数（厚/类型/材质/轴号）后整体重建：墙线、洞口边线、邻墙裁剪同步更新，失败回滚。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "墙编号"},
                "thick": {"type": "number", "description": "新墙厚 mm"},
                "kind": {"type": "string", "enum": ["EXTERNAL", "INTERNAL", "PARTITION"]},
                "mat": {"type": "string", "description": "材质"},
                "ax1": {"type": "string", "description": "关联轴号 1"},
                "ax2": {"type": "string", "description": "关联轴号 2"},
            },
            "required": ["path", "id"],
        },
    },
    {
        "name": "aa_set_opening",
        "description": "改门窗参数（位置/宽度/高度/类型/窗框厚/编号）后重建符号并重排所属墙缺口；越界/重叠拒绝。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "门窗编号"},
                "pos": {"type": "number", "description": "洞口中心距墙起点 mm"},
                "width": {"type": "number", "description": "洞口宽度 mm"},
                "height": {"type": "number", "description": "洞口高度 mm"},
                "sill": {"type": "number", "description": "窗台高 mm"},
                "kind": {"type": "string", "enum": ["DOOR", "WINDOW", "DOORWIN"]},
                "frame": {"type": "number", "description": "窗框厚 mm"},
                "no": {"type": "string", "description": "门窗编号（空串表示按尺寸重算）"},
                "label_side": {"type": "string", "enum": ["in", "out", "auto"],
                               "description": "编号所在侧：in / out / auto"},
            },
            "required": ["path", "id"],
        },
    },
    {
        "name": "aa_openings",
        "description": "门窗表：同编号合并计数，列洞口宽高与所在墙，可导出 CSV 或在图上插表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "csv": {"type": "string", "description": "导出 CSV 路径（可选）"},
                "table_at": {"type": "array", "items": {"type": "number"},
                             "description": "在图上插入表格的左下角 [x, y]（可选）"},
                "title": {"type": "string", "description": "表标题", "default": "门窗表"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_dim",
        "description": "尺寸标注：外墙墙段长度标在外层、洞口宽在内层，落在 AA-DIM 层；重跑幂等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "opening_off": {"type": "number", "description": "洞口尺寸线离墙面距离", "default": 900},
                "wall_off": {"type": "number", "description": "墙段尺寸线离墙面距离", "default": 2000},
                "all_walls": {"type": "boolean", "description": "连内墙一起标（默认只标外墙）", "default": False},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_show",
        "description": "回读图纸全部构件：块参照、属性、几何量（墙长/角度/房间面积/周长）。",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "图纸绝对路径"}},
            "required": ["path"],
        },
    },
    {
        "name": "aa_set_room",
        "description": "改房间名称并重绘名称文字（按已存轮廓重建，面积不变；失败回滚、幂等）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "房间编号，如 R001"},
                "name": {"type": "string", "description": "新名称（空串表示清空）"},
            },
            "required": ["path", "id", "name"],
        },
    },
    {
        "name": "aa_rooms",
        "description": "房间汇总：按编号列面积/周长/围合墙，可导出 CSV，也可在图上插入表格。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "csv": {"type": "string", "description": "导出 CSV 路径（可选）"},
                "table_at": {"type": "array", "items": {"type": "number"},
                             "description": "在图上插入表格的左下角 [x, y]（可选）"},
                "title": {"type": "string", "description": "表标题", "default": "房间面积表"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_sheet",
        "description": "图框 + 标题栏：按 GB/T 14689 幅面绘制，标题栏 9 格；不给 at 时按图形外廓自动居中排图。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "图幅编号", "default": "S001"},
                "size": {"type": "string", "enum": ["A0", "A1", "A2", "A3", "A4"],
                         "description": "图幅", "default": "A3"},
                "scale": {"type": "number", "description": "比例分母（1:100 填 100）", "default": 100},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "图幅左下角 [x, y]；省略则自动排图"},
                "margin": {"type": "number", "description": "自动排图留白（模型单位）", "default": 1500},
                "project": {"type": "string", "description": "工程名称"},
                "drawing": {"type": "string", "description": "图名"},
                "number": {"type": "string", "description": "图号"},
                "date": {"type": "string", "description": "日期"},
                "design": {"type": "string", "description": "设计"},
                "drawn": {"type": "string", "description": "制图"},
                "check": {"type": "string", "description": "审核"},
                "unit": {"type": "string", "description": "单位"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_set_sheet",
        "description": "改标题栏内容：保持图幅/比例/位置重画，属性同步更新。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "图幅编号"},
                "project": {"type": "string"},
                "drawing": {"type": "string"},
                "number": {"type": "string"},
                "date": {"type": "string"},
                "design": {"type": "string"},
                "drawn": {"type": "string"},
                "check": {"type": "string"},
                "unit": {"type": "string"},
            },
            "required": ["path", "id"],
        },
    },
    {
        "name": "aa_export",
        "description": "出图：按扩展名导出 png/svg/pdf；给 sheet 则按图幅范围裁切，否则给 window。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "out": {"type": "string", "description": "输出文件（.png/.svg/.pdf）"},
                "sheet": {"type": "string", "description": "按图幅编号自动取导出窗口"},
                "window": {"type": "array", "items": {"type": "number"},
                           "description": "[x0, y0, x1, y1] 手工窗口"},
            },
            "required": ["path", "out"],
        },
    },
]

TOOL_NAMES = [t["name"] for t in TOOLS]


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """执行一个工具，返回 {"ok": bool, ...}。校验失败抛 CadError，由调用方转成结构化失败。"""
    if name not in TOOL_NAMES:
        raise CadError("未知工具：%s" % name)
    a = args or {}
    path = a.get("path")
    if not path:
        raise CadError("缺少参数 path（图纸绝对路径）")

    if name == "aa_new":
        s = _session(path, must_exist=False)
        if s.path.exists():
            raise CadError("拒绝新建：图纸已存在，不覆盖（%s）" % s.path)
        s.new_metric()
        return {"ok": True, "path": str(s.path), "units": "mm"}

    s = _session(path)

    if name == "aa_layers":
        if a.get("fix"):
            got = s.ensure_layers()
        else:
            got = layer_table(s.path)
        return {"ok": True, "layers": got,
                "spec": {k: {"name": LAYERS[k], **LAYER_STYLES[k]} for k in LAYERS}}

    if name == "aa_axis_auto":
        return {"ok": True, **auto_axis(
            s, a.get("id", "AX001"), _num(a.get("tol", 50), "tol"),
            _num(a.get("ext", 2400), "ext"), _num(a.get("min_len", 0), "min_len"))}

    if name == "aa_axis":
        return {"ok": True, **create_axis_grid(
            s, a["id"], int(a["xcount"]), _num(a["xspace"], "xspace"),
            int(a["ycount"]), _num(a["yspace"], "yspace"),
            _num(a.get("xstart", 0), "xstart"), _num(a.get("ystart", 0), "ystart"),
            _num(a.get("ext", 1000), "ext"))}

    if name == "aa_wall":
        res = create_wall(
            s, a["id"], _pt(a["p1"], "p1"), _pt(a["p2"], "p2"),
            _num(a.get("thick", 240), "thick"), a.get("kind", "INTERNAL"),
            a.get("mat", ""), a.get("ax1", ""), a.get("ax2", ""))
        res["normalized"] = normalize_around(s, a["id"])
        return {"ok": True, **res}

    if name == "aa_opening":
        return {"ok": True, **create_opening(
            s, a["id"], a["wall"], a.get("kind", "DOOR"),
            _num(a["width"], "width"), _num(a["pos"], "pos"),
            _opt(a.get("height")), _num(a.get("sill", 0), "sill"),
            _num(a.get("frame", 60), "frame"), a.get("no", "") or "",
            a.get("label_side", "in") or "in")}

    if name == "aa_openings":
        at = a.get("table_at")
        return {"ok": True, **openings_report(
            s, a.get("csv") or None,
            (float(at[0]), float(at[1])) if at else None,
            a.get("title") or "门窗表")}

    if name == "aa_dim":
        return {"ok": True, **annotate(
            s,
            float(a.get("opening_off") or 900.0),
            float(a.get("wall_off") or 2000.0),
            exterior_only=not bool(a.get("all_walls")),
        )}

    if name == "aa_room":
        walls = a["walls"]
        if isinstance(walls, str):
            walls = [x for x in walls.split(",") if x]
        return {"ok": True, **create_room(s, a["id"], list(walls), a.get("name", ""))}

    if name == "aa_room_auto":
        return {"ok": True, **auto_rooms(
            s, a.get("prefix", "R"), a.get("name", ""),
            _num(a.get("min_area", 1.0), "min_area"))}

    if name == "aa_split":
        return {"ok": True, **split_at_intersections(s)}

    if name == "aa_merge":
        walls = a.get("walls")
        if isinstance(walls, str):
            walls = [x for x in walls.split(",") if x]
        return {"ok": True, **merge_walls(s, list(walls) if walls else None)}

    if name == "aa_set_wall":
        return {"ok": True, **set_wall(
            s, a["id"],
            _opt(a.get("thick")), a.get("kind"), a.get("mat"),
            a.get("ax1"), a.get("ax2"))}

    if name == "aa_set_opening":
        return {"ok": True, **set_opening(
            s, a["id"],
            _opt(a.get("pos")), _opt(a.get("width")),
            _opt(a.get("height")), _opt(a.get("sill")), a.get("kind"),
            _opt(a.get("frame")), a.get("no"), a.get("label_side"))}

    if name == "aa_sheet":
        s = _session(path)
        return {"ok": True, **create_sheet(
            s, a.get("id", "S001") or "S001", a.get("size", "A3"),
            _num(a.get("scale", 100), "scale"),
            _pt(a["at"], "at") if a.get("at") else None,
            a.get("project", "") or "", a.get("drawing", "") or "",
            a.get("number", "") or "", a.get("date", "") or "",
            a.get("design", "") or "", a.get("drawn", "") or "",
            a.get("check", "") or "", a.get("unit", "") or "",
            _num(a.get("margin", 1500), "margin"))}

    if name == "aa_set_sheet":
        s = _session(path)
        fields = {k: a[k] for k in ("project", "drawing", "number", "date",
                                    "design", "drawn", "check", "unit") if k in a}
        return {"ok": True, **set_sheet(s, a["id"], **fields)}

    if name == "aa_export":
        s = _session(path)
        win = None
        if a.get("window"):
            win = [_num(v, "window") for v in a["window"]]
        elif a.get("sheet"):
            win = sheet_window(s, a["sheet"])
        return {"ok": True, **export(s, a["out"], win)}

    if name == "aa_show":
        return {"ok": True, "walls": wall_data(s), "openings": opening_data(s),
                "rooms": room_data(s)}

    if name == "aa_set_room":
        return {"ok": True, **set_room(s, a["id"], a["name"])}

    if name == "aa_rooms":
        at = a.get("table_at")
        return {"ok": True, **rooms_report(
            s, a.get("csv") or None,
            (float(at[0]), float(at[1])) if at else None,
            a.get("title") or "房间面积表")}

    raise CadError("未实现的工具：%s" % name)


def _tool_result(name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = call_tool(name, args)
        ok = True
    except CadError as exc:
        payload = {"ok": False, "error": str(exc)}
        ok = False
    except Exception as exc:  # 任何未预期错误也如实上报，不吞掉
        payload = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        ok = False
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": not ok}


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    """处理一条 JSON-RPC 消息。通知（无 id）返回 None。"""
    mid = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    is_notification = "id" not in request

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    try:
        if method == "initialize":
            return ok({"protocolVersion": PROTOCOL_VERSION,
                       "capabilities": {"tools": {"listChanged": False}},
                       "serverInfo": SERVER_INFO})
        if method in ("notifications/initialized", "initialized"):
            return None
        if method == "ping":
            return ok({})
        if method == "tools/list":
            return ok({"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name")
            if not name:
                return err(-32602, "tools/call 缺少 name")
            return ok(_tool_result(name, params.get("arguments") or {}))
        if is_notification:
            return None
        return err(-32601, "不支持的方法：%s" % method)
    except Exception as exc:
        return err(-32603, "服务器内部错误：%s" % exc)


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                     "error": {"code": -32700, "message": "解析失败：%s" % exc}},
                                    ensure_ascii=False) + "\n")
            stdout.flush()
            continue
        if not isinstance(req, dict):
            continue
        resp = handle(req)
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


def _selftest() -> int:
    init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    print("server:", init["result"]["serverInfo"])
    tools = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    print("tools:", len(tools), [t["name"] for t in tools])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="cadcraft-arch MCP 服务器（stdio）")
    ap.add_argument("--serve", action="store_true", help="以 stdio 方式提供服务（MCP 客户端用）")
    ap.add_argument("--selftest", action="store_true", help="打印工具表并退出")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
