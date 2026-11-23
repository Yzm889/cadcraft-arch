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
import shutil
import sys
import time
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
    axis_grids,
    bind_walls_to_axis,
    auto_rooms,
    create_axis_grid,
    create_column,
    create_step,
    create_apron,
    create_site,
    read_site,
    create_stair,
    create_roof,
    create_roof_detail,
    read_roof_detail,
    audit,
    reconcile,
    verify,
    create_elevation,
    create_section,
    create_floor_table,
    create_opening_table,
    create_detail_mark,
    create_opening_detail,
    create_wall_node,
    create_stair_detail,
    create_elev_balcony,
    create_foundation,
    create_text,
    create_leader,
    create_wc_detail,
    read_detail_mark,
    read_opening_detail,
    read_stair_detail,
    read_elev_balcony,
    read_foundation,
    read_text,
    read_leader,
    read_wc_detail,
    read_wall_node,
    create_sheet_index,
    create_sheet_set,
    copy_floor,
    export_sheet_set,
    read_floors,
    read_opening_table,
    read_sheet_index,
    read_sheet_set,
    create_opening,
    create_room,
    create_wall,
    create_sheet,
    create_title_mark,
    create_north_arrow,
    rescale_annotations,
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
    set_drawing_scale,
    drawing_scale,
    wall_data,
)

SERVER_INFO = {"name": "cadcraft-arch", "version": "1.0.57"}
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
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径（.dxf）"},
                "scale": {"type": "number",
                           "description": "出图比例分母（1:100 填 100），给了就从开图起按该比例画注记"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_scale",
        "description": "查看/设定图档出图比例：先定比例，后续轴号/房间名/门窗编号/尺寸/图名/表格都按它取 mm 规格；已有注记默认整批重画。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "set": {"type": "number", "description": "设为新比例分母（1:50 填 50）；省略则只查询"},
                "rescale": {"type": "boolean", "description": "已有注记是否按新比例重画", "default": True},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_axis",
        "description": "生成轴网：xcount 道纵轴、ycount 道横轴。间距可统一给 xspace/yspace，"
                       "也可用 xspaces/yspaces 给每一段独立间距（如 Y 向 9600,3000,6600）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "轴网编号，如 AX001"},
                "xcount": {"type": "integer", "description": "纵轴根数（≥1）"},
                "xspace": {"type": "number", "description": "纵轴统一间距 mm；与 xspaces 二选一"},
                "xspaces": {"type": "array", "items": {"type": "number"},
                            "description": "纵轴逐段间距 mm，长度 = xcount-1"},
                "ycount": {"type": "integer", "description": "横轴根数（≥1）"},
                "yspace": {"type": "number", "description": "横轴统一间距 mm；与 yspaces 二选一"},
                "yspaces": {"type": "array", "items": {"type": "number"},
                            "description": "横轴逐段间距 mm，长度 = ycount-1"},
                "xstart": {"type": "number", "description": "纵轴起点 x", "default": 0},
                "ystart": {"type": "number", "description": "横轴起点 y", "default": 0},
                "ext": {"type": "number", "description": "轴线两端出头长度 mm", "default": 1000},
                "axis_h": {"type": "number",
                           "description": "轴号出图字高 mm（1:100 时 4.0 => 模型 400）",
                           "default": 3.0},
            },
            "required": ["path", "id", "xcount", "ycount"],
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
        "name": "aa_axis_bind",
        "description": "按现有轴网回填每堵墙的 AX1/AX2：横墙两个端点对应纵轴 1/2/3，"
                       "竖墙两个端点对应横轴 A/B/C；斜墙不套轴号。只改属性不改几何。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "grid": {"type": "string", "description": "轴网编号，默认用图上全部轴网"},
                "tol": {"type": "number", "description": "端点与轴的允许偏差 mm", "default": 50},
                "only_empty": {"type": "boolean", "description": "只填空的，不覆盖已有轴号",
                               "default": False},
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
                "snap_axis": {"type": "boolean", "description": "端点吸附到最近轴线（先轴后墙）",
                              "default": False},
                "snap_tol": {"type": "number", "description": "吸附允许距离 mm", "default": 300},
                "floor": {"type": "integer", "description": "所在层号（写 AA_FLOOR，门窗表按它归\"所在层\"）", "default": 1},
            },
            "required": ["path", "id", "p1", "p2"],
        },
    },
    {
        "name": "aa_column",
        "description": "柱：矩形柱实心填充 + 外框 / 圆柱圆 + 扇形填充，落在 AA-COLUMN 层，尺寸为真实尺寸（不随比例变）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "柱编号，如图纸内唯一 C1"},
                "at": {"type": "array", "items": {"type": "number"}, "description": "柱中心 [x, y]"},
                "w": {"type": "number", "description": "柱宽（圆柱时为直径）mm"},
                "h": {"type": "number", "description": "柱高 mm（默认同宽；圆柱忽略）"},
                "kind": {"type": "string", "enum": ["RECT", "CIRCLE"],
                         "description": "柱类型", "default": "RECT"},
                "angle": {"type": "number", "description": "矩形柱转角（度）", "default": 0},
                "material": {"type": "string", "description": "材料，如 C30", "default": ""},
            },
            "required": ["path", "id", "at", "w"],
        },
    },
    {
        "name": "aa_step",
        "description": "室外台阶：贴墙线不画，按踏步数/踏步宽画踏步线与两侧边线，落在 AA-STEP 层。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "台阶编号，图纸内唯一，如 ST1"},
                "at": {"type": "array", "items": {"type": "number"}, "description": "贴墙线中点 [x, y]"},
                "width": {"type": "number", "description": "台阶宽（沿墙向）mm"},
                "steps": {"type": "integer", "description": "踏步数", "default": 3},
                "tread": {"type": "number", "description": "踏步宽 mm", "default": 300},
                "angle": {"type": "number", "description": "外挑方向（度，270=-Y）", "default": 270},
                "rise": {"type": "number", "description": "单步高 mm（仅记录）", "default": 150},
            },
            "required": ["path", "id", "at", "width"],
        },
    },
    {
        "name": "aa_site",
        "description": "总平面：用地红线（闭合可回读）+ 建筑轮廓 + 道路 + 出入口标注 + 指北针 + 顶点坐标/总尺寸；只画示意，不替代实测红线。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "总平面编号，如图纸内唯一 SITE01"},
                "boundary": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
                             "description": "用地红线顶点 [[x,y], ...]，至少 3 点，世界坐标 mm"},
                "buildings": {"type": "array", "description": "建筑轮廓：{pts:[[x,y]...], name} 或 [x0,y0,x1,y1,名称]"},
                "roads": {"type": "array", "description": "道路：{width,pts:[[x,y]...]} 或 [宽度,[[x,y]...]]"},
                "entrances": {"type": "array", "description": "出入口：{at:[x,y],label,dir:[dx,dy]}，dir 为朝外方向"},
                "north": {"type": "array", "items": {"type": "number"}, "description": "指北针位置 [x, y]"},
                "coords": {"type": "boolean", "description": "是否注红线顶点坐标（米）", "default": True},
                "dims": {"type": "boolean", "description": "是否注总宽/总深尺寸", "default": True},
                "scale": {"type": "number", "description": "出图比例分母，默认读图档"},
                "at": {"type": "array", "items": {"type": "number"}, "description": "整体平移 [x, y]", "default": [0, 0]},
                "show": {"type": "string", "description": "只回读已有总平面编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_apron",
        "description": "散水：沿外墙外侧的等宽带，画外沿线 + 两端收头线，落在 AA-STEP 层。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "散水编号，如 SW1"},
                "at": {"type": "array", "items": {"type": "number"}, "description": "贴墙线中点 [x, y]"},
                "length": {"type": "number", "description": "沿墙长 mm"},
                "width": {"type": "number", "description": "外挑宽 mm", "default": 800},
                "angle": {"type": "number", "description": "外挑方向（度）", "default": 270},
            },
            "required": ["path", "id", "at", "length"],
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
                "label_side": {"type": "string", "enum": ["in", "out", "auto", "leader"],
                               "description": "编号所在侧：in=室内（默认）/ out=室外 / auto=沿用旧行为",
                               "default": "in"},
                "label_h": {"type": "number",
                            "description": "门窗编号出图字高 mm（1:100 时 2.5 => 模型 250）",
                            "default": 1.8},
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
                "show_area": {"type": "boolean",
                              "description": "名称下方是否注面积（天正默认注）", "default": True},
                "name_h": {"type": "number",
                           "description": "房间名出图字高 mm（1:100 时 3.5 => 模型 350）",
                           "default": 2.5},
                "area_h": {"type": "number",
                           "description": "面积出图字高 mm（1:100 时 2.5 => 模型 250）",
                           "default": 2.0},
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
                "name_h": {"type": "number", "description": "房间名出图字高 mm", "default": 2.5},
                "area_h": {"type": "number", "description": "面积出图字高 mm", "default": 2.0},
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
                "label_side": {"type": "string", "enum": ["in", "out", "auto", "leader"],
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
        "name": "aa_title",
        "description": "图名标注：图名（5mm@1:100）+ 比例（3.5mm）+ 图名下粗线 + 比例下细线（GB/T 50001 习惯）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "符号编号", "default": "T001"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "图名文字插入点 [x, y]"},
                "name": {"type": "string", "description": "图名文字，如 一层平面图"},
                "scale": {"type": "string", "description": "比例分母，如 100 表示 1:100；空串不注比例"},
            },
            "required": ["path", "at", "name"],
        },
    },
    {
        "name": "aa_north",
        "description": "指北针：细线圆 + 等腰三角指针，圆直径默认 2400（=24mm@1:100）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "符号编号", "default": "N001"},
                "at": {"type": "array", "items": {"type": "number"}, "description": "圆心 [x, y]"},
                "size": {"type": "number", "description": "圆直径（图元单位），默认 2400"},
            },
            "required": ["path", "at"],
        },
    },
    {
        "name": "aa_elev",
        "description": "标高符号：等腰直角三角（高 3mm）+ 数值（±0.000 / 3.600 / -0.450，m 三位小数）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "符号编号", "default": "E001"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "三角尖端 [x, y]（指向所注标高面）"},
                "value": {"type": "number", "description": "标高值（m），如 0 / 3.6 / -0.45"},
            },
            "required": ["path", "at", "value"],
        },
    },
    {
        "name": "aa_index",
        "description": "索引符号：直径 10mm 圆 + 水平直径线，上半详图编号、下半图号（同图写 —）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "符号编号", "default": "I001"},
                "at": {"type": "array", "items": {"type": "number"}, "description": "圆心 [x, y]"},
                "detail": {"type": "string", "description": "详图编号，如 1 或 5/1"},
                "sheetno": {"type": "string", "description": "图号（同一张图写 —）", "default": "—"},
            },
            "required": ["path", "at", "detail"],
        },
    },
    {
        "name": "aa_section",
        "description": "剖切符号：剖切位置线（粗线）+ 两端投射方向线（5mm）+ 编号 1-1。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "符号编号", "default": "S001"},
                "p1": {"type": "array", "items": {"type": "number"}, "description": "位置线起点 [x, y]"},
                "p2": {"type": "array", "items": {"type": "number"}, "description": "位置线终点 [x, y]"},
                "direction": {"type": "string", "enum": ["down", "up", "left", "right"],
                              "description": "投射方向（往哪边看）", "default": "down"},
                "no": {"type": "string", "description": "剖切编号", "default": "1"},
            },
            "required": ["path", "p1", "p2"],
        },
    },
    {
        "name": "aa_audit",
        "description": "图面自检（不改图）：墙端点没接上、门窗超出墙段、房间文字重叠、尺寸压轴号圈、图形超出图幅。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "tol": {"type": "number", "description": "判定容差 mm", "default": 1.0},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_reconcile",
        "description": "构件一致性检查：墙长/墙厚为 0、门窗宿主缺失或越界/重叠、房间面积与轮廓不符；fix=true 只修无歧义项（删零长空墙、重挂唯一可匹配的悬空门窗、夹回放得下的越界洞口、重建房间面积），墙厚 0/重叠/多候选等只返回 suggestion，不硬改。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "fix": {"type": "boolean", "description": "是否做无歧义自动收尾（零长空墙/悬空门窗/越界洞口/房间面积）", "default": False},
                "tol": {"type": "number", "description": "判定容差 mm", "default": 1.0},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_verify",
        "description": "全图复核（只读，不改图）：轴号重复/墙轴号引用、门窗表樘数与图上洞口、楼层表与立面/剖面楼层行、尺寸测量与三道尺寸链合计。缺表/缺轴网按未做跳过。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "tol": {"type": "number", "description": "判定容差 mm", "default": 1.0},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_rescale",
        "description": "换出图比例时整批重画注记：轴号圈/字高、房间名、门窗编号、图名、指北针按 mm 规格重算，尺寸标注删掉重画。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "scale": {"type": "number", "description": "新比例分母（1:50 填 50）"},
                "rebuild_dims": {"type": "boolean", "description": "是否重画尺寸标注", "default": True},
            },
            "required": ["path", "scale"],
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
                "size": {"type": "string", "enum": ["AUTO", "A0", "A1", "A2", "A3", "A4"],
                         "description": "图幅；AUTO = 按图形外廓自动选最小可容图幅", "default": "A3"},
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
    {
        "name": "aa_stair",
        "description": "楼梯：直跑 / 双跑 U 形（踏步线 + 梯段边线 + 上行箭头），落在 AA-STAIR 层；步数/宽/进深可回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "楼梯编号，如图纸内唯一 LT1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "起步踏步前缘中点 [x, y]"},
                "kind": {"type": "string", "enum": ["STRAIGHT", "DOGLEG"],
                         "description": "直跑 / 双跑 U 形", "default": "STRAIGHT"},
                "width": {"type": "number", "description": "单跑梯段宽 mm", "default": 1200},
                "steps": {"type": "integer", "description": "每跑踏步数（>=2）", "default": 10},
                "tread": {"type": "number", "description": "踏步宽 mm", "default": 280},
                "rise": {"type": "number", "description": "踏步高 mm", "default": 150},
                "well": {"type": "number", "description": "梯井宽 mm（双跑用）", "default": 120},
                "landing": {"type": "number", "description": "平台深 mm（双跑用）", "default": 1200},
                "angle": {"type": "number", "description": "上行方向（度，90=+Y）", "default": 90},
                "level": {"type": "string", "enum": ["FIRST", "MIDDLE", "TOP"],
                          "description": "层类型：首层 / 中层 / 顶层", "default": "MIDDLE"},
                "side": {"type": "string", "enum": ["LEFT", "RIGHT"],
                         "description": "上楼位置（双跑用）", "default": "LEFT"},
            },
            "required": ["path", "id", "at"],
        },
    },
    {
        "name": "aa_roof",
        "description": "屋顶平面：平屋顶（檐沟+四角雨水口+找坡）/ 双坡 / 四坡 / 单坡，檐口外挑计入平面面积；落 AA-ROOF 与 AA-ROOF-ARROW 层。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "屋顶编号，如图纸唯一 RF1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "屋面投影（建筑轮廓）左下角 [x, y]"},
                "kind": {"type": "string", "enum": ["FLAT", "GABLE", "HIP", "SHED"],
                         "description": "平屋顶 / 双坡 / 四坡 / 单坡", "default": "FLAT"},
                "width": {"type": "number", "description": "屋面宽 mm（沿 X）", "default": 6000},
                "depth": {"type": "number", "description": "屋面进深 mm（沿 Y）", "default": 4000},
                "overhang": {"type": "number", "description": "檐口外挑 mm", "default": 600},
                "gutter": {"type": "number", "description": "檐沟宽 mm", "default": 300},
                "ridge": {"type": "string", "enum": ["X", "Y"],
                          "description": "屋脊方向（坡屋顶用）", "default": "X"},
                "angle": {"type": "number", "description": "整体旋转（度）", "default": 0},
                "parapet": {"type": "number", "description": "女儿墙厚 mm（0=不画，只有平屋顶能画；画压顶外沿 + 墙内皮两条闭合矩形）", "default": 0},
                "hatch": {"type": "object", "description": "上人孔 {x, y, size}：x/y 是屋面坐标（相对 at），size 边长常见 700，画方框 + 对角斜线 + 注字",
                          "properties": {
                              "x": {"type": "number"},
                              "y": {"type": "number"},
                              "size": {"type": "number", "default": 700},
                          },
                          "required": ["x", "y"]},
            },
            "required": ["path", "id", "at"],
        },
    },
    {
        "name": "aa_roof_detail",
        "description": "屋面细部（M2）：在已有屋顶净区追加分格线 / 内天沟（带雨水口）/ 找坡箭头与 i=x% 注字，规格与图元数量可回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "屋面细部编号，图纸内唯一"},
                "roof": {"type": "string", "description": "源屋顶编号（AA_ROOF_<id>）"},
                "grid": {"type": "object", "description": "分格：{nx,ny} 分格数，或 {xspace,yspace} 分格间距 mm",
                         "properties": {"nx": {"type": "integer"},
                                        "ny": {"type": "integer"},
                                        "xspace": {"type": "number"},
                                        "yspace": {"type": "number"}}},
                "inner_gutter": {"type": "object", "description": "内天沟 {sides:['N','S','E','W'], width:mm}",
                                 "properties": {"sides": {"type": "array", "items": {"type": "string"}},
                                                "width": {"type": "number"}},
                                 "required": ["sides", "width"]},
                "slope": {"type": "number", "description": "坡度百分数，如 2 表示 i=2%"},
                "scale": {"type": "number", "description": "出图比例分母，默认读图档"},
                "show": {"type": "string", "description": "只回读已有屋面细部编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_elevation",
        "description": "建筑立面：按楼层数据 + 门窗生成地坪线/轮廓/楼层线/门窗/女儿墙或山墙/标高，顶层高可回读；供后续剖面复用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "立面编号，如图纸唯一 E1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "立面左端 ±0.000 地面点 [x, y]"},
                "width": {"type": "number", "description": "立面展开宽度 mm"},
                "floors": {"type": "array", "description": "自下而上每层 {height, elev?, no?, name?}",
                           "items": {"type": "object",
                                     "properties": {
                                         "height": {"type": "number", "description": "层高 mm"},
                                         "elev": {"type": "number", "description": "标高 mm，省略则累加"},
                                         "no": {"type": "string", "description": "层号"},
                                         "name": {"type": "string", "description": "层名"},
                                     },
                                     "required": ["height"]}},
                "openings": {"type": "array",
                             "description": "门窗 {floor(1起), x(左距), w, h, sill, kind: WINDOW/DOOR}",
                             "items": {"type": "object",
                                       "properties": {
                                           "floor": {"type": "integer", "default": 1},
                                           "x": {"type": "number"},
                                           "w": {"type": "number"},
                                           "h": {"type": "number"},
                                           "sill": {"type": "number", "default": 0},
                                           "kind": {"type": "string", "enum": ["WINDOW", "DOOR"],
                                                    "default": "WINDOW"},
                                       },
                                       "required": ["x", "w", "h"]}},
                "roof": {"type": "string", "enum": ["FLAT", "GABLE", "EAVE", "NONE"],
                         "description": "平屋顶（女儿墙+压顶）/ 双坡山墙视向（三角）/ 双坡正对檐口（檐口+屋脊）/ 不加", "default": "FLAT"},
                "parapet": {"type": "number", "description": "女儿墙高 mm", "default": 1200},
                "rise": {"type": "number", "description": "双坡脊高 mm", "default": 0},
                "overhang": {"type": "number", "description": "檐口外挑 mm", "default": 600},
                "marks": {"type": "boolean", "description": "是否注标高", "default": True},
                "angle": {"type": "number", "description": "整体旋转（度）", "default": 0},
                "wall": {"type": "string", "description": "从平面上这道墙（如 W001）读门窗并与 openings 合并，省得手抄坐标"},
                "flip": {"type": "boolean", "description": "该墙在平面上从右往左画（朝北的墙），窗口左边距需镜像", "default": False},
                "eave": {"type": "number", "description": "檐口板厚 mm（0=不画；FLAT 挑檐/GABLE/EAVE 画檐口线下的板底与两端封口）", "default": 0},
                "axes": {"type": "array",
                         "description": "立面轴号 [{x, label}]：x 为轴号在立面宽度上的位置，label 如 \"1\"/\"A\"；顶部画 8mm 圆 + 圈内3mm 字，圆下短引线接轮廓顶",
                         "items": {"type": "object",
                                   "properties": {
                                       "x": {"type": "number"},
                                       "label": {"type": "string"},
                                   },
                                   "required": ["x", "label"]}},
                "dims": {"type": "boolean", "description": "左侧注三道竖向尺寸（窗台/洞高、层高含女儿墙或脊高、总高），落 AA-DIM", "default": True},
            },
            "required": ["path", "id", "at", "width", "floors"],
        },
    },
    {
        "name": "aa_profile",
        "description": "建筑剖面：地坪 + 各层楼板（板顶/板底）+ 屋面板 + 外墙内皮 + 女儿墙或坡屋面 + 各层标高，顶层总高可回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "剖面编号，如图纸唯一 P1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "剖面左端室内地坪点 [x, y]"},
                "width": {"type": "number", "description": "剖面宽度 mm"},
                "floors": {"type": "array", "description": "自下而上每层 {height, elev?, no?, name?}",
                           "items": {"type": "object",
                                     "properties": {
                                         "height": {"type": "number"},
                                         "elev": {"type": "number"},
                                         "no": {"type": "string"},
                                         "name": {"type": "string"},
                                     },
                                     "required": ["height"]}},
                "openings": {"type": "array",
                             "description": "剖到的门窗 {floor, h, sill, kind, side?}：side 默认 LEFT",
                             "items": {"type": "object",
                                       "properties": {
                                           "floor": {"type": "integer", "default": 1},
                                           "h": {"type": "number", "description": "洞口高 mm"},
                                           "sill": {"type": "number", "default": 0},
                                           "kind": {"type": "string", "enum": ["WINDOW", "DOOR"],
                                                    "default": "WINDOW"},
                                           "side": {"type": "string", "enum": ["LEFT", "RIGHT"],
                                                    "default": "LEFT"},
                                       },
                                       "required": ["h"]}},
                "slab": {"type": "number", "description": "楼板厚 mm", "default": 100},
                "side": {"type": "string", "enum": ["BOTH", "LEFT", "RIGHT"],
                         "description": "BOTH 两端外墙都剖（默认）；LEFT/RIGHT 半剖，只在那一端画墙带", "default": "BOTH"},
                "inner_walls": {"type": "array",
                                "description": "被剖到的室内隔墙 {x, thick, openings?}，x 从剖面左端室内面起算",
                                "items": {"type": "object",
                                          "properties": {
                                              "x": {"type": "number"},
                                              "thick": {"type": "number", "default": 120},
                                              "openings": {
                                                  "type": "array",
                                                  "description": "该隔墙上被剖到的门窗 {floor, h, sill, kind}",
                                                  "items": {"type": "object",
                                                            "properties": {
                                                                "floor": {"type": "integer", "default": 1},
                                                                "h": {"type": "number"},
                                                                "sill": {"type": "number", "default": 0},
                                                                "kind": {"type": "string",
                                                                         "enum": ["WINDOW", "DOOR"],
                                                                         "default": "DOOR"},
                                                            },
                                                            "required": ["h"]}},
                                          },
                                          "required": ["x"]}},
                "beams": {"type": "array",
                          "description": "梁 {floor, x0, x1, h}，挂在那一层楼板底",
                          "items": {"type": "object",
                                    "properties": {"floor": {"type": "integer", "default": 2},
                                                   "x0": {"type": "number"},
                                                   "x1": {"type": "number"},
                                                   "h": {"type": "number", "default": 500}},
                                    "required": ["x0", "x1"]}},
                "stairs": {"type": "array",
                           "description": "楼梯断面 {floor, x0, x1, treads}：从 floor 层楼面爬到上一层",
                           "items": {"type": "object",
                                     "properties": {"floor": {"type": "integer", "default": 1},
                                                    "x0": {"type": "number"},
                                                    "x1": {"type": "number"},
                                                    "treads": {"type": "integer", "default": 10}},
                                     "required": ["x0", "x1"]}},
                "roof": {"type": "string", "enum": ["FLAT", "GABLE", "NONE"],
                         "description": "平屋顶 / 双坡 / 不加", "default": "FLAT"},
                "parapet": {"type": "number", "description": "女儿墙高 mm", "default": 1200},
                "rise": {"type": "number", "description": "双坡脊高 mm", "default": 0},
                "wall": {"type": "number", "description": "外墙厚 mm", "default": 240},
                "marks": {"type": "boolean", "description": "是否注标高", "default": True},
                "angle": {"type": "number", "description": "整体旋转（度）", "default": 0},
                "dims": {"type": "boolean", "description": "注尺寸：左侧三道竖向（洞口/层高/总高）+ 底部两道横向（墙厚净宽/总宽），落 AA-DIM", "default": True},
            },
            "required": ["path", "id", "at", "width", "floors"],
        },
    },
    {
        "name": "aa_floor_table",
        "description": "楼层表：写入各层层号/层高/平面图号/层名，起算标高自动累加，画成表并落成 FLOOR_TABLE 构件；立面、剖面后续据此生成。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "表编号，如图纸内唯一 FC1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "表格左上角 [x, y]"},
                "title": {"type": "string", "description": "表名", "default": "楼层表"},
                "floors": {
                    "type": "array",
                    "description": "自下而上每层一条：{no, height, plan, name, elev?}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "no": {"type": "string", "description": "层号，如 1、2、-1"},
                            "height": {"type": "number", "description": "层高 mm"},
                            "plan": {"type": "string", "description": "平面图号，如 建施-01"},
                            "name": {"type": "string", "description": "层名，如 首层"},
                            "elev": {"type": "number", "description": "标高 mm，省略则按层高累加"},
                        },
                        "required": ["height"],
                    },
                },
            },
            "required": ["path", "id", "at", "floors"],
        },
    },
    {
        "name": "aa_opening_table",
        "description": "门窗表：从图上洞口自动统计，按\"编号+类别+洞口宽高+窗台高\"归并，樘数取图上真实数量，所在层取洞口所在墙的 AA_FLOOR（连续写 1-3、不连续写 1,2）；画成表并落成 OPENING_TABLE 构件。只给 at 不建表时用 show 回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "表编号，如图纸内唯一 MC1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "表格左上角 [x, y]"},
                "title": {"type": "string", "description": "表名", "default": "门窗表"},
                "note": {"type": "string", "description": "表下附注（如\"门窗详见xx图集\"）"},
                "scale": {"type": "boolean", "description": "标题是否带出图比例", "default": True},
                "show": {"type": "string", "description": "只回读已有门窗表：给表编号，不回写"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_foundation",
        "description": "基础大放脚剖面（1:20）：以墙中心线与室外地面交点为锚点，墙身下到放脚顶，两侧对称逐级外放，底部垫层；注埋深与基底宽；落 AA_FD_<编号> 可回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "编号，如图纸内唯一 FD1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "墙中心线与室外地面交点 [x, y]"},
                "wall": {"type": "number", "description": "墙厚 mm", "default": 240},
                "steps": {"type": "integer", "description": "放脚级数", "default": 2},
                "step_h": {"type": "number", "description": "台阶高 mm（砖放脚 130）", "default": 130},
                "step_w": {"type": "number", "description": "台阶宽 mm（砖放脚 65）", "default": 65},
                "depth": {"type": "number", "description": "埋深 mm", "default": 2000},
                "base": {"type": "number", "description": "垫层厚 mm", "default": 300},
                "cover": {"type": "number", "description": "圈梁上砖覆盖 mm", "default": 50},
                "beam": {"type": "number", "description": "地圈梁高 mm（0 为不画）", "default": 250},
                "cushion_ext": {"type": "number", "description": "垫层每边外伸 mm", "default": 50},
                "stub": {"type": "number", "description": "±0.000 以上墙头高 mm（0 为不留）", "default": 100},
                "soil": {"type": "number", "description": "垫层底部 3:7 灰土厚 mm（0 为全 C10）", "default": 0},
                "lime_layer": {"type": "number", "description": "灰土分层厚 mm", "default": 150},
                "rebar": {"type": "boolean", "description": "是否画配筋示意", "default": True},
                "bars": {"type": "integer", "description": "圈梁纵筋根数（偶数）", "default": 6},
                "stirrup": {"type": "string", "description": "箍筋标注", "default": "Φ6@250"},
                "ratio": {"type": "number", "description": "详图比例分母", "default": 20},
                "factor": {"type": "number", "description": "直接给放大倍数"},
                "dims": {"type": "boolean", "description": "是否注尺寸", "default": True},
                "show": {"type": "string", "description": "只回读已有：给编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_text",
        "description": "单行注字：给左下角锚点、内容、图面字高与旋转角，落 AA_TXT_<编号> 可回读；用于门窗编号、材料做法等零星注字。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "注字编号，如图纸内唯一 T1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "文字左下角（基线左端）[x, y]"},
                "text": {"type": "string", "description": "注字内容"},
                "height": {"type": "number", "description": "图面字高 mm", "default": 3.5},
                "rotation": {"type": "number", "description": "旋转角（度，逆时针）", "default": 0},
                "show": {"type": "string", "description": "只回读已有：给编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_leader",
        "description": "引线注字：被注点引斜线（带箭头）到文字处，并画文字下水平横段；落 AA_LD_<编号> 可回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "引注编号，如图纸内唯一 L1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "被注点 [x, y]"},
                "text": {"type": "string", "description": "引注内容"},
                "to": {"type": "array", "items": {"type": "number"},
                       "description": "文字基线左端 [x, y]，缺省为被注点右上 10mm"},
                "height": {"type": "number", "description": "图面字高 mm", "default": 3.0},
                "shelf": {"type": "number", "description": "文字下横段长 mm", "default": 5.0},
                "show": {"type": "string", "description": "只回读已有：给编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_elev_balcony",
        "description": "立面上的阳台/雨篷：阳台画挑板+栏板（两侧竖线+压顶线），雨篷画挑板+两端牛腿；注阳台宽与栏板高（雨篷只注宽），挑出宽记属性；落 AA_EB_<编号> 可回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "编号，如图纸内唯一 EB1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "挑板板底左端 [x, y]"},
                "kind": {"type": "string", "enum": ["BALCONY", "AWNING"],
                         "description": "阳台或雨篷", "default": "BALCONY"},
                "width": {"type": "number", "description": "宽 mm", "default": 2400},
                "slab": {"type": "number", "description": "板厚 mm", "default": 100},
                "rail": {"type": "number", "description": "栏板高 mm", "default": 1000},
                "depth": {"type": "number", "description": "挑出宽 mm（只记属性）", "default": 1200},
                "dims": {"type": "boolean", "description": "是否注尺寸", "default": True},
                "show": {"type": "string", "description": "只回读已有：给编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_wc_detail",
        "description": "卫生间大样（1:20）：净空+墙厚+坐便/台盆/地漏+排水坡箭头（i=%），注开间/进深/坐便中心距三道尺寸；默认坐便靠上墙、台盆靠左墙、地漏右下内退 300，落 AA_WC_<编号> 可回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "大样编号，如图纸内唯一 WC1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "内净空左下角 [x, y]"},
                "w": {"type": "number", "description": "净宽 mm，默认 2400"},
                "h": {"type": "number", "description": "净深 mm，默认 1800"},
                "wall": {"type": "number", "description": "墙厚 mm，默认 120"},
                "slope": {"type": "number", "description": "排水坡度 %，默认 1"},
                "drain": {"type": "array", "items": {"type": "number"},
                          "description": "地漏 [x, y]，默认右下内退 300"},
                "ratio": {"type": "number", "description": "详图比例分母，默认 20", "default": 20},
                "factor": {"type": "number", "description": "直接给放大倍数"},
                "title": {"type": "string", "description": "图名"},
                "dims": {"type": "boolean", "description": "是否注尺寸", "default": True},
                "show": {"type": "string", "description": "只回读已有大样：给大样编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_stair_detail",
        "description": "楼梯间大样（1:20）：按图上已有楼梯（STRAIGHT/DOGLEG）的梯段宽/踏步数/踏步宽/梯井/平台深放大重画平面，直跑注梯段宽+踏步总长，双跑再加平台深；尺寸写真实 mm（含 10×280=2800），落 AA_SD_<编号> 可回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "大样编号，如图纸内唯一 SD1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "大样左下角 [x, y]（上行方向朝上）"},
                "stair": {"type": "string", "description": "源楼梯编号，如 ST1"},
                "ratio": {"type": "number", "description": "详图比例分母，默认 20", "default": 20},
                "factor": {"type": "number", "description": "直接给放大倍数"},
                "title": {"type": "string", "description": "图名"},
                "dims": {"type": "boolean", "description": "是否注尺寸", "default": True},
                "show": {"type": "string", "description": "只回读已有大样：给大样编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_wall_node",
        "description": "墙身节点（垂直剖面，1:20）：SILL=窗台节点（墙身/楼板/窗台板/窗框+墙厚与窗台高），PARAPET=女儿墙节点（墙身/屋面板/压顶+墙厚与女儿墙高）；只画结构轮廓与定位尺寸，不做材料分层。几何按出图比例/详图比例放大，注字不放大。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "节点编号，如图纸内唯一 WN1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "墙外皮与室内楼面交点 [x, y]"},
                "kind": {"type": "string", "enum": ["SILL", "PARAPET"],
                         "description": "SILL 窗台 / PARAPET 女儿墙", "default": "SILL"},
                "wall_thick": {"type": "number", "description": "墙厚 mm", "default": 240},
                "slab": {"type": "number", "description": "楼板/屋面板厚 mm", "default": 120},
                "sill": {"type": "number", "description": "窗台高 mm（SILL 用）", "default": 900},
                "parapet": {"type": "number", "description": "女儿墙高 mm（PARAPET 用）", "default": 1200},
                "cap": {"type": "number", "description": "压顶厚 mm", "default": 60},
                "cap_out": {"type": "number", "description": "压顶/窗台板挑出 mm", "default": 60},
                "ratio": {"type": "number", "description": "详图比例分母，默认 20", "default": 20},
                "factor": {"type": "number", "description": "直接给放大倍数"},
                "title": {"type": "string", "description": "图名"},
                "dims": {"type": "boolean", "description": "是否注尺寸", "default": True},
                "show": {"type": "string", "description": "只回读已有节点：给节点编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_detail_mark",
        "description": "详图符号（GB/T 50001）：直径 14mm 的圆 + 水平直径线，上半写详图编号、下半写图纸号（同图写 —）。与索引符号同画法，区别是直径与 AA_KIND=DETAIL_MARK。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "符号编号，如图纸内唯一 DM1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "圆心 [x, y]"},
                "detail": {"type": "string", "description": "详图编号，如 1"},
                "sheet": {"type": "string", "description": "详图所在图纸号；同一张图填 —", "default": "—"},
                "show": {"type": "string", "description": "只回读已有详图符号：给符号编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_opening_detail",
        "description": "门窗大样：从图上已画的洞口读宽高窗台高，按 --ratio（默认 1:20）放大重画一幅大样，含洞口/两侧墙垛/框/中梃/亮子/双扇/窗台板与洞口宽高尺寸，图名与比例画在块内；整块落 AA_OD_<编号>，属性回读源洞口与放大倍数。同编号多樘时须用具体洞口编号。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "大样编号，如图纸内唯一 OD1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "洞口左下角 [x, y]"},
                "opening": {"type": "string", "description": "源洞口编号，如 D001"},
                "no": {"type": "string", "description": "门窗编号，如 C1515；多樘时须改用 opening"},
                "ratio": {"type": "number", "description": "详图比例分母，默认 20（1:20）", "default": 20},
                "factor": {"type": "number", "description": "直接给放大倍数，省略按 出图比例/详图比例"},
                "wall_depth": {"type": "number", "description": "两侧墙垛厚度，默认 240", "default": 240},
                "title": {"type": "string", "description": "图名，省略用 编号+窗/门大样"},
                "dims": {"type": "boolean", "description": "是否注洞口宽高", "default": True},
                "show": {"type": "string", "description": "只回读已有大样：给大样编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_copy_floor",
        "description": "整层复制：把源层（按墙的 AA_FLOOR 过滤）的墙/门窗/房间按偏移复制到目标层，层号自动改写、门窗宿主墙与房间围合墙同步换号；目标层已有墙则拒绝叠图。楼梯/柱/台阶/散水暂不复制。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "from": {"type": "integer", "description": "源层层号"},
                "to": {"type": "integer", "description": "目标层层号"},
                "offset": {"type": "array", "items": {"type": "number"},
                           "description": "平移 [dx, dy]，把新层挪到另一处平面位置", "default": [0, 0]},
                "prefix": {"type": "string", "description": "新构件编号前缀（如 2 → 2W001）", "default": ""},
            },
            "required": ["path", "from", "to"],
        },
    },
    {
        "name": "aa_sheet_set",
        "description": "图纸集：登记每张图的\"图号 / 图名 / 图幅编号 / 备注\"，图幅与比例从图框读（不手填）；是图纸目录与批量出图的唯一数据源。图号重复、图幅被占用、图幅不存在都拒绝。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "图纸集编号，如图纸内唯一 SS1"},
                "items": {
                    "type": "array",
                    "description": "一张图一条：{no, name, sheet, note?}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "no": {"type": "string", "description": "图号，如 建施-01"},
                            "name": {"type": "string", "description": "图名，如 一层平面图"},
                            "sheet": {"type": "string", "description": "图幅编号（图上已有 AA_SHEET_<编号>）"},
                            "note": {"type": "string", "description": "备注"},
                        },
                        "required": ["no", "name", "sheet"],
                    },
                },
                "show": {"type": "string", "description": "只回读已有图纸集：给图纸集编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_sheet_index",
        "description": "图纸目录：按图纸集生成\"序号/图号/图名/图幅/比例/备注\"表，落 AA_TYPE=SHEET_INDEX 可回读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "图纸集编号"},
                "table": {"type": "string", "description": "目录表编号，默认 ML1"},
                "at": {"type": "array", "items": {"type": "number"},
                       "description": "表格左上角 [x, y]（建表必给）"},
                "title": {"type": "string", "description": "表名", "default": "图纸目录"},
                "note": {"type": "string", "description": "表下附注"},
                "show": {"type": "string", "description": "只回读已有目录：给表编号"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_export_set",
        "description": "批量出图：按图纸集逐张导出 PNG/SVG/PDF，一张图幅一个文件，命名\"图号_图名.扩展名\"；缺一张即整体报错并列已完成清单。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "id": {"type": "string", "description": "图纸集编号"},
                "outdir": {"type": "string", "description": "输出目录"},
                "fmt": {"type": "string", "enum": ["png", "svg", "pdf"], "default": "png"},
                "prefix": {"type": "string", "description": "文件名前缀，如 建施"},
            },
            "required": ["path", "id", "outdir"],
        },
    },
    {
        "name": "aa_batch",
        "description": "批量事务：按顺序执行多个工具调用，任一失败自动回滚到调用前的图纸状态（零残留），返回逐步结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径（各 op 未写 path 时默认用它）"},
                "ops": {
                    "type": "array",
                    "description": "调用列表，每项 {tool: 工具名, args: 参数对象}",
                    "items": {"type": "object"},
                },
                "rollback": {"type": "boolean", "description": "失败时是否回滚（默认 true）", "default": True},
            },
            "required": ["path", "ops"],
        },
    },
    {
        "name": "aa_checkpoint",
        "description": "检查点：把当前图纸存一份快照到同目录 .aa_snap/，返回可回退的 id。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "label": {"type": "string", "description": "快照标签（可读，如 before-stair）"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "aa_restore",
        "description": "回退到指定检查点（快照 id 或绝对路径），恢复为当时字节。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "图纸绝对路径"},
                "snapshot": {"type": "string", "description": "aa_checkpoint 返回的 id，或快照绝对路径"},
            },
            "required": ["path", "snapshot"],
        },
    },
]

TOOL_NAMES = [t["name"] for t in TOOLS]

SNAP_DIR = ".aa_snap"


def _snap_path(path: Path) -> Path:
    return path.parent / SNAP_DIR


def aa_checkpoint(path: str, label: str = "") -> dict[str, Any]:
    """把图纸复制一份到同目录 .aa_snap/，返回快照文件名（id）。"""
    p = Path(path)
    if not p.exists():
        raise CadError("检查点失败：图纸不存在（%s）" % p)
    d = _snap_path(p)
    d.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = "%s-%s" % (p.stem, stamp)
    if label:
        base += "-" + "".join(c for c in label if c.isalnum() or c in "-_")[:32]
    target = d / (base + ".dxf")
    n = 1
    while target.exists():
        n += 1
        target = d / ("%s-%d.dxf" % (base, n))
    shutil.copy2(p, target)
    return {"ok": True, "snapshot": str(target), "id": target.name,
            "bytes": target.stat().st_size}


def aa_restore(path: str, snapshot: str) -> dict[str, Any]:
    """把快照复制回图纸路径（字节级还原）。"""
    p = Path(path)
    snap = Path(snapshot)
    if not snap.is_absolute():
        snap = _snap_path(p) / snapshot
    if not snap.exists():
        raise CadError("回退失败：快照不存在（%s）" % snap)
    before = p.stat().st_mtime if p.exists() else None
    shutil.copy2(snap, p)
    return {"ok": True, "path": str(p), "snapshot": str(snap),
            "bytes": p.stat().st_size, "mtime_before": before}


def aa_batch(path: str, ops: list[dict[str, Any]], rollback: bool = True) -> dict[str, Any]:
    """在一个事务里顺序执行多个工具调用；任一失败则回滚到调用前（零残留）。

    第 i 项失败时返回 {"ok": False, failed_index, failed_tool, done}，
    图纸恢复为调用前的字节；前面的成功调用不进结果。
    """
    p = Path(path)
    backup = p.read_bytes() if p.exists() else None
    done = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict) or not op.get("tool"):
            raise CadError("batch 第 %d 项格式错误：需要 {tool, args}" % i)
        tool = op["tool"]
        args = dict(op.get("args") or {})
        args.setdefault("path", str(p))
        try:
            res = call_tool(tool, args)
        except Exception as exc:
            if rollback:
                if backup is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(backup)
            return {"ok": False, "failed_index": i, "failed_tool": tool,
                    "error": "%s: %s" % (type(exc).__name__, exc),
                    "done": len(done), "rolled_back": bool(rollback)}
        done.append({"index": i, "tool": tool, "result": res})
    return {"ok": True, "done": len(done), "results": done}


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
        s.new_metric(_num(a["scale"], "scale") if a.get("scale") else None)
        return {"ok": True, "path": str(s.path), "units": "mm",
                "scale": drawing_scale(s)}

    # 会话必须在使用 s 的所有工具分支之前建好；旧版在这里漏了，
    # 导致 aa_stair/aa_roof 等早期分支直接 UnboundLocalError。
    s = _session(path)

    if name == "aa_stair":
        return {"ok": True, **create_stair(
            s, a["id"], _pt(a["at"], "at"), a.get("kind", "STRAIGHT"),
            _num(a.get("width", 1200), "width"),
            int(_num(a.get("steps", 10), "steps")), _num(a.get("tread", 280), "tread"),
            _num(a.get("rise", 150), "rise"), _num(a.get("well", 120), "well"),
            _num(a.get("landing", 1200), "landing"), _num(a.get("angle", 90.0), "angle"),
            a.get("level", "MIDDLE"), a.get("side", "LEFT"))}

    if name == "aa_roof":
        return {"ok": True, **create_roof(
            s, a["id"], _pt(a["at"], "at"), a.get("kind", "FLAT"),
            _num(a.get("width", 6000), "width"), _num(a.get("depth", 4000), "depth"),
            _num(a.get("overhang", 600), "overhang"), _num(a.get("gutter", 300), "gutter"),
            a.get("ridge", "X"), _num(a.get("angle", 0.0), "angle"),
            _num(a.get("parapet", 0), "parapet"), a.get("hatch") or {})}

    if name == "aa_roof_detail":
        if a.get("show"):
            return {"ok": True, **read_roof_detail(s, a["show"])}
        if not a.get("roof"):
            raise CadError("屋面细部缺少 roof（源屋顶编号）")
        return {"ok": True, **create_roof_detail(
            s, a["id"], a["roof"], a.get("grid"), a.get("inner_gutter"),
            _num(a["slope"], "slope") if a.get("slope") is not None else None,
            _num(a["scale"], "scale") if a.get("scale") else None)}

    if name == "aa_elevation":
        return {"ok": True, **create_elevation(
            s, a["id"], _pt(a["at"], "at"), _num(a["width"], "width"),
            a["floors"], a.get("openings", []) or [], a.get("roof", "FLAT"),
            _num(a.get("parapet", 1200), "parapet"), _num(a.get("rise", 0), "rise"),
            _num(a.get("overhang", 600), "overhang"),
            bool(a.get("marks", True)), _num(a.get("angle", 0.0), "angle"),
            a.get("wall") or None, bool(a.get("flip", False)),
            _num(a.get("eave", 0), "eave"), a.get("axes", []) or [],
            bool(a.get("dims", True)))}

    if name == "aa_profile":
        return {"ok": True, **create_section(
            s, a["id"], _pt(a["at"], "at"), _num(a["width"], "width"),
            a["floors"], a.get("openings", []) or [], a.get("side", "BOTH"),
            _num(a.get("slab", 100), "slab"), a.get("roof", "FLAT"),
            _num(a.get("parapet", 1200), "parapet"), _num(a.get("rise", 0), "rise"),
            _num(a.get("wall", 240), "wall"), bool(a.get("marks", True)),
            _num(a.get("angle", 0.0), "angle"),
            a.get("inner_walls", []) or [], a.get("beams", []) or [],
            a.get("stairs", []) or [], bool(a.get("dims", True)))}

    if name == "aa_floor_table":
        return create_floor_table(s, a["id"], _pt(a["at"], "at"), a["floors"],
                                  a.get("title", "楼层表"))

    if name == "aa_opening_table":
        s = _session(a["path"])
        if a.get("show"):
            return {"ok": True, "rows": read_opening_table(s, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("门窗表需要 id 与 at（或用 show 回读已有表）")
        return create_opening_table(s, a["id"], _pt(a["at"], "at"),
                                    title=a.get("title", "门窗表"),
                                    scale=None if bool(a.get("scale", True)) else 0,
                                    note=a.get("note", ""))

    if name == "aa_text":
        sd = _session(path)
        if a.get("show"):
            return {"ok": True, **read_text(sd, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("注字需要 id 与 at（或用 show 回读）")
        return create_text(sd, a["id"], _pt(a["at"], "at"), a.get("text", ""),
                           _num(a.get("height", 3.5), "height"),
                           _num(a.get("rotation", 0), "rotation"))

    if name == "aa_leader":
        sd = _session(path)
        if a.get("show"):
            return {"ok": True, **read_leader(sd, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("引注需要 id 与 at（或用 show 回读）")
        return create_leader(sd, a["id"], _pt(a["at"], "at"), a.get("text", ""),
                             _pt(a["to"], "to") if a.get("to") else None,
                             _num(a.get("height", 3.0), "height"),
                             _num(a.get("shelf", 5.0), "shelf"))

    if name == "aa_foundation":
        sd = _session(path)
        if a.get("show"):
            return {"ok": True, **read_foundation(sd, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("基础需要 id 与 at（或用 show 回读）")
        return create_foundation(sd, a["id"], _pt(a["at"], "at"),
                                 _num(a.get("wall", 240), "wall"),
                                 int(a.get("steps", 2)),
                                 _num(a.get("step_h", 130), "step_h"),
                                 _num(a.get("step_w", 65), "step_w"),
                                 _num(a.get("depth", 2000), "depth"),
                                 _num(a.get("base", 300), "base"),
                                 _num(a.get("cover", 50), "cover"),
                                 _num(a.get("beam", 250), "beam"),
                                 _num(a.get("cushion_ext", 50), "cushion_ext"),
                                 _num(a.get("stub", 100), "stub"),
                                 _num(a.get("soil", 0), "soil"),
                                 _num(a.get("lime_layer", 150), "lime_layer"),
                                 bool(a.get("rebar", True)),
                                 int(a.get("bars", 6)),
                                 str(a.get("stirrup", "Φ6@250")),
                                 _num(a.get("ratio", 20), "ratio"), a.get("factor"),
                                 bool(a.get("dims", True)))

    if name == "aa_elev_balcony":
        sd = _session(path)
        if a.get("show"):
            return {"ok": True, **read_elev_balcony(sd, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("阳台/雨篷需要 id 与 at（或用 show 回读）")
        return create_elev_balcony(sd, a["id"], _pt(a["at"], "at"),
                                   _num(a.get("width", 2400), "width"),
                                   a.get("kind", "BALCONY"),
                                   _num(a.get("slab", 100), "slab"),
                                   _num(a.get("rail", 1000), "rail"),
                                   _num(a.get("depth", 1200), "depth"),
                                   bool(a.get("dims", True)))

    if name == "aa_wc_detail":
        sd = _session(path)
        if a.get("show"):
            return {"ok": True, **read_wc_detail(sd, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("卫生间大样需要 id 与 at（或用 show 回读）")
        return create_wc_detail(sd, a["id"], _pt(a["at"], "at"),
                                _num(a.get("w", 2400), "w"), _num(a.get("h", 1800), "h"),
                                _num(a.get("wall", 120), "wall"),
                                _num(a.get("slope", 1), "slope"),
                                _pt(a["drain"], "drain") if a.get("drain") else None,
                                _num(a.get("ratio", 20), "ratio"), a.get("factor"),
                                a.get("title"), bool(a.get("dims", True)))

    if name == "aa_stair_detail":
        sd = _session(path)
        if a.get("show"):
            return {"ok": True, **read_stair_detail(sd, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("楼梯大样需要 id 与 at（或用 show 回读）")
        return create_stair_detail(sd, a["id"], _pt(a["at"], "at"), a.get("stair"),
                                   _num(a.get("ratio", 20), "ratio"), a.get("factor"),
                                   a.get("title"), bool(a.get("dims", True)))

    if name == "aa_wall_node":
        wn = _session(path)
        if a.get("show"):
            return {"ok": True, **read_wall_node(wn, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("墙身节点需要 id 与 at（或用 show 回读）")
        return create_wall_node(wn, a["id"], _pt(a["at"], "at"),
                                a.get("kind", "SILL"),
                                _num(a.get("wall_thick", 240), "wall_thick"),
                                _num(a.get("slab", 120), "slab"),
                                _num(a.get("sill", 900), "sill"),
                                _num(a.get("parapet", 1200), "parapet"),
                                _num(a.get("cap", 60), "cap"),
                                _num(a.get("cap_out", 60), "cap_out"),
                                _num(a.get("ratio", 20), "ratio"),
                                a.get("factor"), a.get("title"),
                                bool(a.get("dims", True)))

    if name == "aa_detail_mark":
        dm = _session(path)
        if a.get("show"):
            return {"ok": True, **read_detail_mark(dm, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("详图符号需要 id 与 at（或用 show 回读）")
        return create_detail_mark(dm, a["id"], _pt(a["at"], "at"),
                                  a.get("detail", ""), a.get("sheet", "—"))

    if name == "aa_opening_detail":
        od = _session(path)
        if a.get("show"):
            return {"ok": True, **read_opening_detail(od, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("门窗大样需要 id 与 at（或用 show 回读）")
        return create_opening_detail(od, a["id"], _pt(a["at"], "at"),
                                     a.get("opening"), a.get("no"),
                                     _num(a.get("ratio", 20), "ratio"),
                                     a.get("factor"),
                                     _num(a.get("wall_depth", 240), "wall_depth"),
                                     a.get("title"), bool(a.get("dims", True)))

    if name == "aa_copy_floor":
        cf = _session(path)
        return copy_floor(cf, int(a["from"]), int(a["to"]),
                          a.get("offset", [0, 0]) or [0, 0], a.get("prefix", ""))

    if name == "aa_sheet_set":
        ss = _session(path)
        if a.get("show"):
            return {"ok": True, **read_sheet_set(ss, a["show"])}
        if not a.get("id") or not a.get("items"):
            return _err("图纸集需要 id 与 items（或用 show 回读）")
        return create_sheet_set(ss, a["id"], a["items"])

    if name == "aa_sheet_index":
        si = _session(path)
        if a.get("show"):
            return {"ok": True, "rows": read_sheet_index(si, a["show"])}
        if not a.get("id") or not a.get("at"):
            return _err("图纸目录需要 id 与 at（或用 show 回读）")
        return create_sheet_index(si, a["id"], a.get("table", "ML1"),
                                  _pt(a["at"], "at"), a.get("title", "图纸目录"),
                                  a.get("note", ""))

    if name == "aa_export_set":
        return export_sheet_set(_session(path), a["id"], a["outdir"],
                                a.get("fmt", "png"), a.get("prefix", ""))

    if name == "aa_batch":
        return aa_batch(path, a["ops"], bool(a.get("rollback", True)))

    if name == "aa_checkpoint":
        return aa_checkpoint(path, a.get("label", "") or "")

    if name == "aa_restore":
        return aa_restore(path, a["snapshot"])

    s = _session(path)

    if name == "aa_scale":
        if a.get("set") is None:
            return {"ok": True, "scale": drawing_scale(s)}
        return {"ok": True, **set_drawing_scale(
            s, _num(a["set"], "set"),
            rescale=bool(a.get("rescale", True)))}

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
        xsp = a.get("xspaces") if a.get("xspaces") is not None else a.get("xspace")
        ysp = a.get("yspaces") if a.get("yspaces") is not None else a.get("yspace")
        if xsp is not None and not isinstance(xsp, (int, float, list)):
            raise CadError("xspaces/xspace 必须是数字或数字数组")
        if ysp is not None and not isinstance(ysp, (int, float, list)):
            raise CadError("yspaces/yspace 必须是数字或数字数组")
        return {"ok": True, **create_axis_grid(
            s, a["id"], int(a["xcount"]), xsp,
            int(a["ycount"]), ysp,
            _num(a.get("xstart", 0), "xstart"), _num(a.get("ystart", 0), "ystart"),
            _num(a.get("ext", 1000), "ext"), text_h=_num(a.get("axis_h", 3.0), "axis_h"))}

    if name == "aa_axis_bind":
        return {"ok": True, **bind_walls_to_axis(
            s, a.get("grid"), _num(a.get("tol", 50), "tol"),
            bool(a.get("only_empty")))}

    if name == "aa_title":
        return {"ok": True, **create_title_mark(
            s, a.get("id", "T001"), _pt(a["at"], "at"), a["name"],
            a.get("scale") or None)}

    if name == "aa_north":
        return {"ok": True, **create_north_arrow(
            s, a.get("id", "N001"), _pt(a["at"], "at"),
            _opt(a.get("size")))}

    if name == "aa_elev":
        return {"ok": True, **create_elevation_mark(
            s, a.get("id", "E001"), _pt(a["at"], "at"), _num(a["value"], "value"))}

    if name == "aa_index":
        return {"ok": True, **create_index_mark(
            s, a.get("id", "I001"), _pt(a["at"], "at"),
            a["detail"], a.get("sheetno", "—"))}

    if name == "aa_section":
        return {"ok": True, **create_section_mark(
            s, a.get("id", "S001"), _pt(a["p1"], "p1"), _pt(a["p2"], "p2"),
            a.get("direction", "down"), a.get("no", "1"))}

    if name == "aa_audit":
        return {"ok": True, **audit(s, _num(a.get("tol", 1.0), "tol"))}

    if name == "aa_reconcile":
        return {"ok": True, **reconcile(
            s, fix=bool(a.get("fix", False)), tol=_num(a.get("tol", 1.0), "tol"))}

    if name == "aa_verify":
        return {"ok": True, **verify(s, tol=_num(a.get("tol", 1.0), "tol"))}

    if name == "aa_rescale":
        return {"ok": True, **rescale_annotations(
            s, _num(a["scale"], "scale"), bool(a.get("rebuild_dims", True)))}

    if name == "aa_wall":
        res = create_wall(
            s, a["id"], _pt(a["p1"], "p1"), _pt(a["p2"], "p2"),
            _num(a.get("thick", 240), "thick"), a.get("kind", "INTERNAL"),
            a.get("mat", ""), a.get("ax1", ""), a.get("ax2", ""),
            snap_axis=bool(a.get("snap_axis")),
            snap_tol=_num(a.get("snap_tol", 300), "snap_tol"),
            floor=int(a.get("floor", 1)))
        res["normalized"] = normalize_around(s, a["id"])
        return {"ok": True, **res}

    if name == "aa_column":
        return {"ok": True, **create_column(
            s, a["id"], _pt(a["at"], "at"), _num(a["w"], "w"),
            _opt(a.get("h")), a.get("kind", "RECT"),
            _num(a.get("angle", 0.0), "angle"), a.get("material", ""))}

    if name == "aa_step":
        return {"ok": True, **create_step(
            s, a["id"], _pt(a["at"], "at"), _num(a["width"], "width"),
            int(_num(a.get("steps", 3), "steps")), _num(a.get("tread", 300), "tread"),
            _num(a.get("angle", 270.0), "angle"), _num(a.get("rise", 150), "rise"))}

    if name == "aa_apron":
        return {"ok": True, **create_apron(
            s, a["id"], _pt(a["at"], "at"), _num(a["length"], "length"),
            _num(a.get("width", 800), "width"), _num(a.get("angle", 270.0), "angle"))}

    if name == "aa_site":
        if a.get("show"):
            return {"ok": True, **read_site(s, a["show"])}
        if not a.get("boundary"):
            raise CadError("总平面缺少 boundary（用地红线顶点）")
        return {"ok": True, **create_site(
            s, a["id"], a["boundary"], a.get("buildings") or [],
            a.get("roads") or [], a.get("entrances") or [],
            _pt(a["north"], "north") if a.get("north") else None,
            bool(a.get("coords", True)), bool(a.get("dims", True)),
            _num(a["scale"], "scale") if a.get("scale") else None,
            _pt(a.get("at") or [0, 0], "at"))}

    if name == "aa_opening":
        return {"ok": True, **create_opening(
            s, a["id"], a["wall"], a.get("kind", "DOOR"),
            _num(a["width"], "width"), _num(a["pos"], "pos"),
            _opt(a.get("height")), _num(a.get("sill", 0), "sill"),
            _num(a.get("frame", 60), "frame"), a.get("no", "") or "",
            a.get("label_side", "in") or "in",
            label_h=_num(a.get("label_h", 1.8), "label_h"))}

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
        return {"ok": True, **create_room(s, a["id"], list(walls), a.get("name", ""),
                                          show_area=bool(a.get("show_area", True)),
                                          name_h=_num(a.get("name_h", 2.5), "name_h"),
                                          area_h=_num(a.get("area_h", 2.0), "area_h"))}

    if name == "aa_room_auto":
        return {"ok": True, **auto_rooms(
            s, a.get("prefix", "R"), a.get("name", ""),
            _num(a.get("min_area", 1.0), "min_area"),
            name_h=_num(a.get("name_h", 2.5), "name_h"),
            area_h=_num(a.get("area_h", 2.0), "area_h"))}

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
            _num(a["scale"], "scale") if a.get("scale") else None,
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
        ok = bool(payload.get("ok", True)) if isinstance(payload, dict) else True
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
