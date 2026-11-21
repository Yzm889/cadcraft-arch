"""cadcraft-arch 的 CADCraft 驱动层。

职责边界（重要）：
- 几何数学、图元生成：CADCraft LISP（lisp/*.lisp）
- 块定义归集、块参照插入、属性读写：CADCraft 原生 JSON 命令
  （LISP 的 entmake 无法创建 ATTRIB/SEQEND，必须由 `insert` 带 attribs 落盘）
- 回读校验：`entities` / `info` / `eattext`

所有调用都走 cadcraft-cli 的无头模式，不弹任何对话框。
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

LISP_DIR = Path(__file__).resolve().parent.parent / "lisp"

# 转角合角判据的容差（mm）。墙方向由 atan 回算，端点会有 ~1e-5 mm 漂移，
# 用 1e-9 会把转角误判成"端点不在邻墙上"，导致漏合角。
CORNER_TOL = 0.01

# 图层名：默认按下表，但允许用户用 aa_layers.json 覆盖成自己图档的图层标准。
# 键与 LISP 侧 aa:*lay-* 变量一一对应。
DEFAULT_LAYERS = {
    "axis": "AA-AXIS",
    "axistext": "AA-AXISTEXT",
    "wall": "AA-WALL",
    "opening": "AA-OPENING",
    "room": "AA-ROOM",
    "dim": "AA-DIM",
    "border": "AA-BORDER",
    "sheet": "AA-SHEET",
    "title": "AA-TITLE",
    "table": "AA-TABLE",
    "name": "AA-NAME",
    "column": "AA-COLUMN",
    "step": "AA-STEP",
    "stair": "AA-STAIR",
    "stairarrow": "AA-STAIR-ARROW",
    "stairtext": "AA-STAIR-TEXT",
    "stairbreak": "AA-STAIR-BREAK",
    "roof": "AA-ROOF",
    "roofarrow": "AA-ROOF-ARROW",
    "elev": "AA-ELEV",
    "elevdetail": "AA-ELEV-DETAIL",
}
LAYERS = dict(DEFAULT_LAYERS)

# 各图层的标准线型 / 颜色（ACI）/ 线宽（mm），按 GB/T 50001 线宽组 + 天正默认配色：
# 轴线：红点划线；墙体：白（黑）实线、粗线 b=0.35；门窗：青细线；房间名：白细线；
# 尺寸：绿细线；图框：白粗线 0.70（图框线用最粗的 b 级）；标题栏内格：0.25；表格：0.18。
# 用户可在 aa_layers.json 里写成 {"axis": {"name": "AXIS", "color": 1,
# "linetype": "CENTER", "lineweight": 0.15}} 覆盖任意一项；只写字符串则沿用默认样式。
DEFAULT_LAYER_STYLES: dict[str, dict[str, Any]] = {
    "axis":     {"color": 1, "linetype": "CENTER", "lineweight": 0.15},
    "axistext": {"color": 1, "linetype": "Continuous", "lineweight": 0.15},
    "wall":     {"color": 7, "linetype": "Continuous", "lineweight": 0.35},
    "opening":  {"color": 4, "linetype": "Continuous", "lineweight": 0.18},
    "room":     {"color": 7, "linetype": "Continuous", "lineweight": 0.18},
    "dim":      {"color": 3, "linetype": "Continuous", "lineweight": 0.15},
    "border":   {"color": 7, "linetype": "Continuous", "lineweight": 0.15},
    "sheet":    {"color": 7, "linetype": "Continuous", "lineweight": 0.70},
    "title":    {"color": 7, "linetype": "Continuous", "lineweight": 0.25},
    "table":    {"color": 7, "linetype": "Continuous", "lineweight": 0.18},
    "name":     {"color": 7, "linetype": "Continuous", "lineweight": 0.25},
    "column":   {"color": 8, "linetype": "Continuous", "lineweight": 0.35},
    "step":     {"color": 7, "linetype": "Continuous", "lineweight": 0.18},
    "stair":    {"color": 2, "linetype": "Continuous", "lineweight": 0.18},
    "stairarrow": {"color": 3, "linetype": "Continuous", "lineweight": 0.18},
    "stairtext": {"color": 7, "linetype": "Continuous", "lineweight": 0.18},
    "stairbreak": {"color": 7, "linetype": "DASHED", "lineweight": 0.18},
    "roof":     {"color": 7, "linetype": "Continuous", "lineweight": 0.25},
    "roofarrow": {"color": 3, "linetype": "Continuous", "lineweight": 0.18},
    "elev":     {"color": 7, "linetype": "Continuous", "lineweight": 0.35},
    "elevdetail": {"color": 7, "linetype": "Continuous", "lineweight": 0.18},
}
LAYER_STYLES: dict[str, dict[str, Any]] = {
    k: dict(v) for k, v in DEFAULT_LAYER_STYLES.items()
}

# 颜色名 -> ACI（配置里可以写 "red"/"红"，也可以直接写 1）
COLOR_NAMES = {
    "red": 1, "yellow": 2, "green": 3, "cyan": 4, "blue": 5, "magenta": 6,
    "white": 7, "black": 7, "gray": 8, "grey": 8,
    "红": 1, "黄": 2, "绿": 3, "青": 4, "蓝": 5, "洋红": 6, "白": 7, "黑": 7, "灰": 8,
}


def parse_color(value: Any) -> int:
    """颜色写法归一：1..255 的 ACI 整数，或 "Red"/"red"/"红" 这类名字。"""
    if isinstance(value, bool):
        raise CadError("图层颜色不合法：%r" % (value,))
    if isinstance(value, int):
        if 1 <= value <= 255:
            return value
        raise CadError("图层颜色 ACI 应在 1..255：%r" % (value,))
    if isinstance(value, str):
        s = value.strip().lower()
        if s.isdigit():
            return parse_color(int(s))
        if s in COLOR_NAMES:
            return COLOR_NAMES[s]
    raise CadError("图层颜色不合法：%r" % (value,))


def load_layer_config(path: str | Path | None = None) -> dict:
    """读取图层配置（JSON，键同 DEFAULT_LAYERS），并更新模块级 LAYERS / LAYER_STYLES。

    值可以是字符串（只改层名，样式用默认），也可以是对象
    {"name": ..., "color": ..., "linetype": ..., "lineweight": ...}（任意字段可省）。
    查找顺序：显式 path > 环境变量 AA_LAYERS_FILE > 项目根 aa_layers.json。
    文件不存在则保持默认，不报错（图层标准是可选项）。
    """
    global LAYERS, LAYER_STYLES
    LAYERS = dict(DEFAULT_LAYERS)
    LAYER_STYLES = {k: dict(v) for k, v in DEFAULT_LAYER_STYLES.items()}
    cand = None
    if path:
        cand = Path(path)
    elif os.environ.get("AA_LAYERS_FILE"):
        cand = Path(os.environ["AA_LAYERS_FILE"])
    else:
        cand = Path(__file__).resolve().parent.parent / "aa_layers.json"
    if cand and Path(cand).exists():
        data = json.loads(Path(cand).read_text(encoding="utf-8-sig"))
        for k, v in data.items():
            if k not in DEFAULT_LAYERS:
                continue
            if isinstance(v, str) and v.strip():
                LAYERS[k] = v.strip()
            elif isinstance(v, dict):
                name = v.get("name")
                if isinstance(name, str) and name.strip():
                    LAYERS[k] = name.strip()
                style = LAYER_STYLES[k]
                if "color" in v:
                    style["color"] = parse_color(v["color"])
                if "linetype" in v and str(v["linetype"]).strip():
                    style["linetype"] = str(v["linetype"]).strip()
                if "lineweight" in v:
                    style["lineweight"] = float(v["lineweight"])
    return {"layers": dict(LAYERS),
            "styles": {k: dict(v) for k, v in LAYER_STYLES.items()}}


def layer_key_by_name(name: str) -> str | None:
    for k, v in LAYERS.items():
        if v == name:
            return k
    return None


def annot_size(mm: float, scale: float) -> float:
    """图上注写的 mm 尺寸 -> 图元单位。1:100 时 2.5mm 文字 = 250 图元单位。"""
    return float(mm) * float(scale)


def drawing_scale(session, fallback: float = 100.0) -> float:
    """当前图档的出图比例分母：优先 `AA_CFG_SCALE` 标记，其次图上 `AA_SHEET` 的 AA_SCALE，都没有按 100。

    `session.annot_scale` 可显式覆盖（rescale 等临时场景走这里），
    这样"先定比例再画"和"先画后套图框"两种顺序都成立。
    """
    forced = getattr(session, "annot_scale", None)
    if forced:
        return float(forced)
    cfg = cfg_scale(session)
    if cfg:
        return cfg
    for e in session.components("AA_SHEET_"):
        g = e["geometry"]
        attrs = {a["tag"]: a.get("text", {}).get("value", "")
                 for a in g.get("attribs", [])}
        if attrs.get("AA_TYPE") == "SHEET" and attrs.get("AA_SCALE"):
            try:
                return float(attrs["AA_SCALE"])
            except ValueError:
                break
    return float(fallback)


CFG_BLOCK = "AA_CFG_SCALE"


def cfg_scale(session) -> float | None:
    """读图档级比例标记（`AA_CFG_SCALE`），没有返回 None。"""
    ref = session.reference(CFG_BLOCK)
    if not ref:
        return None
    attrs = {a["tag"]: a.get("text", {}).get("value", "")
             for a in ref["geometry"].get("attribs", [])}
    try:
        return float(attrs.get("AA_SCALE") or 0) or None
    except ValueError:
        return None


def _write_cfg_scale(session, scale: float) -> str:
    """写/改图档级比例标记：只有一条不可见属性，不画几何。"""
    sc = "%.6g" % scale
    ref = session.reference(CFG_BLOCK)
    if ref:
        session.run([("attedit", {"handle": ref["handle"], "values": {"AA_SCALE": sc}})],
                    save=True)
        return ref["handle"]
    att = session.define_attributes([("AA_SCALE", "drawing scale 1:n", sc)])[0]
    session.make_block(CFG_BLOCK, (0.0, 0.0), [att])
    return session.insert(CFG_BLOCK, (0.0, 0.0), {"AA_SCALE": sc})


def set_drawing_scale(session, scale: float, rescale: bool = True) -> dict[str, Any]:
    """定/改出图比例（天正式"先定比例再画"）。

    - 比例写进 `AA_CFG_SCALE` 标记，**之后画的墙/门窗/房间/轴号/尺寸/图名/表格全部按它取 mm 规格**；
    - 图里已有注记时，默认按新比例整批重画（`rescale=False` 可只改标记）；
    - 图幅比例小于标记时提示（由 create_sheet 校验）。
    """
    sc = float(scale)
    if sc <= 0:
        raise CadError("比例必须为正数：%r" % (scale,))
    old = cfg_scale(session)
    if old is not None and abs(old - sc) < 1e-9:
        return {"scale": sc, "changed": 0, "rescaled": None}
    has_annot = bool(session.components("AA_AXGRID_") or session.components("AA_ROOM_")
                     or session.components("AA_OPENING_") or session.components("AA_SYM_")
                     or session.components("AA_TABLE_")
                     or session.components("AA_SHEET_"))
    res = rescale_annotations(session, sc) if (rescale and has_annot) else None
    handle = _write_cfg_scale(session, sc)
    return {"scale": sc, "changed": 1, "handle": handle, "rescaled": res}


load_layer_config()

_DEFAULT_CLI_CANDIDATES = [
    r"C:\Users\19891\AppData\Local\Programs\ArtCraft\CADCraft\cadcraft-cli.exe",
]


class CadError(RuntimeError):
    """CADCraft 调用失败或校验不通过。"""


def find_cli(explicit: str | None = None) -> str:
    """定位 cadcraft-cli，可用环境变量 CADCRAFT_CLI 覆盖。"""
    if explicit:
        return explicit
    env = os.environ.get("CADCRAFT_CLI")
    if env:
        return env
    found = shutil.which("cadcraft-cli")
    if found:
        return found
    for p in _DEFAULT_CLI_CANDIDATES:
        if Path(p).exists():
            return p
    raise CadError(
        "找不到 cadcraft-cli，请安装 CADCraft 或设置环境变量 CADCRAFT_CLI"
    )


@dataclass
class RunResult:
    raw: list[str]
    data: list[dict[str, Any]]

    def last(self) -> dict[str, Any]:
        if not self.data:
            raise CadError("命令未返回结果：%s" % self.raw)
        return self.data[-1]


class Session:
    """针对一张图纸的操作会话。"""

    def __init__(self, path: str | Path, cli: str | None = None):
        self.path = Path(path)
        self.cli = find_cli(cli)

    # ---------- 底层 ----------

    def _exec(self, argv: Sequence[str]) -> RunResult:
        proc = subprocess.run(
            [self.cli, *argv],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            raise CadError(
                "cadcraft-cli 失败 rc=%s\n%s" % (proc.returncode, proc.stderr.strip()[:800])
            )
        raw = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        data = []
        for ln in raw:
            try:
                data.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        return RunResult(raw=raw, data=data)

    def run(self, cmds: Iterable[tuple[str, dict]], save: bool = False) -> RunResult:
        argv = ["run", str(self.path)]
        for cid, params in cmds:
            argv += ["--cmd", "%s %s" % (cid, json.dumps(params, ensure_ascii=False))]
        if save:
            argv += ["--save", str(self.path), "--in-place"]
        return self._exec(argv)

    def new_metric(self, scale: float | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._exec(["run", "--metric", "--save", str(self.path)])
        if not self.path.exists():
            raise CadError("新建图纸失败：%s" % self.path)
        # 一开图就把标准层按 GB/天正规格建好（颜色、线型、线宽一次到位）
        self.ensure_layers()
        # 不给比例就走天正默认 1:100（缺省值在 drawing_scale 里），不必往图里塞标记块
        if scale:
            _write_cfg_scale(self, float(scale))

    # ---------- LISP ----------

    def lisp(self, code: str, libraries: Sequence[str] = ()) -> str:
        """执行一段 LISP，返回它的 prin1 值（字符串）。"""
        loads = "".join('(load "%s")' % str(LISP_DIR / lib).replace("\\", "/") for lib in libraries)
        # 用户图档自己的图层标准优先：覆盖 aa_core 里的默认层名
        sets = "".join(
            '(setq aa:*lay-%s* "%s")' % (k, LAYERS[k])
            for k in ("axis", "axistext", "wall", "opening", "room", "column", "step", "stair",
                      "stairarrow", "stairtext", "stairbreak", "roof", "roofarrow", "elev", "elevdetail", "sheet", "title", "table")
        )
        payload = loads + sets + code
        res = self.run([("lisp", {"code": payload})], save=True)
        last = res.last()
        if last.get("error"):
            raise CadError("LISP 执行失败：%s" % last["error"])
        value = str(last.get("value", ""))
        # prin1 会给字符串结果加引号，这里去掉外层引号
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        return value

    # ---------- 图层 / 块 / 插入 ----------

    def ensure_layers(self, names: Sequence[str] | None = None,
                      strict: bool = True) -> dict[str, dict[str, Any]]:
        """按标准自动建层：缺层就建，已存在但颜色/线型/线宽不对就改，最后回读校验。

        names 传层名（与 LAYERS 里的值对应）；不传则把整套 9 个标准层全部备齐。
        这样"画的时候层就是对的"，用户拿到图不用再手调层色。
        """
        names = list(names) if names is not None else [LAYERS[k] for k in LAYERS]
        spec: list[tuple[str, dict[str, Any]]] = []
        for n in names:
            key = layer_key_by_name(n)
            if key is None:
                # 用户自定义层名不在标准表里：只给个中性规格（白细实线），不猜标准
                spec.append((n, {"color": 7, "linetype": "Continuous",
                                 "lineweight": 0.18}))
            else:
                spec.append((LAYERS[key], dict(LAYER_STYLES[key])))
        if any(s["linetype"] != "Continuous" for _, s in spec):
            self.ensure_linetypes()          # 轴线要用 CENTER，新图档只带 Continuous

        table = layer_table(self.path) if self.path.exists() else {}
        cmds: list[tuple[str, dict[str, Any]]] = []
        for name, style in spec:
            color = parse_color(style["color"])
            lt = str(style["linetype"])
            lw = float(style["lineweight"])
            have = table.get(name)
            if have is None:
                cmds.append(("layer.new", {"name": name, "color": color,
                                           "linetype": lt, "lineweight": lw}))
            elif (have["color"] != color
                  or str(have["linetype"]).lower() != lt.lower()
                  or abs(float(have["lineweight"]) - lw) > 0.011):
                cmds.append(("layer.set", {"name": name, "color": color,
                                            "linetype": lt, "lineweight": lw}))
        if cmds:
            self.run(cmds, save=True)

        table = layer_table(self.path)
        bad = []
        for name, style in spec:
            have = table.get(name)
            if have is None:
                bad.append("%s 缺层" % name)
                continue
            if have["color"] != parse_color(style["color"]):
                bad.append("%s 颜色 %s≠%s" % (name, have["color"], style["color"]))
            if str(have["linetype"]).lower() != str(style["linetype"]).lower():
                bad.append("%s 线型 %s≠%s" % (name, have["linetype"], style["linetype"]))
            if abs(float(have["lineweight"]) - float(style["lineweight"])) > 0.011:
                bad.append("%s 线宽 %s≠%s" % (name, have["lineweight"], style["lineweight"]))
        if bad and strict:
            raise CadError("图层规格校验失败：" + "；".join(bad))
        return {name: table.get(name, {}) for name, _ in spec}

    def ensure_linetypes(self) -> None:
        """把 CADCraft 内置线型库加载进当前图档（幂等，只跑一次）。

        轴线要用点划线，而新建图档只带 Continuous；linetype 的 load 参数接受
        "*" 表示加载内置库全部线型（BORDER/CENTER/DASHDOT/...）。
        """
        if getattr(self, "_lt_loaded", False):
            return
        res = self.run([("linetype", {"load": "*"})], save=True)
        loaded = [x.get("name", "") for x in (res.last().get("loaded") or [])]
        if "CENTER" not in loaded:
            raise CadError("线型加载失败：图档里没有 CENTER 线型")
        self._lt_loaded = True

    def ensure_table_style(self, name: str = "AA-TABLE", text_height: float = 250.0,
                           margin: float = 60.0) -> None:
        """建/切一个表格样式：默认样式字高极小，直接插表会看不清。

        反复执行时把字高/边距刷成目标值（旧图档里 1.8mm 的样式会被就地修正），再切为当前样式。
        """
        if getattr(self, "_ts_ready", False):
            return
        self.run([("tablestyle", {"name": name, "textHeight": text_height,
                                  "margin": margin})], save=True)
        self.run([("tablestyle", {"name": name, "current": True})], save=True)
        self._ts_ready = True

    def ensure_dim_style(self, name: str = "AA-DIM", text_height: float = 250.0,
                         arrow_size: float = 150.0, ext_offset: float = 100.0) -> None:
        """建/切标注样式（幂等）。

        默认样式的字高与箭头极小，不建样式直接标注，图上只有一堆细短线。
        1:100 出图：字高 2.5mm => 250、箭头 1.5mm => 150、尺寸界线偏移 1mm => 100。
        规格每次调用都重设：换出图比例时，旧样式必须被就地改成新的字高/箭头，
        否则 1:50 的图上字还是按 1:100 配的，越看越小。
        """
        key = (name, float(text_height), float(arrow_size), float(ext_offset))
        if getattr(self, "_dim_key", None) == key:
            return
        self.run([("dimstyle", {"name": name, "textHeight": text_height,
                                "arrowSize": arrow_size,
                                "extOffset": ext_offset})], save=True)
        self.run([("dimstyle", {"name": name, "current": True})], save=True)
        self._dim_key = key

    def block_exists(self, name: str) -> bool:
        names = self.info().get("blocks", [])
        return name in names

    def define_attributes(
        self, specs: Sequence[tuple[str, str, str]]
    ) -> list[str]:
        """在模型空间创建不可见 ATTDEF，返回句柄。

        specs 为 (tag, prompt, default)。属性只做数据载体，
        一律 invisible，避免在图纸上产生文字噪音。
        """
        cmds = []
        for i, (tag, prompt, default) in enumerate(specs):
            cmds.append(
                (
                    "attdef",
                    {
                        "tag": tag,
                        "prompt": prompt,
                        "default": default,
                        "at": [0.0, -400.0 * (i + 1)],
                        "height": 200.0,
                        "invisible": True,
                    },
                )
            )
        res = self.run(cmds, save=True)
        handles = [r.get("handle") for r in res.data if r.get("handle")]
        if len(handles) != len(specs):
            raise CadError("属性定义失败：期望 %d 个，实际 %d 个" % (len(specs), len(handles)))
        return handles

    def make_block(self, name: str, base: tuple[float, float], handles: Sequence[str]) -> dict:
        if self.block_exists(name):
            raise CadError("块定义已存在：%s" % name)
        res = self.run(
            [("block", {"name": name, "base": list(base), "handles": list(handles), "keep": "delete"})],
            save=True,
        )
        return res.last()

    def insert(
        self,
        block: str,
        at: tuple[float, float],
        attribs: dict[str, str],
        rotation: float = 0.0,
        layer: str | None = None,
    ) -> str:
        params: dict[str, Any] = {
            "name": block,
            "at": [float(at[0]), float(at[1])],
            "rotation": float(rotation),
            "attribs": {k: str(v) for k, v in attribs.items()},
        }
        res = self.run([("insert", params)], save=True)
        handle = res.last().get("handle")
        if not handle:
            raise CadError("插入块参照失败：%s" % block)
        if layer:
            # insert 命令不接受 layer 参数，用 properties.set 回设
            self.run([("properties.set", {"handles": [handle], "layer": layer})], save=True)
        return handle

    # ---------- 回读 ----------

    def info(self) -> dict[str, Any]:
        proc = subprocess.run(
            [self.cli, "info", str(self.path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            raise CadError("info 失败：%s" % proc.stderr.strip()[:400])
        return json.loads(proc.stdout)

    def entities(self, **filters: Any) -> dict[str, Any]:
        params = {"limit": 10000}
        params.update(filters)
        return self.run([("entities", params)]).last()

    def snapshot(self) -> set[str]:
        """当前模型空间全部句柄快照，用于差分定位新建图元。"""
        return {e["handle"] for e in self.entities().get("entities", [])}

    def new_handles(self, before: set[str]) -> list[str]:
        """返回本次新建的句柄，按创建顺序（HANDLE 递增）排列。"""
        after = {e["handle"] for e in self.entities().get("entities", [])}
        fresh = after - before
        return sorted(fresh, key=lambda h: int(h, 16))

    def references(self) -> list[dict[str, Any]]:
        return self.entities(type="INSERT").get("entities", [])

    def reference(self, block: str) -> dict[str, Any] | None:
        for e in self.references():
            if e.get("geometry", {}).get("block") == block:
                return e
        return None

    def attributes(self, block: str) -> dict[str, str]:
        """回读某块参照的全部属性（tag -> value）。"""
        ref = self.reference(block)
        if not ref:
            return {}
        out = {}
        for a in ref["geometry"].get("attribs", []):
            out[a["tag"]] = a.get("text", {}).get("value", "")
        return out

    def components(self, prefix: str) -> list[dict[str, Any]]:
        """按块名前缀收集全部构件参照。"""
        out = []
        for e in self.references():
            if e.get("geometry", {}).get("block", "").startswith(prefix):
                out.append(e)
        return out

    def component_handle(self, prefix: str, ident: str) -> str | None:
        """按"块前缀 + 构件编号"取参照句柄（attedit 需要句柄）。"""
        target = prefix + ident
        for e in self.components(prefix):
            g = e["geometry"]
            attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in g.get("attribs", [])}
            if g["block"] == target or attrs.get("AA_ID") == ident:
                return e["handle"]
        return None

    # ---------- 断言 ----------

    def expect_attributes(self, block: str, expected: dict[str, str]) -> None:
        actual = self.attributes(block)
        if not actual:
            raise CadError("回读失败：找不到块参照 %s 或其属性为空" % block)
        diffs = []
        for k, v in expected.items():
            got = actual.get(k)
            if got is None:
                diffs.append("%s 缺失（实际：%s）" % (k, actual))
            elif str(got).strip() != str(v).strip():
                diffs.append("%s 期望 %r 实际 %r" % (k, v, got))
        if diffs:
            raise CadError("属性校验不通过：\n  " + "\n  ".join(diffs))


# ---------- 常用组合动作 ----------


def create_axis_grid(
    session: Session,
    grid_id: str,
    xcount: int,
    xspace: float,
    ycount: int,
    yspace: float,
    xstart: float = 0.0,
    ystart: float = 0.0,
    ext: float | None = None,
    scale: float | None = None,
) -> dict[str, Any]:
    """轴网：LISP 生成几何 -> block 归集 -> insert 带属性 -> 回读校验。

    轴号圈直径 8mm、字高 3mm、轴线外伸 24mm，按出图比例换算（1:100 => 800/300/2400）。
    """
    block = "AA_AXGRID_" + grid_id
    sc = float(scale) if scale else drawing_scale(session)
    if ext is None:
        ext = annot_size(24.0, sc)
    session.ensure_layers([LAYERS["axis"], LAYERS["axistext"]])
    session.ensure_linetypes()          # 轴线用 CENTER 点划线，先确保图档里有这个线型

    before = session.snapshot()
    value = session.lisp(
        "(progn (setq aa:*axis-r* %.4f) (setq aa:*axis-h* %.4f)"
        " (aa:axis \"%s\" %d %s %d %s %s %s %s))"
        % (annot_size(4.0, sc), annot_size(3.0, sc),
           grid_id, xcount, xspace, ycount, yspace, xstart, ystart, ext),
        libraries=("aa_core.lisp", "aa_axis.lisp"),
    )
    handles = session.new_handles(before)
    ver, hor = value.split("#")

    att_handles = session.define_attributes(
        [
            ("AA_TYPE", "component type", "AXGRID"),
            ("AA_ID", "component id", grid_id),
            ("AA_XCOUNT", "x axis count", str(xcount)),
            ("AA_YCOUNT", "y axis count", str(ycount)),
            ("AA_XSPACE", "x axis spacing", "%.4f" % float(xspace)),
            ("AA_YSPACE", "y axis spacing", "%.4f" % float(yspace)),
            ("AA_XSTART", "x origin", "%.4f" % float(xstart)),
            ("AA_YSTART", "y origin", "%.4f" % float(ystart)),
            ("AA_VER", "vertical labels", ver),
            ("AA_HOR", "horizontal labels", hor),
        ]
    )

    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(
        block,
        (0.0, 0.0),
        {
            "AA_TYPE": "AXGRID",
            "AA_ID": grid_id,
            "AA_XCOUNT": str(xcount),
            "AA_YCOUNT": str(ycount),
            "AA_XSPACE": "%.4f" % float(xspace),
            "AA_YSPACE": "%.4f" % float(yspace),
            "AA_XSTART": "%.4f" % float(xstart),
            "AA_YSTART": "%.4f" % float(ystart),
            "AA_VER": ver,
            "AA_HOR": hor,
        },
        layer=LAYERS["axis"],
    )
    session.expect_attributes(
        block,
        {
            "AA_ID": grid_id,
            "AA_TYPE": "AXGRID",
            "AA_XCOUNT": str(xcount),
            "AA_YCOUNT": str(ycount),
            "AA_VER": ver,
            "AA_HOR": hor,
        },
    )
    return {"block": block, "handle": handle, "ver": ver, "hor": hor, "geom_handles": handles}


def _axis_letters(n: int) -> list[str]:
    """轴号字母序列：A、B…Z、AA、AB…（跳过 I/O/Z 这类易混字符的国标做法暂不启用）。"""
    out = []
    for i in range(n):
        letters = ""
        k = i
        while True:
            letters = chr(ord("A") + k % 26) + letters
            k = k // 26 - 1
            if k < 0:
                break
        out.append(letters)
    return out


def _cluster(values: Sequence[float], tol: float) -> list[float]:
    """把位置按容差聚类，返回每簇的中心（处理"同一根轴上有两段墙但端点差几毫米"）。"""
    if not values:
        return []
    out: list[list[float]] = []
    for v in sorted(values):
        if out and abs(v - out[-1][-1]) <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


def auto_axis(
    session: Session,
    grid_id: str = "AX001",
    tol: float = 50.0,
    ext: float | None = None,
    min_len: float = 0.0,
    scale: float | None = None,
) -> dict[str, Any]:
    """按现有墙段自动生成轴网：竖墙 -> 纵向轴线（编 1、2、3…），横墙 -> 横向轴线（编 A、B、C…）。

    规则：
      · 只认正交墙（走向与 X/Y 轴夹角 ≤ 0.1°，可调 tol 只管位置聚类）；斜墙跳过并在结果里列出；
      · 同一根轴上的墙段按 `tol`（默认 50mm）合并成一根轴；
      · 轴线长度 = 最外侧轴线 ± `ext`；轴号圈贴在轴线端外侧，与端部相切；
      · 轴号编号：纵向自左向右 1、2、3…，横向自下向上 A、B、C…（GB/T 50001）；
      · 编号已存在同名的轴网块 -> 拒绝（换编号重来，避免两套轴线叠在一起）。
    """
    block = "AA_AXGRID_" + grid_id
    if session.block_exists(block):
        raise CadError("轴网 %s 已存在，请换编号（自动轴网不会覆盖已有轴网）" % grid_id)
    sc = float(scale) if scale else drawing_scale(session)
    if ext is None:
        ext = annot_size(24.0, sc)
    gap = annot_size(4.0, sc)          # 轴号圈与轴线端点的间隙 = 半径，保持相切
    # 天正常规：轴号圈与轴线端相切，圆占 ext→ext+8mm，所以尺寸外道（20mm）必须落在 ext 之内。
    ext_min = annot_size(20.0, sc) + annot_size(2.0, sc)
    ext_adjusted = None
    if ext < ext_min:
        ext_adjusted = round(ext_min, 3)
        ext = ext_min

    xs_raw: list[float] = []
    ys_raw: list[float] = []
    skipped: list[dict[str, Any]] = []
    for w in wall_data(session):
        if w["len"] < min_len:
            continue
        ang = w["rotation_rad"] % math.pi
        dx, dy = abs(math.cos(ang)), abs(math.sin(ang))
        if dy <= 1e-3:                      # 水平墙
            ys_raw.append(w["p1"][1])
        elif dx <= 1e-3:                    # 竖直墙
            xs_raw.append(w["p1"][0])
        else:
            skipped.append({"id": w["id"], "angle_deg": round(math.degrees(ang), 2)})

    xs = _cluster(xs_raw, tol)
    ys = _cluster(ys_raw, tol)
    if not xs and not ys:
        raise CadError("没有任何正交墙可用于生成轴网（斜墙 %d 段）" % len(skipped))

    ver = [str(i + 1) for i in range(len(xs))]
    hor = _axis_letters(len(ys))
    x0, x1 = (min(xs), max(xs)) if xs else (0.0, 0.0)
    y0, y1 = (min(ys), max(ys)) if ys else (0.0, 0.0)

    session.ensure_layers([LAYERS["axis"], LAYERS["axistext"]])
    session.ensure_linetypes()
    before = session.snapshot()
    body: list[str] = []
    for x, lab in zip(xs, ver):
        body.append('(aa:mkline-lt (list %.3f %.3f) (list %.3f %.3f) "%s" "CENTER")'
                    % (x, y0 - ext, x, y1 + ext, LAYERS["axis"]))
        body.append('(aa:axistag %.3f %.3f "%s")' % (x, y1 + ext + gap, lab))
    for y, lab in zip(ys, hor):
        body.append('(aa:mkline-lt (list %.3f %.3f) (list %.3f %.3f) "%s" "CENTER")'
                    % (x0 - ext, y, x1 + ext, y, LAYERS["axis"]))
        body.append('(aa:axistag %.3f %.3f "%s")' % (x0 - ext - gap, y, lab))
    session.lisp("(progn (setq aa:*axis-r* %.4f) (setq aa:*axis-h* %.4f) %s (princ \"ok\"))"
                 % (annot_size(4.0, sc), annot_size(3.0, sc), " ".join(body)),
                 libraries=("aa_core.lisp", "aa_axis.lisp"))
    handles = session.new_handles(before)

    def fmt(v: Sequence[float]) -> str:
        return ";".join("%.2f" % x for x in v)

    att_defs = [
        ("AA_TYPE", "component type", "AXGRID"),
        ("AA_ID", "component id", grid_id),
        ("AA_MODE", "grid mode", "AUTO"),
        ("AA_XCOUNT", "x axis count", str(len(xs))),
        ("AA_YCOUNT", "y axis count", str(len(ys))),
        ("AA_XPOS", "vertical axis positions", fmt(xs)),
        ("AA_YPOS", "horizontal axis positions", fmt(ys)),
        ("AA_VER", "vertical labels", ";".join(ver)),
        ("AA_HOR", "horizontal labels", ";".join(hor)),
        ("AA_SKIP", "skipped slanted walls", ";".join(s["id"] for s in skipped)),
    ]
    att_vals = {t: v for t, _d, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=LAYERS["axis"])
    session.expect_attributes(block, {"AA_ID": grid_id, "AA_TYPE": "AXGRID",
                                      "AA_VER": ";".join(ver), "AA_HOR": ";".join(hor)})

    # 回读：线数 / 圈数 / 轴号文字必须与推理结果一致
    geom = block_geometry(session.path, block)
    n_line = sum(1 for g in geom if g["type"] == "LINE")
    n_circ = sum(1 for g in geom if g["type"] == "CIRCLE")
    texts = [g["text"] for g in geom if g["type"] == "TEXT"]
    if n_line != len(xs) + len(ys) or n_circ != len(xs) + len(ys):
        raise CadError("轴网回读不符：线 %d / 圈 %d，期望 %d"
                       % (n_line, n_circ, len(xs) + len(ys)))
    if sorted(texts) != sorted(ver + hor):
        raise CadError("轴号回读不符：%s，期望 %s" % (texts, ver + hor))
    if not all(g["lt"] == "CENTER" for g in geom if g["type"] == "LINE"):
        raise CadError("轴线线型回读不符：应全部为 CENTER")

    bound = bind_walls_to_axis(session, grid_id=grid_id, tol=tol)

    return {
        "block": block,
        "handle": handle,
        "xpos": [round(v, 3) for v in xs],
        "ypos": [round(v, 3) for v in ys],
        "ver": ";".join(ver),
        "hor": ";".join(hor),
        "lines": n_line,
        "ext": round(ext, 3),
        "ext_adjusted": ext_adjusted,
        "skipped": skipped,
        "geom_handles": handles,
        "ax_bound": bound["bound"],
        "walls": bound["walls"],
    }


def axis_grids(session: Session) -> list[dict[str, Any]]:
    """读图上的全部轴网（自动/等距都算），返回轴位与编号序列。"""
    out = []
    for e in session.components("AA_AXGRID_"):
        g = e["geometry"]
        attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in g.get("attribs", [])}
        if attrs.get("AA_TYPE") != "AXGRID":
            continue
        xs = [float(v) for v in (attrs.get("AA_XPOS") or "").split(";") if v]
        ys = [float(v) for v in (attrs.get("AA_YPOS") or "").split(";") if v]
        if not xs or not ys:                       # 等距轴网没有 XPOS/YPOS，按间距还原
            x0 = float(attrs.get("AA_XSTART", "0") or 0)
            y0 = float(attrs.get("AA_YSTART", "0") or 0)
            xs = [x0 + i * float(attrs.get("AA_XSPACE", "0") or 0)
                  for i in range(int(attrs.get("AA_XCOUNT", "0") or 0))]
            ys = [y0 + i * float(attrs.get("AA_YSPACE", "0") or 0)
                  for i in range(int(attrs.get("AA_YCOUNT", "0") or 0))]
        out.append({
            "id": attrs.get("AA_ID", ""),
            "block": g["block"],
            "handle": e["handle"],
            "mode": attrs.get("AA_MODE", "EVEN"),
            "xpos": xs,
            "ypos": ys,
            "ver": [s for s in (attrs.get("AA_VER") or "").split(";") if s],
            "hor": [s for s in (attrs.get("AA_HOR") or "").split(";") if s],
        })
    return out


def _axis_label(value: float, positions: Sequence[float], labels: Sequence[str],
                tol: float) -> str:
    if not positions or not labels:
        return ""
    best_i, best_d = -1, None
    for i, p in enumerate(positions):
        d = abs(p - value)
        if best_d is None or d < best_d:
            best_i, best_d = i, d
    if best_d is not None and best_d <= tol and best_i < len(labels):
        return labels[best_i]
    return ""


def bind_walls_to_axis(session: Session, grid_id: str | None = None, tol: float = 50.0,
                       only_empty: bool = False) -> dict[str, Any]:
    """按轴网回填墙的 AA_AX1 / AA_AX2（墙起点/终点所在的轴线编号）。

    正交墙的端点一定落在"垂直于墙方向"的那组轴上：横墙的两个端点对应纵轴 1/2/3，
    竖墙的两个端点对应横轴 A/B/C。超出 tol 找不到轴就留空，不硬套编号。
    只改属性、不重建几何（用 attedit 就地写值），所以墙线、洞口、裁剪都不受影响。
    """
    grids = [g for g in axis_grids(session) if grid_id in (None, g["id"])]
    if not grids:
        raise CadError("图上没有轴网，无法回填墙轴号")
    updates: list[dict[str, Any]] = []
    for w in wall_data(session):
        ang = float(w["rotation_rad"])
        if abs(math.sin(ang)) <= 1e-3:
            horiz = True
        elif abs(math.cos(ang)) <= 1e-3:
            horiz = False
        else:
            continue                    # 斜墙不硬套轴号（如同 auto_axis 的做法）
        a1 = a2 = ""
        for g in grids:
            if horiz:
                l1 = _axis_label(w["p1"][0], g["xpos"], g["ver"], tol)
                l2 = _axis_label(w["p2"][0], g["xpos"], g["ver"], tol)
            else:
                l1 = _axis_label(w["p1"][1], g["ypos"], g["hor"], tol)
                l2 = _axis_label(w["p2"][1], g["ypos"], g["hor"], tol)
            if l1 or l2:
                a1, a2 = l1, l2
                break
        if only_empty and (w["ax1"] or w["ax2"]):
            continue
        if (a1, a2) == (w["ax1"], w["ax2"]):
            continue
        h = session.component_handle("AA_WALL_", w["id"])
        if not h:
            continue
        session.run([("attedit", {"handle": h, "values": {"AA_AX1": a1, "AA_AX2": a2}})],
                    save=True)
        updates.append({"wall": w["id"], "ax1": a1, "ax2": a2})
    return {"bound": len(updates), "walls": updates}


# ---------------- 图面符号：图名标注 / 指北针（v0.9.3） ----------------

def create_title_mark(
    session: Session,
    sym_id: str,
    at: tuple[float, float],
    name: str,
    scale: str | int | float | None = None,
    scale_denom: float | None = None,
) -> dict[str, Any]:
    """图名标注：图名 + 比例 + 图名下粗线 + 比例下细线（GB/T 50001 图名注写习惯）。

    `at` 是图名文字的插入点（左下角基线）；1:100 出图时图名 5mm、比例 3.5mm，
    图名线用图框线层（0.70 粗），比例下的线用图名层（0.25 细）。
    """
    if not name.strip():
        raise CadError("图名不能为空")
    block = "AA_SYM_" + sym_id
    if session.block_exists(block):
        raise CadError("符号 %s 已存在，请换编号" % sym_id)
    denom = scale_denom
    label = ""
    if isinstance(scale, str) and not scale.strip():
        denom = None                       # 显式留空：不注比例
    elif scale not in (None, ""):
        text = str(scale)
        denom = float(text.split(":")[-1]) if ":" in text else float(text)
        label = "1:%g" % denom
    else:
        denom = drawing_scale(session)      # 未给：跟图档比例走
        label = "1:%g" % denom
    sc = float(denom) if denom else drawing_scale(session)
    session.ensure_layers([LAYERS["name"], LAYERS["sheet"]])
    before = session.snapshot()
    session.lisp(
        "(progn (setq aa:*title-h* %.4f) (setq aa:*title-scale-h* %.4f)"
        " (setq aa:*name-h* %.4f) (setq aa:*title-base* %.4f) (setq aa:*title-gap* %.4f)"
        " (aa:title %.3f %.3f \"%s\" \"%s\"))"
        % (annot_size(5.0, sc), annot_size(3.5, sc), annot_size(3.5, sc),
           annot_size(2.5, sc), annot_size(4.0, sc),
           float(at[0]), float(at[1]), name.replace('"', "'"), label),
        libraries=("aa_core.lisp", "aa_symbol.lisp"),
    )
    handles = session.new_handles(before)
    if not handles:
        raise CadError("图名标注没有生成任何图元")
    sc = float(denom) if denom else drawing_scale(session)
    att_defs = [
        ("AA_TYPE", "component type", "TITLEMARK"),
        ("AA_ID", "component id", sym_id),
        ("AA_KIND", "symbol kind", "TITLE"),
        ("AA_TEXT", "title text", name),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=LAYERS["name"])
    session.expect_attributes(
        block, {"AA_TYPE": "TITLEMARK", "AA_ID": sym_id, "AA_TEXT": name}
    )
    return {"block": block, "handle": handle, "text": name, "scale": label,
            "scale_denom": sc, "geom_handles": handles}


def create_north_arrow(
    session: Session,
    sym_id: str,
    at: tuple[float, float],
    size: float | None = None,
    scale: float | None = None,
) -> dict[str, Any]:
    """指北针（GB/T 50001 习惯）：细线圆 + 指针，圆直径 24mm@出图比例。

    `size` 为图元单位（mm）；不传则按 24mm × 出图比例（1:100 => 2400）。
    """
    block = "AA_SYM_" + sym_id
    if session.block_exists(block):
        raise CadError("符号 %s 已存在，请换编号" % sym_id)
    sc = float(scale) if scale else drawing_scale(session)
    d = annot_size(24.0, sc) if size is None else float(size)
    if d <= 0:
        raise CadError("指北针直径必须为正：%r" % (size,))
    session.ensure_layers([LAYERS["name"]])
    before = session.snapshot()
    session.lisp(
        "(progn (setq aa:*name-h* %.4f) (aa:north %.3f %.3f %.3f))"
        % (annot_size(3.5, sc), float(at[0]), float(at[1]), d),
        libraries=("aa_core.lisp", "aa_symbol.lisp"),
    )
    handles = session.new_handles(before)
    if not handles:
        raise CadError("指北针没有生成任何图元")
    att_defs = [
        ("AA_TYPE", "component type", "TITLEMARK"),
        ("AA_ID", "component id", sym_id),
        ("AA_KIND", "symbol kind", "NORTH"),
        ("AA_R", "arrow radius", "%.3f" % (d / 2.0)),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=LAYERS["name"])
    session.expect_attributes(
        block, {"AA_TYPE": "TITLEMARK", "AA_ID": sym_id, "AA_KIND": "NORTH"}
    )
    return {"block": block, "handle": handle, "diameter": d, "geom_handles": handles}


def format_elevation(value: float) -> str:
    """标高数值写法（m，三位小数）：零写 ±0.000，负写 -0.450，正写 3.600。"""
    v = round(float(value), 3)
    if abs(v) < 1e-9:
        return "±0.000"
    return "%.3f" % v


def create_elevation_mark(
    session: Session,
    sym_id: str,
    at: tuple[float, float],
    value: float | str,
    scale: float | None = None,
) -> dict[str, Any]:
    """标高符号（GB/T 50001 习惯）：等腰直角三角高 3mm，尖端指向所注面，(x,y) 就是尖端。

    数字 2.5mm 写在三角右侧基线上方；`value` 传米制数值（如 3.6 / -0.45 / 0），
    文字由 `format_elevation` 统一成 `±0.000 / 3.600 / -0.450`。
    """
    block = "AA_SYM_" + sym_id
    if session.block_exists(block):
        raise CadError("符号 %s 已存在，请换编号" % sym_id)
    sc = float(scale) if scale else drawing_scale(session)
    text = value if isinstance(value, str) and value.strip() else format_elevation(float(value))
    h = annot_size(3.0, sc)
    session.ensure_layers([LAYERS["name"], LAYERS["sheet"]])
    before = session.snapshot()
    session.lisp(
        '(aa:elev %.3f %.3f "%s" %.4f %.4f)'
        % (float(at[0]), float(at[1]), text.replace('"', "'"),
           h, annot_size(2.5, sc)),
        libraries=("aa_core.lisp", "aa_symbol.lisp"),
    )
    handles = session.new_handles(before)
    if not handles:
        raise CadError("标高符号没有生成任何图元")
    att_defs = [
        ("AA_TYPE", "component type", "SYMBOL"),
        ("AA_ID", "component id", sym_id),
        ("AA_KIND", "symbol kind", "ELEV"),
        ("AA_VALUE", "elevation text", text),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
        ("AA_H", "triangle height", "%.4f" % h),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=LAYERS["name"])
    session.expect_attributes(block, {"AA_TYPE": "SYMBOL", "AA_KIND": "ELEV",
                                      "AA_VALUE": text})
    return {"block": block, "handle": handle, "kind": "ELEV", "value": text,
            "geom_handles": handles}


def create_index_mark(
    session: Session,
    sym_id: str,
    at: tuple[float, float],
    detail: str,
    sheetno: str = "—",
    scale: float | None = None,
) -> dict[str, Any]:
    """索引符号（GB/T 50001 习惯）：直径 10mm 圆 + 水平直径线，上半详图编号、下半图号。

    同一张图上的详图写成 "—"（GB 习惯）。
    """
    block = "AA_SYM_" + sym_id
    if session.block_exists(block):
        raise CadError("符号 %s 已存在，请换编号" % sym_id)
    if not str(detail).strip():
        raise CadError("索引符号必须给详图编号")
    sc = float(scale) if scale else drawing_scale(session)
    d = annot_size(10.0, sc)
    session.ensure_layers([LAYERS["name"]])
    before = session.snapshot()
    session.lisp(
        '(aa:idx %.3f %.3f %.4f "%s" "%s" %.4f)'
        % (float(at[0]), float(at[1]), d,
           str(detail).replace('"', "'"), str(sheetno).replace('"', "'"),
           annot_size(2.5, sc)),
        libraries=("aa_core.lisp", "aa_symbol.lisp"),
    )
    handles = session.new_handles(before)
    if not handles:
        raise CadError("索引符号没有生成任何图元")
    att_defs = [
        ("AA_TYPE", "component type", "SYMBOL"),
        ("AA_ID", "component id", sym_id),
        ("AA_KIND", "symbol kind", "INDEX"),
        ("AA_DETAIL", "detail no", str(detail)),
        ("AA_SHEETNO", "sheet no", str(sheetno)),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=LAYERS["name"])
    session.expect_attributes(block, {"AA_TYPE": "SYMBOL", "AA_KIND": "INDEX",
                                      "AA_DETAIL": str(detail)})
    return {"block": block, "handle": handle, "kind": "INDEX",
            "detail": str(detail), "sheetno": str(sheetno), "geom_handles": handles}


_SECTION_DIRS = {
    "down": (0.0, -1.0), "up": (0.0, 1.0),
    "left": (-1.0, 0.0), "right": (1.0, 0.0),
}


def create_section_mark(
    session: Session,
    sym_id: str,
    p1: tuple[float, float],
    p2: tuple[float, float],
    direction: str = "down",
    no: str = "1",
    scale: float | None = None,
) -> dict[str, Any]:
    """剖切符号（GB/T 50001）：剖切位置线只画两端两段粗线（6mm，不与图面线条相接），
    两端各一条垂直的投射方向线（5mm），编号 1-1 写在两条方向线端部。

    `p1`/`p2` 是剖切位置线的两个端点（落在建筑轮廓外一点），`direction` 是投射方向
    （朝哪边看）：down/up/left/right，方向线从两端往该方向画。
    """
    block = "AA_SYM_" + sym_id
    if session.block_exists(block):
        raise CadError("符号 %s 已存在，请换编号" % sym_id)
    if math.dist(tuple(p1), tuple(p2)) <= 1.0:
        raise CadError("剖切位置线两端点重合，无法画剖切符号")
    d = _SECTION_DIRS.get(str(direction).lower())
    if not d:
        raise CadError("剖切方向只能是 down/up/left/right：%r" % direction)
    sc = float(scale) if scale else drawing_scale(session)
    session.ensure_layers([LAYERS["name"], LAYERS["sheet"]])
    before = session.snapshot()
    session.lisp(
        '(aa:section %.3f %.3f %.3f %.3f %.1f %.1f "%s" %.4f %.4f %.4f)'
        % (float(p1[0]), float(p1[1]), float(p2[0]), float(p2[1]), d[0], d[1],
           str(no).replace('"', "'"), annot_size(6.0, sc), annot_size(5.0, sc),
           annot_size(2.5, sc)),
        libraries=("aa_core.lisp", "aa_symbol.lisp"),
    )
    handles = session.new_handles(before)
    if not handles:
        raise CadError("剖切符号没有生成任何图元")
    att_defs = [
        ("AA_TYPE", "component type", "SYMBOL"),
        ("AA_ID", "component id", sym_id),
        ("AA_KIND", "symbol kind", "SECTION"),
        ("AA_NO", "section no", str(no)),
        ("AA_DIRX", "look direction x", "%.1f" % d[0]),
        ("AA_DIRY", "look direction y", "%.1f" % d[1]),
        ("AA_X1", "cut line x1", "%.4f" % float(p1[0])),
        ("AA_Y1", "cut line y1", "%.4f" % float(p1[1])),
        ("AA_X2", "cut line x2", "%.4f" % float(p2[0])),
        ("AA_Y2", "cut line y2", "%.4f" % float(p2[1])),
        ("AA_SEG", "cut line segment", "%.4f" % annot_size(6.0, sc)),
        ("AA_ATX", "anchor x", "%.4f" % float(p1[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(p1[1])),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=LAYERS["name"])
    session.expect_attributes(block, {"AA_TYPE": "SYMBOL", "AA_KIND": "SECTION",
                                      "AA_NO": str(no)})
    return {"block": block, "handle": handle, "kind": "SECTION", "no": str(no),
            "direction": str(direction).lower(), "geom_handles": handles}


def _rebuild_axis_grid(session: Session, grid: dict[str, Any], scale: float) -> dict[str, Any]:
    """按新比例重画一套已有轴网（轴位与编号保持不变，只重算圈半径/字高/间隙）。"""
    block = grid["block"]
    if not delete_component(session, block):
        raise CadError("轴网 %s 不存在，无法重画" % grid["id"])
    xs, ys = grid["xpos"], grid["ypos"]
    if not xs or not ys:
        raise CadError("轴网 %s 缺少轴位数据，无法按比例重画" % grid["id"])
    ext = annot_size(24.0, scale)
    gap = annot_size(4.0, scale)
    session.ensure_layers([LAYERS["axis"], LAYERS["axistext"]])
    session.ensure_linetypes()
    before = session.snapshot()
    body = []
    for x, lab in zip(xs, grid["ver"]):
        body.append('(aa:mkline-lt (list %.3f %.3f) (list %.3f %.3f) "%s" "CENTER")'
                    % (x, min(ys) - ext, x, max(ys) + ext, LAYERS["axis"]))
        body.append('(aa:axistag %.3f %.3f "%s")' % (x, max(ys) + ext + gap, lab))
    for y, lab in zip(ys, grid["hor"]):
        body.append('(aa:mkline-lt (list %.3f %.3f) (list %.3f %.3f) "%s" "CENTER")'
                    % (min(xs) - ext, y, max(xs) + ext, y, LAYERS["axis"]))
        body.append('(aa:axistag %.3f %.3f "%s")' % (min(xs) - ext - gap, y, lab))
    session.lisp("(progn (setq aa:*axis-r* %.4f) (setq aa:*axis-h* %.4f) %s (princ \"ok\"))"
                 % (annot_size(4.0, scale), annot_size(3.0, scale), " ".join(body)),
                 libraries=("aa_core.lisp", "aa_axis.lisp"))
    handles = session.new_handles(before)

    att_defs = [
        ("AA_TYPE", "component type", "AXGRID"),
        ("AA_ID", "component id", grid["id"]),
        ("AA_MODE", "grid mode", grid["mode"]),
        ("AA_XCOUNT", "x axis count", str(len(xs))),
        ("AA_YCOUNT", "y axis count", str(len(ys))),
        ("AA_XPOS", "vertical axis positions", ";".join("%.2f" % v for v in xs)),
        ("AA_YPOS", "horizontal axis positions", ";".join("%.2f" % v for v in ys)),
        ("AA_VER", "vertical labels", ";".join(grid["ver"])),
        ("AA_HOR", "horizontal labels", ";".join(grid["hor"])),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=LAYERS["axis"])
    session.expect_attributes(block, {"AA_TYPE": "AXGRID", "AA_ID": grid["id"]})
    return {"grid": grid["id"], "lines": len(handles), "handle": handle}


def rescale_annotations(session: Session, scale: float,
                        rebuild_dims: bool = True) -> dict[str, Any]:
    """把图上所有"按 mm 出图"的注记整批改成新比例：轴号圈/轴号字、房间名、
    门窗编号、图名、指北针，以及尺寸标注（删掉重画）。

    做法是"删组件 -> 用原属性重画"，墙/门窗几何参数一个不改，只改字高与圈径。
    """
    sc = float(scale)
    if sc <= 0:
        raise CadError("比例必须为正数：%r" % (scale,))
    prev = getattr(session, "annot_scale", None)
    session.annot_scale = sc
    try:
        grids = [_rebuild_axis_grid(session, g, sc) for g in axis_grids(session)]

        openings = opening_data(session)
        for o in openings:
            delete_component(session, o["block"])
            create_opening(session, o["id"], o["wallid"], o["kind"],
                           o["width"], o["pos"], o["height"], o["sill"],
                           o["frame"], o["no"], o["labelside"])

        rooms = room_data(session)
        for r in rooms:
            delete_component(session, r["block"])
            create_room(session, r["id"], r["walls"], r["name"],
                        show_area=r.get("show_area", True))

        symbols = []
        for e in session.components("AA_SYM_"):
            g = e["geometry"]
            attrs = {a["tag"]: a.get("text", {}).get("value", "")
                     for a in g.get("attribs", [])}
            sym_id = attrs.get("AA_ID") or g["block"][len("AA_SYM_"):]
            at = ((float(attrs.get("AA_ATX", "0") or 0),
                   float(attrs.get("AA_ATY", "0") or 0))
                  if attrs.get("AA_ATX") else
                  (g["insert"]["x"], g["insert"]["y"]))
            delete_component(session, g["block"])
            if attrs.get("AA_KIND") == "NORTH":
                size = 2.0 * float(attrs.get("AA_R", "0") or 0)
                ratio = size / (24.0 * (prev or 100.0)) if prev else 1.0
                create_north_arrow(session, sym_id, at,
                                   size=24.0 * sc * ratio, scale=sc)
                symbols.append({"id": sym_id, "kind": "NORTH"})
            elif attrs.get("AA_KIND") == "TITLE":
                create_title_mark(session, sym_id, at,
                                  attrs.get("AA_TEXT", ""),
                                  scale=("%g" % sc) if attrs.get("AA_SCALE") else None)
                symbols.append({"id": sym_id, "kind": "TITLE"})
            elif attrs.get("AA_KIND") == "ELEV":
                create_elevation_mark(session, sym_id, at,
                                      attrs.get("AA_VALUE", "±0.000"), scale=sc)
                symbols.append({"id": sym_id, "kind": "ELEV"})
            elif attrs.get("AA_KIND") == "INDEX":
                create_index_mark(session, sym_id, at,
                                  attrs.get("AA_DETAIL", "1"),
                                  attrs.get("AA_SHEETNO", "—"), scale=sc)
                symbols.append({"id": sym_id, "kind": "INDEX"})
            elif attrs.get("AA_KIND") == "SECTION":
                d = (float(attrs.get("AA_DIRX", "0") or 0),
                     float(attrs.get("AA_DIRY", "-1") or -1))
                direction = next((k for k, v in _SECTION_DIRS.items()
                                  if (v[0], v[1]) == d), "down")
                create_section_mark(
                    session, sym_id,
                    (float(attrs.get("AA_X1", "0") or 0), float(attrs.get("AA_Y1", "0") or 0)),
                    (float(attrs.get("AA_X2", "0") or 0), float(attrs.get("AA_Y2", "0") or 0)),
                    direction=direction, no=attrs.get("AA_NO", "1"), scale=sc)
                symbols.append({"id": sym_id, "kind": "SECTION"})

        tables = []
        for e in session.components("AA_TABLE_"):
            g = e["geometry"]
            attrs = {a["tag"]: a.get("text", {}).get("value", "")
                     for a in g.get("attribs", [])}
            tid = attrs.get("AA_ID") or g["block"][len("AA_TABLE_"):]
            at = (float(attrs.get("AA_ATX", "0") or 0), float(attrs.get("AA_ATY", "0") or 0))
            header = [c for c in (attrs.get("AA_HEADER") or "").split("~")]
            data = [[c for c in r.split("~")]
                    for r in (attrs.get("AA_ROWS") or "").split("@@") if r]
            widths = [float(w) for w in (attrs.get("AA_WIDTHS") or "").split("~") if w]
            if not widths:
                continue
            # 列宽也是纸面 mm（1:100 => 图元），按新旧比例等比缩放
            prev_sc = float(attrs.get("AA_SCALE", "100") or 100)
            widths = [w * sc / prev_sc for w in widths]
            delete_component(session, g["block"])
            draw_table(session, at, attrs.get("AA_TITLE", ""), header, data,
                       widths, table_id=tid, scale=sc)
            tables.append({"id": tid})

        dims = 0
        if rebuild_dims:
            res = annotate(session, scale=sc)
            dims = res["dims"]
    finally:
        if prev is None:
            try:
                del session.annot_scale
            except AttributeError:
                pass
        else:
            session.annot_scale = prev
    return {"scale": sc, "grids": grids, "openings": len(openings),
            "rooms": len(rooms), "symbols": symbols, "dims": dims}


def wall_info(session: Session, wall_id: str) -> dict[str, Any]:
    """读取墙参照的定位信息与属性；墙不存在直接报错。"""
    block = "AA_WALL_" + wall_id
    ref = session.reference(block)
    if not ref:
        raise CadError("找不到墙 %s：门窗必须依附于已存在的墙" % wall_id)
    g = ref["geometry"]
    attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in g.get("attribs", [])}
    return {
        "block": block,
        "at": (g["insert"]["x"], g["insert"]["y"]),
        # insert.rotation 入参为度、回读为弧度（实测），此处统一暴露弧度
        "rotation_rad": g.get("rotation", 0.0),
        "length": float(attrs.get("AA_LEN", "0") or 0),
        "thick": float(attrs.get("AA_THICK", "0") or 0),
        "attrs": attrs,
    }


def _openings_on_wall(session: Session, wall_id: str) -> list[tuple[str, float, float]]:
    """返回 (id, pos, width)，用于同墙洞口重叠校验。"""
    out = []
    for e in session.components("AA_OPENING_"):
        attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in e["geometry"].get("attribs", [])}
        if attrs.get("AA_WALLID") != wall_id:
            continue
        out.append(
            (
                attrs.get("AA_ID", e["geometry"]["block"].replace("AA_OPENING_", "")),
                float(attrs.get("AA_POS", "0") or 0),
                float(attrs.get("AA_WIDTH", "0") or 0),
            )
        )
    return out


def opening_no(kind: str, width: float, height: float) -> str:
    """门窗编号（尺寸式，施工图常用）：类型 + 洞口宽高（分米，两位）。

    DOOR 900x2100 -> M0921；WINDOW 1200x1500 -> C1215；门连窗 -> MC0921。
    """
    prefix = {"DOOR": "M", "WINDOW": "C", "DOORWIN": "MC"}.get(kind, "M")
    return "%s%02d%02d" % (prefix, int(round(width / 100.0)), int(round(height / 100.0)))


def _label_side_sign(session: Session, wall: dict[str, Any], pos: float,
                     label_side: str) -> float:
    """把"编号放室内/室外"换算成本地侧向 +1（+Y）/ -1（-Y）。

    本地 +Y 在世界上就是墙方向左法向；探一点判断那一侧是不是房间，
    就知道 +Y 是室内还是室外。label_side="auto" 沿用旧行为（-Y 侧）。
    """
    if label_side == "auto":
        return -1.0
    r = wall["rotation_rad"]
    d = (math.cos(r), math.sin(r))
    n = (-d[1], d[0])
    p1 = tuple(wall["at"])
    probe = (p1[0] + d[0] * pos + n[0] * (wall["thick"] / 2.0 + 50.0),
             p1[1] + d[1] * pos + n[1] * (wall["thick"] / 2.0 + 50.0))
    polys: list[list[tuple[float, float]]] = []
    for r in room_data(session):
        raw = r.get("pts")
        if isinstance(raw, str) and raw.strip():
            try:
                polys.append([tuple(p) for p in ast.literal_eval(raw)])
                continue
            except (ValueError, SyntaxError):
                pass
        elif raw:
            polys.append([tuple(p) for p in raw])
    plus_y_indoor = any(_in_polygon(probe, poly) for poly in polys) if polys else None
    if plus_y_indoor is None:
        return -1.0          # 没有房间时无法判断，退回默认侧
    want_inside = label_side == "in"
    return 1.0 if (plus_y_indoor == want_inside) else -1.0


def create_opening(
    session: Session,
    opening_id: str,
    wall_id: str,
    kind: str,
    width: float,
    pos: float,
    height: float | None = None,
    sill: float = 0.0,
    frame: float = 60.0,
    no: str = "",
    label_side: str = "in",
    tol: float = 1e-6,
) -> dict[str, Any]:
    """门窗：校验 -> LISP 生成符号 -> block -> insert（贴墙）-> 回读校验。

    校验规则（spec §6.2）：
      1. 所属墙必须存在
      2. 宽度 > 0
      3. 洞口必须完全落在墙段内（含容差）
      4. 同一墙段上的洞口不得重叠
    任一规则不满足 => 拒绝写入并报告原因。

    frame = 窗框厚（构造尺寸，默认 60，可逐樘给定）；no = 门窗编号，
    留空则按尺寸自动生成（见 opening_no）。
    """
    wall = wall_info(session, wall_id)
    wlen, thick = wall["length"], wall["thick"]

    if width <= 0:
        raise CadError("拒绝写入：洞口宽度必须为正实数（收到 %s）" % width)
    if frame <= 0:
        raise CadError("拒绝写入：窗框厚必须为正实数（收到 %s）" % frame)
    lo, hi = pos - width / 2.0, pos + width / 2.0
    if lo < -tol or hi > wlen + tol:
        raise CadError(
            "拒绝写入：洞口 [%.4f, %.4f] 超出墙 %s 的可用范围 [0, %.4f]"
            % (lo, hi, wall_id, wlen)
        )
    for oid, opos, owidth in _openings_on_wall(session, wall_id):
        olo, ohi = opos - owidth / 2.0, opos + owidth / 2.0
        if min(hi, ohi) - max(lo, olo) > tol:
            raise CadError(
                "拒绝写入：洞口与已存在洞口 %s [%.4f, %.4f] 重叠"
                % (oid, olo, ohi)
            )

    if height is None:
        height = {"DOOR": 2100.0, "WINDOW": 1500.0, "DOORWIN": 2100.0}.get(kind, 2100.0)
    no = no or opening_no(kind, width, height)
    if label_side not in ("in", "out", "auto", "leader"):
        raise CadError("拒绝写入：label_side 只能是 in / out / auto / leader（收到 %s）" % label_side)
    # 墙块若转了 180°（墙从右往左画），块内编号会倒着看；给文字补 180° 抵消。
    rot_deg = (math.degrees(wall["rotation_rad"]) + 360.0) % 360.0
    label_rot = math.pi if 135.0 <= rot_deg <= 225.0 else 0.0
    # leader 用"室内侧"定方向（没有房间时退回 -Y），再靠引线把编号引出去
    side = _label_side_sign(session, wall, pos,
                            "in" if label_side == "leader" else label_side)
    leader_flag = 1 if label_side == "leader" else 0

    block = "AA_OPENING_" + opening_id
    session.ensure_layers([LAYERS["opening"]])

    before = session.snapshot()
    sc = drawing_scale(session)
    value = session.lisp(
        '(progn (setq aa:*label-h* %.4f) (aa:opening %s %s %s "%s" %s "%s" %s %s %d))'
        % (annot_size(1.8, sc), pos, width, thick, kind, frame, no, label_rot, side,
           leader_flag),
        libraries=("aa_core.lisp", "aa_opening.lisp"),
    )
    handles = session.new_handles(before)
    got_pos, got_width = value.split("#")
    if abs(float(got_pos) - pos) > 1e-4 or abs(float(got_width) - width) > 1e-4:
        raise CadError("LISP 参数回显不一致：pos=%s width=%s" % (got_pos, got_width))

    att_handles = session.define_attributes(
        [
            ("AA_TYPE", "component type", "OPENING"),
            ("AA_ID", "component id", opening_id),
            ("AA_KIND", "opening kind", kind),
            ("AA_WIDTH", "opening width", "%.4f" % float(width)),
            ("AA_HEIGHT", "opening height", "%.4f" % float(height)),
            ("AA_SILL", "sill height", "%.4f" % float(sill)),
            ("AA_WALLID", "host wall id", wall_id),
            ("AA_POS", "offset from wall start", "%.4f" % float(pos)),
            ("AA_FRAME", "window frame thickness", "%.4f" % float(frame)),
            ("AA_NO", "opening mark", no),
            ("AA_LABELSIDE", "label side", label_side),
        ]
    )

    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(
        block,
        wall["at"],
        {
            "AA_TYPE": "OPENING",
            "AA_ID": opening_id,
            "AA_KIND": kind,
            "AA_WIDTH": "%.4f" % float(width),
            "AA_HEIGHT": "%.4f" % float(height),
            "AA_SILL": "%.4f" % float(sill),
            "AA_WALLID": wall_id,
            "AA_POS": "%.4f" % float(pos),
            "AA_FRAME": "%.4f" % float(frame),
            "AA_NO": no,
            "AA_LABELSIDE": label_side,
        },
        rotation=math.degrees(wall["rotation_rad"]),
        layer=LAYERS["opening"],
    )
    session.expect_attributes(
        block,
        {
            "AA_ID": opening_id,
            "AA_TYPE": "OPENING",
            "AA_KIND": kind,
            "AA_WIDTH": "%.4f" % float(width),
            "AA_WALLID": wall_id,
            "AA_POS": "%.4f" % float(pos),
            "AA_NO": no,
            "AA_LABELSIDE": label_side,
        },
    )
    # 洞口符号落地后，重生成所属墙块，让墙身两侧线在洞口处断开
    rebuild_wall_with_openings(session, wall_id)

    return {
        "block": block,
        "handle": handle,
        "width": float(width),
        "pos": float(pos),
        "wall": wall_id,
        "frame": float(frame),
        "no": no,
        "label_side": label_side,
        "geom_handles": handles,
    }


def _poly_signed_area(pts: Sequence[tuple[float, float]]) -> float:
    """带符号面积（鞋带公式），>0 表示逆时针。"""
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def _line_intersect(
    p1: tuple[float, float], u1: tuple[float, float],
    p2: tuple[float, float], u2: tuple[float, float],
) -> tuple[float, float] | None:
    den = u1[0] * u2[1] - u1[1] * u2[0]
    if abs(den) < 1e-12:
        return None
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    t = (dx * u2[1] - dy * u2[0]) / den
    return (p1[0] + t * u1[0], p1[1] + t * u1[1])


def _room_inner(edges: list[tuple[tuple[float, float], tuple[float, float], str]],
                thick: dict[str, float], tol: float) -> tuple[list[tuple[float, float]], float]:
    """由有序边界边（p→q, 墙号）求房间净轮廓与面积。

    edges 必须首尾相接、闭合成环；内部会统一成逆时针，再把每条边向内侧平移半墙厚、
    求相邻平移线交点，得到净空轮廓（鞋带公式给面积）。
    """
    if len(edges) < 3:
        raise CadError("拒绝写入：房间边界少于 3 条边")
    pts = [e[0] for e in edges]
    for i in range(len(edges)):
        q = edges[i][1]
        if math.dist(q, edges[(i + 1) % len(edges)][0]) > 1.0:
            raise CadError("拒绝写入：墙环断裂（边 %d 与前一条不接）" % i)
    if _poly_signed_area(pts) < 0:
        edges = [(q, p, wid) for (p, q, wid) in reversed(edges)]

    inner: list[tuple[float, float]] = []
    n = len(edges)
    for i in range(n):
        p_prev, q_prev, w_prev = edges[i - 1]
        p_cur, q_cur, w_cur = edges[i]
        up, uc = _unit(p_prev, q_prev), _unit(p_cur, q_cur)
        hp, hc = thick.get(w_prev, 0.0) / 2.0, thick.get(w_cur, 0.0) / 2.0
        # 逆时针环的内侧 = 方向左手法向
        lp = (p_prev[0] - up[1] * hp, p_prev[1] + up[0] * hp)
        lc = (p_cur[0] - uc[1] * hc, p_cur[1] + uc[0] * hc)
        pt = _line_intersect(lp, up, lc, uc)
        inner.append(pt if pt is not None else lc)
    area = abs(_poly_signed_area(inner))
    if area <= tol:
        raise CadError("拒绝写入：内偏移后面积为 0，墙厚与墙长不匹配")
    return inner, area


def _store_room(session: Session, room_id: str, inner: list[tuple[float, float]],
                area: float, wall_ids: Sequence[str], name: str,
                scale: float | None = None, show_area: bool = True) -> dict[str, Any]:
    """把算好的房间轮廓落图：LISP 画名称/面积 -> block -> insert -> 回读校验。"""
    block = "AA_ROOM_" + room_id
    session.ensure_layers([LAYERS["room"]])
    sc = float(scale) if scale else drawing_scale(session)

    pts_lisp = " ".join("(list %.4f %.4f 0.0)" % (p[0], p[1]) for p in inner)
    before = session.snapshot()
    value = session.lisp(
        '(progn (setq aa:*room-h* %.4f) (setq aa:*room-area-h* %.4f)'
        " (setq aa:*room-show-area* %d) (aa:room (list %s) \"%s\"))"
        % (annot_size(2.5, sc), annot_size(2.0, sc), 1 if show_area else 0,
           pts_lisp, name),
        libraries=("aa_core.lisp", "aa_room.lisp"),
    )
    handles = session.new_handles(before)
    got_area, got_per = value.split("#")

    pts_str = ";".join("%.2f,%.2f" % (p[0], p[1]) for p in inner)
    att_handles = session.define_attributes(
        [
            ("AA_TYPE", "component type", "ROOM"),
            ("AA_ID", "component id", room_id),
            ("AA_NAME", "room name", name),
            ("AA_AREA", "area", "%.2f" % area),
            ("AA_PERIMETER", "perimeter", "%.2f" % float(got_per)),
            ("AA_WALLS", "enclosing walls", ";".join(wall_ids)),
            ("AA_PTS", "inner outline", pts_str),
            ("AA_AREA_SHOW", "show area text", "1" if show_area else "0"),
        ]
    )

    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(
        block,
        (0.0, 0.0),
        {
            "AA_TYPE": "ROOM",
            "AA_ID": room_id,
            "AA_NAME": name,
            "AA_AREA": "%.2f" % area,
            "AA_PERIMETER": "%.2f" % float(got_per),
            "AA_WALLS": ";".join(wall_ids),
            "AA_PTS": pts_str,
            "AA_AREA_SHOW": "1" if show_area else "0",
        },
        layer=LAYERS["room"],
    )
    session.expect_attributes(
        block,
        {
            "AA_ID": room_id,
            "AA_TYPE": "ROOM",
            "AA_AREA": "%.2f" % area,
            "AA_WALLS": ";".join(wall_ids),
        },
    )
    # 房间出现后，室内/室外才可判定：把该房间墙上的门窗编号重画到正确一侧
    refresh_opening_labels(session, wall_ids)
    return {
        "block": block,
        "handle": handle,
        "area": area,
        "perimeter": float(got_per),
        "inner": inner,
        "geom_handles": handles,
    }


def refresh_opening_labels(session: Session, wall_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """"室内/室外"编号侧向依赖房间轮廓，房间后建时必须重算并重画编号。

    只重画、不改参数：按现有属性原样重建门窗符号（顺带重建所属墙洞口）。
    """
    if not room_data(session):
        return {"openings": 0, "ids": []}
    pool = opening_data(session)
    if wall_ids is not None:
        keep = set(wall_ids)
        pool = [o for o in pool if o["wallid"] in keep]
    ids = [o["id"] for o in pool]
    for oid in ids:
        set_opening(session, oid)      # 同参数重画，内部会按房间重算侧向
    return {"openings": len(ids), "ids": ids}


COLUMN_KINDS = ("RECT", "CIRCLE")
STAIR_KINDS = ("STRAIGHT", "DOGLEG")
STAIR_LEVELS = ("FIRST", "MIDDLE", "TOP")


def create_column(
    session: Session,
    column_id: str,
    at: tuple[float, float],
    w: float,
    h: float | None = None,
    kind: str = "RECT",
    angle: float = 0.0,
    material: str = "",
    scale: float | None = None,
) -> dict[str, Any]:
    """柱（天正平面图做法）：矩形柱 = 实心 SOLID + 外框；圆柱 = 圆 + 扇形填充。

    全部落在 `AA-COLUMN` 层（颜色 8、线宽 0.35，与墙同粗）。`at` 是柱中心，
    `w/h` 是柱截面（圆柱时 `w` 即直径、`h` 忽略）；`angle` 是矩形柱绕中心的转角（度）。
    几何是真实尺寸，不随出图比例缩放——柱不会因为换比例变大变小。
    """
    block = "AA_COLUMN_" + column_id
    if session.block_exists(block):
        raise CadError("柱 %s 已存在，请换编号" % column_id)
    kind_u = str(kind).upper()
    if kind_u not in COLUMN_KINDS:
        raise CadError("柱类型只能是 RECT / CIRCLE（收到 %r）" % kind)
    w = float(w)
    if w <= 0:
        raise CadError("拒绝写入：柱截面必须为正实数（收到 %s）" % w)
    if kind_u == "RECT":
        hh = float(h) if h is not None else w
        if hh <= 0:
            raise CadError("拒绝写入：柱高必须为正实数（收到 %s）" % hh)
    else:
        hh = w

    session.ensure_layers([LAYERS["column"]])
    before = session.snapshot()
    if kind_u == "RECT":
        session.lisp(
            '(aa:column-rect %.4f %.4f %.6f)' % (w, hh, math.radians(float(angle))),
            libraries=("aa_core.lisp", "aa_column.lisp"))
    else:
        session.lisp('(aa:column-circle %.4f)' % w,
                     libraries=("aa_core.lisp", "aa_column.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("柱没有生成任何图元")

    area = (w * hh) if kind_u == "RECT" else math.pi * (w / 2.0) ** 2
    att_defs = [
        ("AA_TYPE", "component type", "COLUMN"),
        ("AA_ID", "component id", column_id),
        ("AA_KIND", "column kind", kind_u),
        ("AA_W", "column width/diameter", "%.4f" % w),
        ("AA_H", "column height", "%.4f" % hh),
        ("AA_ANGLE", "rotation deg", "%.4f" % float(angle)),
        ("AA_MATERIAL", "material", material),
        ("AA_AREA", "section area", "%.4f" % area),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (float(at[0]), float(at[1])), att_vals,
                            layer=LAYERS["column"])
    session.expect_attributes(block, {"AA_TYPE": "COLUMN", "AA_ID": column_id,
                                      "AA_KIND": kind_u, "AA_W": "%.4f" % w})
    return {"block": block, "handle": handle, "kind": kind_u, "w": w, "h": hh,
            "angle": float(angle), "area": area, "geom_handles": handles}


def create_step(
    session: Session,
    step_id: str,
    at: tuple[float, float],
    width: float,
    steps: int = 3,
    tread: float = 300.0,
    angle: float = 270.0,
    rise: float = 150.0,
) -> dict[str, Any]:
    """室外台阶（天正"台阶"做法）：贴墙面的第一条线不画（与墙线重合），
    只画 `steps` 条踏步线（最后一条即外沿）+ 两侧边线，落在 `AA-STEP`（白 7 / 0.18）。

    `at` = 贴墙线中点；`angle` = 外挑方向（度，0=+X、90=+Y、270=-Y）；
    `width` 沿墙向；`steps` 踏步数；`tread` 踏步宽；`rise` 单步高（记录用，平面不画）。
    总进深 = steps*tread，可回读 `AA_DEPTH`。
    """
    block = "AA_STEP_" + step_id
    if session.block_exists(block):
        raise CadError("台阶 %s 已存在，请换编号" % step_id)
    width, tread, rise = float(width), float(tread), float(rise)
    if width <= 0 or tread <= 0:
        raise CadError("拒绝写入：台阶宽与踏步宽必须为正实数（收到 %s / %s）" % (width, tread))
    if int(steps) != steps or int(steps) < 1:
        raise CadError("拒绝写入：踏步数必须是 >=1 的整数（收到 %s）" % steps)
    steps = int(steps)
    depth = steps * tread
    angle = float(angle) % 360.0

    session.ensure_layers([LAYERS["step"]])
    before = session.snapshot()
    session.lisp('(aa:step %.4f %d %.4f)' % (width, steps, tread),
                 libraries=("aa_core.lisp", "aa_step.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("台阶没有生成任何图元")

    att_defs = [
        ("AA_TYPE", "component type", "STEP"),
        ("AA_ID", "component id", step_id),
        ("AA_W", "step width along wall", "%.4f" % width),
        ("AA_STEPS", "tread count", str(steps)),
        ("AA_TREAD", "tread depth", "%.4f" % tread),
        ("AA_DEPTH", "total depth", "%.4f" % depth),
        ("AA_RISE", "rise per step", "%.4f" % rise),
        ("AA_H", "total rise", "%.4f" % (steps * rise)),
        ("AA_ANGLE", "outward direction deg", "%.4f" % angle),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (float(at[0]), float(at[1])), att_vals,
                            rotation=angle - 90.0, layer=LAYERS["step"])
    session.expect_attributes(block, {"AA_TYPE": "STEP", "AA_ID": step_id,
                                      "AA_STEPS": str(steps), "AA_W": "%.4f" % width})
    return {"block": block, "handle": handle, "width": width, "steps": steps,
            "tread": tread, "depth": depth, "angle": angle, "geom_handles": handles}


def create_apron(
    session: Session,
    apron_id: str,
    at: tuple[float, float],
    length: float,
    width: float = 800.0,
    angle: float = 270.0,
) -> dict[str, Any]:
    """散水（天正"散水"做法）：沿外墙外侧的等宽带，只画外沿线 + 两端收头线，
    贴墙那条线由外墙自身承担；落在 `AA-STEP`（与台阶同层，同为室外附属）。

    `at` = 贴墙线中点；`length` 沿墙长；`width` 外挑宽（默认 800，常规 600–1000）；
    `angle` = 外挑方向（度）。两端收头暂按垂直收头（非 45° 斜接口）。
    """
    block = "AA_APRON_" + apron_id
    if session.block_exists(block):
        raise CadError("散水 %s 已存在，请换编号" % apron_id)
    length, width = float(length), float(width)
    if length <= 0 or width <= 0:
        raise CadError("拒绝写入：散水长度与外挑宽必须为正实数（收到 %s / %s）" % (length, width))
    angle = float(angle) % 360.0

    session.ensure_layers([LAYERS["step"]])
    before = session.snapshot()
    session.lisp('(aa:apron %.4f %.4f)' % (length, width),
                 libraries=("aa_core.lisp", "aa_step.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("散水没有生成任何图元")

    att_defs = [
        ("AA_TYPE", "component type", "APRON"),
        ("AA_ID", "component id", apron_id),
        ("AA_W", "apron width", "%.4f" % width),
        ("AA_LEN", "length along wall", "%.4f" % length),
        ("AA_ANGLE", "outward direction deg", "%.4f" % angle),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (float(at[0]), float(at[1])), att_vals,
                            rotation=angle - 90.0, layer=LAYERS["step"])
    session.expect_attributes(block, {"AA_TYPE": "APRON", "AA_ID": apron_id,
                                      "AA_W": "%.4f" % width, "AA_LEN": "%.4f" % length})
    return {"block": block, "handle": handle, "length": length, "width": width,
            "angle": angle, "geom_handles": handles}


def create_stair(
    session: Session,
    stair_id: str,
    at: tuple[float, float],
    kind: str = "STRAIGHT",
    width: float = 1200.0,
    steps: int = 10,
    tread: float = 280.0,
    rise: float = 150.0,
    well: float = 120.0,
    landing: float = 1200.0,
    angle: float = 90.0,
    level: str = "MIDDLE",
    side: str = "LEFT",
) -> dict[str, Any]:
    """楼梯（天正平面做法）：直跑 STRAIGHT / 双跑 U 形 DOGLEG。

    `at` = 起步踏步前缘中点，`angle` = 上行方向（度，90=+Y 向上）。
    `width` 是单跑梯段宽；`steps` 是**每跑**踏步数（双跑总踏步 = 2×steps）；
    `tread` 踏步宽；`well` 梯井宽（双跑用，直跑忽略）；`landing` 平台深（双跑用）。
    总水平投影：直跑 = steps*tread；双跑 = 2*landing + steps*tread。

    图形：踏步线 + 梯段边线 + 上行箭头（实心三角），落 `AA-STAIR`（白 7 / 0.18）。
    剖断线、踏步数文字暂不画（规格 §26 注明）。
    """
    block = "AA_STAIR_" + stair_id
    if session.block_exists(block):
        raise CadError("楼梯 %s 已存在，请换编号" % stair_id)
    kind_u = str(kind).upper()
    if kind_u not in STAIR_KINDS:
        raise CadError("楼梯类型只能是 STRAIGHT / DOGLEG（收到 %r）" % kind)
    width, tread, rise = float(width), float(tread), float(rise)
    if width <= 0 or tread <= 0:
        raise CadError("拒绝写入：梯段宽与踏步宽必须为正实数（收到 %s / %s）" % (width, tread))
    if int(steps) != steps or int(steps) < 2:
        raise CadError("拒绝写入：每跑踏步数必须是 >=2 的整数（收到 %s）" % steps)
    steps = int(steps)
    well, landing = float(well), float(landing)
    level_u = str(level).upper()
    if level_u not in STAIR_LEVELS:
        raise CadError("层类型只能是 FIRST / MIDDLE / TOP（收到 %r）" % level)
    side_u = str(side).upper()
    if side_u not in ("LEFT", "RIGHT"):
        raise CadError("上楼位置只能是 LEFT / RIGHT（收到 %r）" % side)
    if kind_u == "DOGLEG":
        if well < 0:
            raise CadError("拒绝写入：梯井宽不能为负（收到 %s）" % well)
        if landing <= 0:
            raise CadError("拒绝写入：平台深必须为正实数（收到 %s）" % landing)
    angle = float(angle) % 360.0

    run = steps * tread
    if kind_u == "STRAIGHT":
        depth = run
        total_steps = steps
    else:
        depth = landing + run
        total_steps = steps * 2

    session.ensure_layers([LAYERS["stair"], LAYERS["stairarrow"],
                            LAYERS["stairtext"], LAYERS["stairbreak"]])
    sc = drawing_scale(session)
    lh = annot_size(2.5, sc)
    rot = (angle - 90.0) % 360.0
    trot = math.pi if 135.0 <= rot <= 225.0 else 0.0
    before = session.snapshot()
    if kind_u == "STRAIGHT":
        session.lisp('(aa:stair-straight %.4f %d %.4f %.4f %.6f)' % (width, steps, tread, lh, trot),
                     libraries=("aa_core.lisp", "aa_symbol.lisp", "aa_stair.lisp"))
    else:
        lv = {"FIRST": 1, "MIDDLE": 0, "TOP": 2}[level_u]
        sgn = 1 if side_u == "LEFT" else -1
        session.lisp('(aa:stair-dogleg %.4f %d %.4f %.4f %.4f %.4f %.6f %d %d)'
                     % (width, steps, tread, well, landing, lh, trot, lv, sgn),
                     libraries=("aa_core.lisp", "aa_symbol.lisp", "aa_stair.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("楼梯没有生成任何图元")

    att_defs = [
        ("AA_TYPE", "component type", "STAIR"),
        ("AA_ID", "component id", stair_id),
        ("AA_KIND", "stair kind", kind_u),
        ("AA_W", "flight width", "%.4f" % width),
        ("AA_STEPS", "steps per flight", str(steps)),
        ("AA_STEPS_TOTAL", "total steps", str(total_steps)),
        ("AA_TREAD", "tread depth", "%.4f" % tread),
        ("AA_RISE", "riser height", "%.4f" % rise),
        ("AA_RUN", "run per flight", "%.4f" % run),
        ("AA_DEPTH", "total plan depth", "%.4f" % depth),
        ("AA_WELL", "well width", "%.4f" % (well if kind_u == "DOGLEG" else 0.0)),
        ("AA_LANDING", "landing depth", "%.4f" % (landing if kind_u == "DOGLEG" else 0.0)),
        ("AA_LEVEL", "floor level type", level_u),
        ("AA_UPSIDE", "up side", side_u),
        ("AA_ANGLE", "up direction deg", "%.4f" % angle),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (float(at[0]), float(at[1])), att_vals,
                            rotation=angle - 90.0, layer=LAYERS["stair"])
    session.expect_attributes(block, {"AA_TYPE": "STAIR", "AA_ID": stair_id,
                                      "AA_KIND": kind_u, "AA_STEPS": str(steps)})
    return {"block": block, "handle": handle, "kind": kind_u, "width": width,
            "steps": steps, "steps_total": total_steps, "tread": tread, "run": run,
            "depth": depth, "angle": angle, "level": level_u, "side": side_u,
            "geom_handles": handles}


ROOF_KINDS = ("FLAT", "GABLE", "HIP", "SHED")


def create_roof(
    session: Session,
    roof_id: str,
    at: tuple[float, float],
    kind: str = "FLAT",
    width: float = 6000.0,
    depth: float = 4000.0,
    overhang: float = 600.0,
    gutter: float = 300.0,
    ridge: str = "X",
    angle: float = 0.0,
    parapet: float = 0.0,
    hatch: Sequence[Any] = (),
) -> dict[str, Any]:
    """屋顶平面（GB/T 50104 屋顶平面图 + 天正"屋顶"做法）。

    `at` = 屋面投影（建筑外轮廓）左下角，`width/depth` 沿本地 +X/+Y。
    `kind`：FLAT 平屋顶（檐沟 + 四角雨水口 + 南北找坡）/
            GABLE 双坡（正脊 + 两坡）/ HIP 四坡（正脊 + 四条 45° 斜脊）/ SHED 单坡。
    `overhang` 檐口外挑；`gutter` 檐沟宽；`ridge` 屋脊方向 X/Y；`angle` 整体旋转。
    `parapet` 女儿墙厚（0 = 不画，只有平屋顶能画）：平面里画两条闭合矩形——
    外圈是压顶外沿（比屋面轮廓外扩 60 的构造挑出），内圈是女儿墙内皮（轮廓内缩墙厚）。
    `hatch` 上人孔 `{x, y, size}`（x/y 相对 at 的屋面坐标，size 边长，常见 700）：
    画方框 + 对角斜线 + "上人孔" 注字，必须落在屋面净区里。

    图形落 `AA-ROOF`（白 7 / 0.25）与 `AA-ROOF-ARROW`（绿 3 / 0.18），
    找坡箭头一律指向下坡（檐口 / 檐沟）。暂不做坡屋顶内天沟与坡度文字。
    """
    block = "AA_ROOF_" + roof_id
    if session.block_exists(block):
        raise CadError("屋顶 %s 已存在，请换编号" % roof_id)
    kind_u = str(kind).upper()
    if kind_u not in ROOF_KINDS:
        raise CadError("屋顶类型只能是 FLAT / GABLE / HIP / SHED（收到 %r）" % kind)
    ridge_u = str(ridge).upper()
    if ridge_u not in ("X", "Y"):
        raise CadError("屋脊方向只能是 X / Y（收到 %r）" % ridge)
    width, depth = float(width), float(depth)
    overhang, gutter = float(overhang), float(gutter)
    if width <= 0 or depth <= 0:
        raise CadError("拒绝写入：屋面宽与进深必须为正实数（收到 %s / %s）" % (width, depth))
    if overhang < 0:
        raise CadError("拒绝写入：檐口外挑不能为负（收到 %s）" % overhang)
    if gutter <= 0:
        raise CadError("拒绝写入：檐沟宽必须为正实数（收到 %s）" % gutter)
    if kind_u == "FLAT":
        if 2.0 * (overhang + gutter) >= min(width, depth):
            raise CadError("拒绝写入：檐沟 %s + 外挑 %s 太大，屋面已经没有净面积（%s×%s）"
                           % (gutter, overhang, width, depth))
    if kind_u in ("GABLE", "HIP") and ridge_u == "X" and depth < 1000.0:
        raise CadError("拒绝写入：屋脊沿 X 时进深太小（收到 %s），画不出两坡" % depth)
    angle = float(angle) % 360.0
    parapet = float(parapet)
    if parapet < 0:
        raise CadError("拒绝写入：女儿墙厚不能为负（收到 %s）" % parapet)
    if parapet > 0 and kind_u != "FLAT":
        raise CadError("拒绝写入：女儿墙只在平屋顶平面上画（当前 %s）" % kind_u)
    if parapet > 0 and 2.0 * parapet >= min(width, depth):
        raise CadError("拒绝写入：女儿墙厚 %s 太大，屋面已经没有净宽" % parapet)
    hx, hy, hs = 0.0, 0.0, 0.0
    if hatch:
        h = dict(hatch) if isinstance(hatch, dict) else {}
        if not h:
            raise CadError("上人孔要写成 {x, y, size}（收到 %r）" % (hatch,))
        hx, hy = float(h.get("x", 0.0)), float(h.get("y", 0.0))
        hs = float(h.get("size", 700.0))
        if hs <= 0:
            raise CadError("拒绝写入：上人孔边长必须为正（收到 %s）" % hs)
        if kind_u == "FLAT":
            m = max(overhang + gutter, parapet)
        elif kind_u == "SHED":
            m = max(overhang, gutter)
        else:
            m = overhang
        if (hx - hs / 2.0 < m or hy - hs / 2.0 < m
                or hx + hs / 2.0 > width - m or hy + hs / 2.0 > depth - m):
            raise CadError("拒绝写入：上人孔 %s×%s @(%s,%s) 落在屋面净区之外"
                           % (hs, hs, hx, hy))

    session.ensure_layers([LAYERS["roof"], LAYERS["roofarrow"]])
    sc = drawing_scale(session)
    lh = annot_size(2.5, sc)
    kind_code = {"FLAT": 0, "GABLE": 1, "HIP": 2, "SHED": 3}[kind_u]
    ridgex = 1 if ridge_u == "X" else 0
    before = session.snapshot()
    session.lisp('(aa:roof %.4f %.4f %.4f %.4f %d %d %.6f %.4f %.4f %.4f %.4f)'
                 % (width, depth, overhang, gutter, kind_code, ridgex, lh,
                    parapet, hx, hy, hs),
                 libraries=("aa_core.lisp", "aa_roof.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("屋顶没有生成任何图元")

    outer_w = width + 2.0 * overhang
    outer_d = depth + 2.0 * overhang
    area = outer_w * outer_d
    att_defs = [
        ("AA_TYPE", "component type", "ROOF"),
        ("AA_ID", "component id", roof_id),
        ("AA_KIND", "roof kind", kind_u),
        ("AA_W", "roof width", "%.4f" % width),
        ("AA_D", "roof depth", "%.4f" % depth),
        ("AA_OVERHANG", "eave overhang", "%.4f" % overhang),
        ("AA_GUTTER", "gutter width", "%.4f" % gutter),
        ("AA_RIDGE", "ridge direction", ridge_u),
        ("AA_ANGLE", "rotation deg", "%.4f" % angle),
        ("AA_AREA", "plan area incl overhang", "%.4f" % area),
        ("AA_PARAPET", "parapet thickness", "%.4f" % parapet),
        ("AA_HATCH", "roof access hatch", "%.4f,%.4f,%.4f" % (hx, hy, hs)),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (float(at[0]), float(at[1])), att_vals,
                            rotation=angle, layer=LAYERS["roof"])
    session.expect_attributes(block, {"AA_TYPE": "ROOF", "AA_ID": roof_id,
                                      "AA_KIND": kind_u,
                                      "AA_W": "%.4f" % width})
    return {"block": block, "handle": handle, "kind": kind_u, "width": width,
            "depth": depth, "overhang": overhang, "gutter": gutter,
            "ridge": ridge_u, "angle": angle, "area": area,
            "parapet": parapet, "hatch": (hx, hy, hs) if hs > 0 else None,
            "outer_w": outer_w, "outer_d": outer_d, "geom_handles": handles}


def _norm_floors(floors: Sequence[Any]) -> list[dict[str, Any]]:
    """立面/剖面用的楼层数据：接受 {height,elev?} 或 {no,elev,height,plan,name}，
    标高缺省按层高自下而上累加（首层 ±0.000）。"""
    rows: list[dict[str, Any]] = []
    prev_top = 0.0
    for i, f in enumerate(floors):
        if not isinstance(f, dict):
            raise CadError("楼层数据必须是对象（收到 %r）" % (f,))
        h = float(f.get("height", 0.0) or 0.0)
        if h <= 0:
            raise CadError("第 %d 层层高必须大于 0（收到 %s）" % (i + 1, h))
        if f.get("elev") is None:
            e = 0.0 if i == 0 else prev_top
        else:
            e = float(f["elev"])
        if i and e <= rows[-1]["elev"] + 1e-6:
            raise CadError("第 %d 层标高必须高于下一层（%s <= %s）"
                           % (i + 1, e, rows[-1]["elev"]))
        rows.append({"no": str(f.get("no", i + 1)), "elev": e, "height": h,
                     "plan": str(f.get("plan", "")), "name": str(f.get("name", ""))})
        prev_top = e + h
    return rows


ELEV_ROOFS = ("FLAT", "GABLE", "EAVE", "NONE")
SECTION_ROOFS = ("FLAT", "GABLE", "NONE")


def _dim_segments(vals: Sequence[float], min_seg: float = 0.0) -> list[tuple[float, float]]:
    """把一串高度/长度排成链：先去重，`min_seg>0` 时把小于它的分界点并到下一段。

    并段是为了不同洞口的窗台/洞顶错开时造出 300 这类无意义杂段——注上去文字会骑到相邻尺寸上。
    """
    uniq: list[float] = []
    for v in sorted(float(x) for x in vals):
        if not uniq or abs(v - uniq[-1]) > 1e-6:
            uniq.append(v)
    if len(uniq) < 2:
        return []
    segs: list[tuple[float, float]] = []
    acc = uniq[0]
    for v in uniq[1:]:
        if min_seg > 0 and v - acc < min_seg and v != uniq[-1]:
            continue
        segs.append((acc, v))
        acc = v
    return [s for s in segs if s[1] - s[0] > 1.0]


def _dim_chain(session: Session, W, vals: Sequence[float], off: float, angle: float,
               vertical: bool = True, min_seg: float = 0.0,
               min_len: float = 0.0) -> int:
    """注一道链式尺寸，全部落 AA-DIM，返回条数。

    `W(x, y)` 是局部→世界坐标的变换（立面/剖面各自带的平移旋转）；
    vertical=True 时尺寸线退到 x=-off（注竖向高度），否则退到 y=-off（注横向宽度）。
    `min_len`：段长小于它的**不注**（窄房间的 1.1m 净空在 1:100 上注不下，
    dimlinear 的文字锚点不归我们控，会骑到相邻尺寸上）。
    """
    n = 0
    cmds = []
    for a, b in _dim_segments(vals, min_seg):
        if min_len > 0 and b - a < min_len:
            continue
        if vertical:
            p1, p2 = W(0.0, a), W(0.0, b)
            mid = W(-off, (a + b) / 2.0)
            rot = angle + 90.0
        else:
            p1, p2 = W(a, 0.0), W(b, 0.0)
            mid = W((a + b) / 2.0, -off)
            rot = angle
        cmds.append(("dimlinear", {"p1": [round(v, 4) for v in p1],
                                   "p2": [round(v, 4) for v in p2],
                                   "at": [round(mid[0], 4), round(mid[1], 4)],
                                   "rotation": round(rot, 6)}))
        n += 1
    if cmds:
        res = session.run(cmds, save=True)
        hs = [r.get("handle") for r in res.data if r.get("handle")]
        if hs:
            # dimlinear 默认落在 0 层，必须显式改到 AA-DIM
            session.run([("properties.set", {"handles": hs, "layer": LAYERS["dim"]})],
                        save=True)
    return n


def create_elevation(
    session: Session,
    elev_id: str,
    at: tuple[float, float],
    width: float,
    floors: Sequence[Any],
    openings: Sequence[dict[str, Any]] = (),
    roof: str = "FLAT",
    parapet: float = 1200.0,
    rise: float = 0.0,
    overhang: float = 600.0,
    marks: bool = True,
    angle: float = 0.0,
    wall: str | None = None,
    flip: bool = False,
    eave: float = 0.0,
    axes: Sequence[Any] = (),
    dims: bool = True,
) -> dict[str, Any]:
    """建筑立面（GB/T 50104 立面图做法，按楼层表数据生成）。

    `at` = 立面左端 ±0.000 地面点；`width` = 立面展开宽度；`floors` = 自下而上
    [{height, elev?, no?, plan?, name?}]（也可直接喂 `read_floors` 的结果）。
    `openings` = [{floor: 1 起层号, x: 洞口左边距, w, h, sill, kind: WINDOW/DOOR}]，
    只做直立矩形洞口（窗加中横线，门只描框）。
    `wall` 给了就**从平面读这道墙上的门窗**（`read_facade_openings`），和 `openings`
    里手填的合并使用：常用的做法是一层门窗由平面派生，二三层用 `openings` 补。
    `flip=True` 表示这面墙在平面上是从右往左画的（如朝北的墙），窗口左边距要翻过来。
    `roof`：FLAT 平屋顶（挑檐 + 女儿墙 + 压顶）/ GABLE 双坡（山墙三角）/
    EAVE 双坡正对檐口（檐口 + 屋脊）/ NONE 无。
    `marks=True` 时每道楼层线右侧注标高（±0.000 / 3.600 …）。
    `eave` = 檐口板厚（0 = 不画）：FLAT 无女儿墙的挑檐、GABLE、EAVE 三种都在檐口线
    下方再画一道板底线并两端封口，厚度按构造值（常见 200）。
    `axes` = 立面轴号 `[{x, label}]`（x 为轴号在立面宽度上的位置，label 如 "1"/"A"）：
    按 GB/T 50001 在立面顶部外画 8mm 细实线圆 + 圈内 3mm 轴号，圆下方用一条细线
    引到立面轮廓顶（立面不画通长轴线，免得和门窗线打架）。
    `dims=True` 在**左侧**注三道竖向尺寸（GB/T 50104 立面必须注高度尺寸）：
    内道 = 窗台高 / 洞口高 / 洞顶到楼面（全楼特征高度排成一条链），
    中道 = 各层层高，外道 = 从 ±0.000 到含女儿墙/脊高的总高。尺寸落 `AA-DIM`。

    图元：地坪线粗、外轮廓粗落 `AA-ELEV`；楼层线、门窗、女儿墙压顶、檐口板厚落
    `AA-ELEV-DETAIL`；轴号落 `AA-AXISTEXT`。暂不做阳台、雨篷、材料图例。
    """
    block = "AA_ELEVATION_" + elev_id
    if session.block_exists(block):
        raise CadError("立面 %s 已存在，请换编号" % elev_id)
    width = float(width)
    if width <= 0:
        raise CadError("拒绝写入：立面宽度必须为正实数（收到 %s）" % width)
    rows = _norm_floors(floors)
    roof_u = str(roof).upper()
    if roof_u not in ELEV_ROOFS:
        raise CadError("屋顶形式只能是 FLAT / GABLE / EAVE / NONE（收到 %r）" % roof)
    parapet, rise, overhang = float(parapet), float(rise), float(overhang)
    if roof_u == "FLAT" and parapet < 0:
        raise CadError("拒绝写入：女儿墙高不能为负（收到 %s）" % parapet)
    if roof_u in ("GABLE", "EAVE"):
        if rise <= 0:
            raise CadError("拒绝写入：双坡屋顶的脊高必须为正（收到 %s）" % rise)
        if overhang < 0:
            raise CadError("拒绝写入：檐口外挑不能为负（收到 %s）" % overhang)
    angle = float(angle) % 360.0
    eave = float(eave)
    if eave < 0:
        raise CadError("拒绝写入：檐口板厚不能为负（收到 %s）" % eave)
    if eave > 0 and roof_u == "NONE":
        raise CadError("拒绝写入：roof=NONE 时没有檐口，檐口板厚给不了（收到 %s）" % eave)

    src: list[dict[str, Any]] = list(openings or ())
    if wall:
        src = read_facade_openings(session, wall, flip=flip) + src
    ops: list[dict[str, Any]] = []
    for i, op in enumerate(src):
        if not isinstance(op, dict):
            raise CadError("门窗数据必须是对象（收到 %r）" % (op,))
        fl = int(op.get("floor", 1) or 1)
        if not (1 <= fl <= len(rows)):
            raise CadError("第 %d 个洞口层号 %s 超出 1..%d" % (i + 1, fl, len(rows)))
        x, w = float(op.get("x", 0.0)), float(op.get("w", 0.0))
        hh, sill = float(op.get("h", 0.0)), float(op.get("sill", 0.0))
        if w <= 0 or hh <= 0:
            raise CadError("第 %d 个洞口宽高必须为正（收到 %s / %s）" % (i + 1, w, hh))
        if x < 0 or x + w > width:
            raise CadError("第 %d 个洞口超出立面宽度（x=%s w=%s width=%s）"
                           % (i + 1, x, w, width))
        if sill < 0:
            raise CadError("第 %d 个洞口窗台高不能为负（收到 %s）" % (i + 1, sill))
        kind = str(op.get("kind", "WINDOW")).upper()
        if kind not in ("WINDOW", "DOOR"):
            raise CadError("第 %d 个洞口类型只能是 WINDOW / DOOR（收到 %r）" % (i + 1, kind))
        if sill + hh > rows[fl - 1]["height"] + 1e-6:
            raise CadError("第 %d 个洞口（%s）高出本层：sill %s + h %s > 层高 %s"
                           % (i + 1, kind, sill, hh, rows[fl - 1]["height"]))
        ops.append({"floor": fl, "x": x, "w": w, "h": hh, "sill": sill,
                    "kind": kind})

    # 同层洞口不许叠在一起（叠了就是错图，早报早改）
    for i in range(len(ops)):
        for j in range(i + 1, len(ops)):
            a, b = ops[i], ops[j]
            if a["floor"] != b["floor"]:
                continue
            ax1, ax2 = a["x"], a["x"] + a["w"]
            bx1, bx2 = b["x"], b["x"] + b["w"]
            ay1, ay2 = a["sill"], a["sill"] + a["h"]
            by1, by2 = b["sill"], b["sill"] + b["h"]
            if min(ax2, bx2) - max(ax1, bx1) > 1e-6 and \
                    min(ay2, by2) - max(ay1, by1) > 1e-6:
                raise CadError("第 %d 层第 %d 个洞口与第 %d 个洞口位置重叠"
                               % (a["floor"], i + 1, j + 1))

    ax_tag: list[dict[str, Any]] = []
    for i, ax in enumerate(list(axes or ())):
        if isinstance(ax, dict):
            ax_x, ax_lab = float(ax.get("x", 0.0)), str(ax.get("label", "")).strip()
        elif isinstance(ax, (list, tuple)) and len(ax) >= 2:
            ax_x, ax_lab = float(ax[0]), str(ax[1]).strip()
        else:
            raise CadError("第 %d 个轴号必须是对象或 [x, 轴号]（收到 %r）" % (i + 1, ax))
        if not ax_lab:
            raise CadError("第 %d 个轴号的编号不能为空" % (i + 1))
        if ax_x < -1e-6 or ax_x > width + 1e-6:
            raise CadError("第 %d 个轴号位置 %s 超出立面宽度（0..%s）" % (i + 1, ax_x, width))
        ax_tag.append({"x": ax_x, "label": ax_lab})

    top = rows[-1]["elev"] + rows[-1]["height"]
    if roof_u == "FLAT":
        total_top = top + parapet
    elif roof_u in ("GABLE", "EAVE"):
        total_top = top + rise
    else:
        total_top = top

    session.ensure_layers([LAYERS["elev"], LAYERS["elevdetail"], LAYERS["name"],
                           LAYERS["axistext"]])
    sc = drawing_scale(session)
    lh = annot_size(3.0, sc)
    th = annot_size(2.5, sc)
    lev = LAYERS["elev"]
    det = LAYERS["elevdetail"]
    ext = annot_size(5.0, sc)

    def L(x1, y1, x2, y2, lay):
        return '(aa:mkline (aa:pt %.4f %.4f) (aa:pt %.4f %.4f) "%s")' % (x1, y1, x2, y2, lay)

    def eave_band(oh):
        """檐口板厚：檐口线下方再画一道板底线 + 两端封口（GB/T 50104 檐口要注厚度）。"""
        if eave <= 0:
            return
        code.append(L(-oh, top - eave, width + oh, top - eave, det))
        code.append(L(-oh, top, -oh, top - eave, det))
        code.append(L(width + oh, top, width + oh, top - eave, det))

    code: list[str] = []
    # 地坪线（两端出头）+ 两侧外轮廓（有女儿墙时轮廓到压顶）
    top_line = top + parapet if (roof_u == "FLAT" and parapet > 0) else top
    code.append(L(-ext, 0.0, width + ext, 0.0, lev))
    code.append(L(0.0, 0.0, 0.0, top_line, lev))
    code.append(L(width, 0.0, width, top_line, lev))
    # 楼层线（首层地面已有地坪线，其余每层楼面一条）
    for r in rows[1:]:
        code.append(L(0.0, r["elev"], width, r["elev"], det))
    # 屋顶
    if roof_u == "FLAT":
        oh = max(overhang, 0.0)
        if parapet > 0:
            # 女儿墙：与外墙同宽，只画压顶（不画挑檐，否则立面会长出一个大帽子）
            code.append(L(0.0, top + parapet, width, top + parapet, lev))
            cap = annot_size(1.5, sc)
            if parapet >= 2 * cap:
                code.append(L(0.0, top + parapet - cap, width, top + parapet - cap, det))
        else:
            code.append(L(-oh, top, width + oh, top, lev))     # 挑檐板线
            eave_band(oh)
    elif roof_u == "GABLE":
        oh = max(overhang, 0.0)
        code.append(L(-oh, top, width + oh, top, lev))               # 檐口
        code.append(L(-oh, top, width / 2.0, top + rise, lev))       # 左坡
        code.append(L(width / 2.0, top + rise, width + oh, top, lev))  # 右坡
        eave_band(oh)
    elif roof_u == "EAVE":
        # 正对檐口看（脊与图面平行）：只见檐口线 + 后方屋脊线，不出现山墙三角
        oh = max(overhang, 0.0)
        code.append(L(-oh, top, width + oh, top, lev))               # 檐口（含外挑）
        code.append(L(0.0, top + rise, width, top + rise, lev))      # 屋脊（被檐口挡住下半，投影为水平线）
        code.append(L(0.0, top, 0.0, top + rise, det))               # 两端山墙边（竖直）
        code.append(L(width, top, width, top + rise, det))
        eave_band(oh)
    # 门窗（天正立面做法：洞口 + 窗框双线 + 中梃分扇 + 上部亮子 + 窗台线）
    frame = 60.0           # 窗框在立面上的可见宽度（构造值，不随比例变）
    for k, op in enumerate(ops):
        base = rows[op["floor"] - 1]["elev"] + op["sill"]
        y2 = base + op["h"]
        x1, x2 = op["x"], op["x"] + op["w"]
        # 洞口外轮廓
        code.append(L(x1, base, x2, base, det))
        code.append(L(x2, base, x2, y2, det))
        code.append(L(x2, y2, x1, y2, det))
        code.append(L(x1, y2, x1, base, det))
        if op["w"] > 2 * frame and op["h"] > 2 * frame:
            # 窗框内线（四周内缩 frame）
            fx1, fx2 = x1 + frame, x2 - frame
            fy1, fy2 = base + frame, y2 - frame
            code.append(L(fx1, fy1, fx2, fy1, det))
            code.append(L(fx2, fy1, fx2, fy2, det))
            code.append(L(fx2, fy2, fx1, fy2, det))
            code.append(L(fx1, fy2, fx1, fy1, det))
            # 上部亮子横线（窗：亮窗高 600 或 1/3 洞高取小；门：门扇高固定 2100，
            #  只有洞高超过 2100 才有亮子，否则不画横线——2100 高的门再画一条横线就成了窗）
            if op["kind"] == "WINDOW":
                # 竖向中梃（分扇）：两扇居中一条，宽窗按 1.2m 分格
                head = min(600.0, op["h"] / 3.0)
                hy = y2 - head
                if hy > base + frame + 100.0:
                    code.append(L(fx1, hy, fx2, hy, det))
                panes = max(2, int(round(op["w"] / 1200.0)) or 2)
                for m in range(1, panes):
                    mx = x1 + op["w"] * m / panes
                    code.append(L(mx, fy1, mx, fy2, det))
                # 窗台线：比洞口每侧宽出 60
                code.append(L(x1 - frame, base, x2 + frame, base, det))
            else:
                # 门：门扇 2100，洞高超过 2100 + 100 才画门上亮子线
                if op["h"] > 2200.0:
                    code.append(L(fx1, base + 2100.0, fx2, base + 2100.0, det))
                # 双扇中缝；单扇（<900）画门扇上冒头线
                if op["w"] >= 900.0:
                    code.append(L((x1 + x2) / 2.0, fy1, (x1 + x2) / 2.0, fy2, det))
                else:
                    code.append(L(fx1, base + op["h"] * 0.62, fx2,
                                  base + op["h"] * 0.62, det))
    # 标高（右侧，尖端对着楼层线）
    if marks:
        mx = width + annot_size(8.0, sc)
        if ax_tag and any(abs(t["x"] - width) <= 1e-6 for t in ax_tag):
            # 右端有轴号时把标高列再右移一个轴号圈的宽度，免得三角和圆圈压在一起
            mx += 4 * annot_size(4.0, sc)
        for r in rows:
            code.append('(aa:elev %.4f %.4f "%s" %.4f %.4f)'
                        % (mx, r["elev"], format_elevation(r["elev"] / 1000.0), lh, th))
        if roof_u in ("GABLE", "EAVE"):
            # 檐口 + 屋脊两个标高，和楼层标高排在同一条竖列
            code.append('(aa:elev %.4f %.4f "%s" %.4f %.4f)'
                        % (mx, top, format_elevation(top / 1000.0), lh, th))
            code.append('(aa:elev %.4f %.4f "%s" %.4f %.4f)'
                        % (mx, top + rise,
                           format_elevation((top + rise) / 1000.0), lh, th))

    # 轴号（顶部外，圈下短引线接到立面轮廓顶；立面不画通长轴线）
    if ax_tag:
        r_ax = annot_size(4.0, sc)          # 圆半径 4mm => 直径 8mm（GB/T 50001）
        h_ax = annot_size(3.0, sc)          # 圈内轴号字高 3mm
        gap = annot_size(4.0, sc)
        code.append("(setq aa:*axis-r* %.4f)" % r_ax)
        code.append("(setq aa:*axis-h* %.4f)" % h_ax)
        for tag in ax_tag:
            code.append(L(tag["x"], total_top, tag["x"], total_top + gap, LAYERS["axistext"]))
            code.append('(aa:axistag %.4f %.4f "%s")'
                        % (tag["x"], total_top + gap + r_ax, tag["label"]))

    session.ensure_layers([LAYERS["sheet"], LAYERS["name"]])
    before = session.snapshot()
    session.lisp(" ".join(code),
                 libraries=("aa_core.lisp", "aa_axis.lisp", "aa_symbol.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("立面没有生成任何图元")

    rows_txt = "~".join("%s~%.4f~%.4f" % (r["no"], r["elev"], r["height"]) for r in rows)
    att_defs = [
        ("AA_TYPE", "component type", "ELEVATION"),
        ("AA_ID", "component id", elev_id),
        ("AA_W", "facade width", "%.4f" % width),
        ("AA_FLOORS", "floor count", str(len(rows)),
        ),
        ("AA_ROWS", "floor rows", rows_txt),
        ("AA_TOP", "top elevation", "%.4f" % top),
        ("AA_TOTAL", "total height incl roof", "%.4f" % total_top),
        ("AA_ROOF", "roof kind", roof_u),
        ("AA_PARAPET", "parapet height", "%.4f" % (parapet if roof_u == "FLAT" else 0.0)),
        ("AA_RISE", "gable rise", "%.4f" % (rise if roof_u in ("GABLE", "EAVE") else 0.0)),
        ("AA_OVERHANG", "eave overhang", "%.4f" % overhang),
        ("AA_OPENINGS", "opening count", str(len(ops))),
        ("AA_AXES", "axis labels", ";".join(t["label"] for t in ax_tag)),
        ("AA_EAVE", "eave thickness", "%.4f" % eave),
        ("AA_ANGLE", "rotation deg", "%.4f" % angle),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (float(at[0]), float(at[1])), att_vals,
                            rotation=angle, layer=LAYERS["elev"])
    session.expect_attributes(block, {"AA_TYPE": "ELEVATION", "AA_ID": elev_id,
                                      "AA_ROOF": roof_u,
                                      "AA_FLOORS": str(len(rows))})

    # 左侧三道竖向尺寸（GB/T 50104：立面必须注高度尺寸）
    dim_n = 0
    if dims:
        ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))

        def W(x, y):
            return (float(at[0]) + x * ca - y * sa, float(at[1]) + x * sa + y * ca)

        session.ensure_layers([LAYERS["dim"]])
        session.ensure_dim_style(text_height=annot_size(2.5, sc),
                                 arrow_size=annot_size(1.5, sc),
                                 ext_offset=annot_size(1.0, sc))
        ys_a = [0.0] + [r["elev"] for r in rows] + [top]
        for op in ops:
            b = rows[op["floor"] - 1]["elev"]
            ys_a += [b + op["sill"], b + op["sill"] + op["h"]]
        dim_n += _dim_chain(session, W, ys_a, annot_size(9.0, sc), angle,
                            True, annot_size(5.0, sc))
        # 中道把女儿墙/脊高也带上，否则 1200 的女儿墙或 1800 的脊高在立面上一段都没注
        dim_n += _dim_chain(session, W,
                            [0.0] + [r["elev"] for r in rows] + [top, total_top],
                            annot_size(16.0, sc), angle)
        dim_n += _dim_chain(session, W, [0.0, total_top], annot_size(23.0, sc), angle)

    return {"block": block, "handle": handle, "width": width,
            "floors": len(rows), "top": top, "total": total_top,
            "roof": roof_u, "openings": len(ops), "angle": angle,
            "eave": eave, "axes": [t["label"] for t in ax_tag], "dims": dim_n,
            "rows": rows, "geom_handles": handles}


def create_section(
    session: Session,
    section_id: str,
    at: tuple[float, float],
    width: float,
    floors: Sequence[Any],
    openings: Sequence[dict[str, Any]] = (),
    side: str = "BOTH",
    slab: float = 100.0,
    roof: str = "FLAT",
    parapet: float = 1200.0,
    rise: float = 0.0,
    wall: float = 240.0,
    marks: bool = True,
    angle: float = 0.0,
    inner_walls: Sequence[dict[str, Any]] = (),
    beams: Sequence[dict[str, Any]] = (),
    stairs: Sequence[dict[str, Any]] = (),
    dims: bool = True,
) -> dict[str, Any]:
    """建筑剖面（GB/T 50104 剖面图做法）：剖到的地坪、楼板、屋面板、外墙、女儿墙/坡屋面。

    `at` = 剖面左端室内地坪点（±0.000）；`width` = 剖面宽（两端墙内皮之间）；
    `floors` 同 `create_elevation`；`slab` 楼板厚（默认 100）；`wall` 外墙厚。
    `side`：BOTH（默认）= 剖切面穿过两端外墙，两端都按墙厚画成被剖的窄带（带门窗断口）；
    LEFT / RIGHT 为特殊需求下的"半剖"——只画那一端的墙带，另一端按看到的内表面画细线。
    `openings` = 剖到的门窗 `[{floor, h, sill, kind, side?}]`：在墙带上断开墙线，
    画窗框双线 + 玻璃（窗）或门上亮子（门）；`side` 默认 LEFT（另一端给 RIGHT）。
    `roof`：FLAT 平屋顶（屋面板 + 女儿墙）/ GABLE 双坡（斜屋面板 + 脊）/ NONE。
    `inner_walls` = 被剖切面切到的室内隔墙 `[{x, thick}]`：x 是剖面局部坐标（从 at 起算），
    画成同宽的墙带（贯穿到墙顶，不做洞口）。
    `beams` = 梁 `[{floor, x0, x1, h}]`：从该层楼板底往下返 h，画梁侧两条竖线 + 梁底线。
    `stairs` = 楼梯断面 `[{floor, x0, x1, treads}]`：从 floor 层楼面爬到上一层，踏步
    逐级画"一平一竖"，再加一条梯段板斜线（板厚取楼板厚）与两端收头。
    剖面暂不画基础、材料图例。
    `dims=True`（默认）在左侧注三道竖向尺寸（洞口/层高/总高，口径同立面）并在
    底部注一道横向尺寸（墙厚 + 净宽 + 隔墙/楼梯分段），全部落 AA-DIM。
    """
    block = "AA_SECTION_" + section_id
    if session.block_exists(block):
        raise CadError("剖面 %s 已存在，请换编号" % section_id)
    width = float(width)
    if width <= 0:
        raise CadError("拒绝写入：剖面宽度必须为正实数（收到 %s）" % width)
    rows = _norm_floors(floors)
    roof_u = str(roof).upper()
    if roof_u not in SECTION_ROOFS:
        raise CadError("剖面屋顶形式只能是 FLAT / GABLE / NONE（收到 %r）" % roof)
    slab, parapet, rise, wall = float(slab), float(parapet), float(rise), float(wall)
    if slab <= 0:
        raise CadError("拒绝写入：楼板厚必须为正（收到 %s）" % slab)
    if wall <= 0:
        raise CadError("拒绝写入：外墙厚必须为正（收到 %s）" % wall)
    if wall * 2 >= width:
        raise CadError("拒绝写入：外墙厚 %s 太大，剖面已经没有净宽（%s）" % (wall, width))
    if roof_u == "FLAT" and parapet < 0:
        raise CadError("拒绝写入：女儿墙高不能为负（收到 %s）" % parapet)
    if roof_u == "GABLE" and rise <= 0:
        raise CadError("拒绝写入：双坡屋脊高必须为正（收到 %s）" % rise)
    angle = float(angle) % 360.0

    top = rows[-1]["elev"] + rows[-1]["height"]
    roof_bottom = top
    roof_top = top + slab
    if roof_u == "FLAT":
        total_top = roof_top + parapet
    elif roof_u == "GABLE":
        total_top = top + rise + slab
    else:
        total_top = roof_top

    session.ensure_layers([LAYERS["elev"], LAYERS["elevdetail"], LAYERS["name"]])
    sc = drawing_scale(session)
    lh = annot_size(3.0, sc)
    th = annot_size(2.5, sc)
    lev = LAYERS["elev"]
    det = LAYERS["elevdetail"]
    ext = annot_size(5.0, sc)

    # 剖到的门窗：只给层号/高/窗台高/类型/侧别，竖向位置由层高定。
    # 剖切面穿过两端外墙，两端都是"被剖到"，各自可挂洞口。
    ops_cut: list[dict[str, Any]] = []
    cut = str(side).upper()
    if cut not in ("BOTH", "LEFT", "RIGHT"):
        raise CadError("剖面 side 只能是 BOTH / LEFT / RIGHT（收到 %r）" % side)
    for i, op in enumerate(openings or ()):
        if not isinstance(op, dict):
            raise CadError("剖面门窗必须是对象（收到 %r）" % (op,))
        fl = int(op.get("floor", 1) or 1)
        if not (1 <= fl <= len(rows)):
            raise CadError("第 %d 个剖面洞口层号 %s 超出 1..%d" % (i + 1, fl, len(rows)))
        hh, sill = float(op.get("h", 0.0)), float(op.get("sill", 0.0))
        if hh <= 0:
            raise CadError("第 %d 个剖面洞口高必须为正（收到 %s）" % (i + 1, hh))
        if sill < 0:
            raise CadError("第 %d 个剖面洞口窗台高不能为负（收到 %s）" % (i + 1, sill))
        if sill + hh > rows[fl - 1]["height"] + 1e-6:
            raise CadError("第 %d 个剖面洞口高出本层：sill %s + h %s > 层高 %s"
                           % (i + 1, sill, hh, rows[fl - 1]["height"]))
        kd = str(op.get("kind", "WINDOW")).upper()
        if kd not in ("WINDOW", "DOOR"):
            raise CadError("第 %d 个剖面洞口类型只能是 WINDOW / DOOR（收到 %r）" % (i + 1, kd))
        sd = str(op.get("side", "LEFT")).upper()
        if sd not in ("LEFT", "RIGHT"):
            raise CadError("第 %d 个剖面洞口侧别只能是 LEFT / RIGHT（收到 %r）" % (i + 1, sd))
        if cut != "BOTH" and sd != cut:
            raise CadError("第 %d 个剖面洞口在 %s 侧，但只画了 %s 端的墙带："
                           "那一端的墙没有剖开，不能落洞口（用 side=BOTH，或删掉这个洞口）"
                           % (i + 1, sd, cut))
        ops_cut.append({"kind": kd, "h": hh, "side": sd,
                        "elev0": rows[fl - 1]["elev"] + sill,
                        "elev1": rows[fl - 1]["elev"] + sill + hh})
    # 同侧洞口不得竖向重叠（不同侧是两道墙，各自独立）
    for a in range(len(ops_cut)):
        for b in range(a + 1, len(ops_cut)):
            if ops_cut[a]["side"] != ops_cut[b]["side"]:
                continue
            if min(ops_cut[a]["elev1"], ops_cut[b]["elev1"]) - \
                    max(ops_cut[a]["elev0"], ops_cut[b]["elev0"]) > 1e-6:
                raise CadError("剖面%s侧同一道墙上有两个洞口竖向重叠（%s 与 %s）"
                               % ("左" if ops_cut[a]["side"] == "LEFT" else "右",
                                  ops_cut[a]["elev0"], ops_cut[b]["elev0"]))

    # 被剖到的室内隔墙：只给位置与厚度，贯穿墙顶；可挂剖到的门窗
    iwalls: list[dict[str, Any]] = []
    for i, wd in enumerate(inner_walls or ()):
        if not isinstance(wd, dict):
            raise CadError("剖面隔墙必须是对象（收到 %r）" % (wd,))
        x = float(wd.get("x", 0.0))
        t = float(wd.get("thick", 120.0))
        if t <= 0:
            raise CadError("第 %d 道剖面隔墙厚度必须为正（收到 %s）" % (i + 1, t))
        if x < wall - 1e-6 or x + t > width - wall + 1e-6:
            raise CadError("第 %d 道剖面隔墙 [%.4f, %.4f] 压在外墙上（净宽 %.4f..%.4f）"
                           % (i + 1, x, x + t, wall, width - wall))
        for other in iwalls:
            if min(x + t, other["x"] + other["thick"]) - max(x, other["x"]) > 1e-6:
                raise CadError("第 %d 道剖面隔墙与已有隔墙在剖面上重叠" % (i + 1))
        iops: list[dict[str, Any]] = []
        for k, op in enumerate(wd.get("openings", []) or ()):
            if not isinstance(op, dict):
                raise CadError("第 %d 道隔墙的第 %d 个洞口必须是对象" % (i + 1, k + 1))
            fl = int(op.get("floor", 1) or 1)
            if not (1 <= fl <= len(rows)):
                raise CadError("第 %d 道隔墙第 %d 个洞口层号 %s 超出 1..%d"
                               % (i + 1, k + 1, fl, len(rows)))
            hh, sill = float(op.get("h", 0.0)), float(op.get("sill", 0.0))
            if hh <= 0:
                raise CadError("第 %d 道隔墙第 %d 个洞口高必须为正（收到 %s）" % (i + 1, k + 1, hh))
            if sill < 0:
                raise CadError("第 %d 道隔墙第 %d 个洞口窗台高不能为负" % (i + 1, k + 1))
            if sill + hh > rows[fl - 1]["height"] + 1e-6:
                raise CadError("第 %d 道隔墙第 %d 个洞口高出本层：sill %s + h %s > 层高 %s"
                               % (i + 1, k + 1, sill, hh, rows[fl - 1]["height"]))
            kd = str(op.get("kind", "WINDOW")).upper()
            if kd not in ("WINDOW", "DOOR"):
                raise CadError("第 %d 道隔墙第 %d 个洞口类型只能是 WINDOW / DOOR" % (i + 1, k + 1))
            iops.append({"kind": kd, "h": hh, "sill": sill,
                         "elev0": rows[fl - 1]["elev"] + sill,
                         "elev1": rows[fl - 1]["elev"] + sill + hh})
        for a in range(len(iops)):
            for b in range(a + 1, len(iops)):
                if min(iops[a]["elev1"], iops[b]["elev1"]) - \
                        max(iops[a]["elev0"], iops[b]["elev0"]) > 1e-6:
                    raise CadError("第 %d 道隔墙上的两个洞口竖向重叠" % (i + 1))
        iwalls.append({"x": x, "thick": t, "ops": iops})

    # 梁：挂在楼板底，从 x0 到 x1
    bms: list[dict[str, Any]] = []
    for i, bm in enumerate(beams or ()):
        if not isinstance(bm, dict):
            raise CadError("剖面梁必须是对象（收到 %r）" % (bm,))
        fl = int(bm.get("floor", 1) or 1)
        if not (2 <= fl <= len(rows)):
            raise CadError("第 %d 根梁的层号 %s 越界：梁只能挂在不低于二层的楼板上（1..%d 不含首层）"
                           % (i + 1, fl, len(rows)))
        x0, x1 = float(bm.get("x0", 0.0)), float(bm.get("x1", 0.0))
        hb = float(bm.get("h", 500.0))
        if hb <= 0:
            raise CadError("第 %d 根梁高必须为正（收到 %s）" % (i + 1, hb))
        if x1 - x0 <= 1e-6:
            raise CadError("第 %d 根梁的 x1 必须大于 x0（收到 %s / %s）" % (i + 1, x0, x1))
        if x0 < -1e-6 or x1 > width + 1e-6:
            raise CadError("第 %d 根梁超出剖面宽度（%s..%s / %.4f）" % (i + 1, x0, x1, width))
        bms.append({"floor": fl, "x0": x0, "x1": x1, "h": hb})

    # 楼梯断面：一跑梯段，从 floor 层楼面爬到上一层的楼面
    sts: list[dict[str, Any]] = []
    for i, st in enumerate(stairs or ()):
        if not isinstance(st, dict):
            raise CadError("剖面楼梯必须是对象（收到 %r）" % (st,))
        fl = int(st.get("floor", 1) or 1)
        if not (1 <= fl < len(rows)):
            raise CadError("第 %d 跑楼梯的起层 %s 越界：楼梯要跨到上一层（1..%d）"
                           % (i + 1, fl, len(rows) - 1))
        x0, x1 = float(st.get("x0", 0.0)), float(st.get("x1", 0.0))
        n = int(st.get("treads", 10) or 10)
        if n < 2:
            raise CadError("第 %d 跑楼梯踏步数至少 2（收到 %s）" % (i + 1, n))
        if x1 - x0 <= 1e-6:
            raise CadError("第 %d 跑楼梯的 x1 必须大于 x0（收到 %s / %s）" % (i + 1, x0, x1))
        if x0 < wall - 1e-6 or x1 > width - wall + 1e-6:
            raise CadError("第 %d 跑楼梯 [%.4f, %.4f] 出了净宽 %.4f..%.4f"
                           % (i + 1, x0, x1, wall, width - wall))
        sts.append({"floor": fl, "x0": x0, "x1": x1, "treads": n})

    def L(x1, y1, x2, y2, lay):
        return '(aa:mkline (aa:pt %.4f %.4f) (aa:pt %.4f %.4f) "%s")' % (x1, y1, x2, y2, lay)

    code: list[str] = []
    # 室内地坪（两端出头）
    code.append(L(-ext, 0.0, width + ext, 0.0, lev))

    # 剖切面穿过两端外墙：默认两端都画墙厚窄带（遇洞口断墙）；
    # side=LEFT/RIGHT 是"半剖"的特殊需求，另一端只画看到的内表面一条细线。
    frame_s = 60.0
    cut_left = cut in ("BOTH", "LEFT")
    cut_right = cut in ("BOTH", "RIGHT")
    gaps = {"LEFT": [(o["elev0"], o["elev1"]) for o in ops_cut if o["side"] == "LEFT"],
            "RIGHT": [(o["elev0"], o["elev1"]) for o in ops_cut if o["side"] == "RIGHT"]}

    def wall_segments(x, gaps_):
        out = []
        cursor = 0.0
        for g0, g1 in sorted(gaps_):
            if g0 > cursor + 1e-6:
                out.append(L(x, cursor, x, g0, lev))
            cursor = max(cursor, g1)
        if cursor < top - 1e-6:
            out.append(L(x, cursor, x, top, lev))
        return out

    if cut_left:
        code += wall_segments(0.0, gaps["LEFT"]) + wall_segments(wall, gaps["LEFT"])
    else:
        code.append(L(wall, 0.0, wall, top, det))          # 看到的对面墙内表面
    if cut_right:
        code += wall_segments(width - wall, gaps["RIGHT"]) + wall_segments(width, gaps["RIGHT"])
    else:
        code.append(L(width - wall, 0.0, width - wall, top, det))

    # 被剖到的室内隔墙：同宽窄带，从地坪贯到墙顶；带门窗时按洞口断墙
    for iw in iwalls:
        g_iw = [(o["elev0"], o["elev1"]) for o in iw["ops"]]
        code += wall_segments(iw["x"], g_iw) + wall_segments(iw["x"] + iw["thick"], g_iw)

    # 剖到的门窗：洞口上下封口 + 窗框双线 + 玻璃 / 门扇冒头线 + 窗台板向室内挑出
    def cut_opening(x0, x1, prot, op):
        b, t2 = op["elev0"], op["elev1"]
        if b > 1e-6:
            code.append(L(x0, b, x1, b, det))
        code.append(L(x0, t2, x1, t2, det))
        framed = x1 - x0 > 2 * frame_s
        if framed:
            code.append(L(x0 + frame_s, b, x0 + frame_s, t2, det))
            code.append(L(x1 - frame_s, b, x1 - frame_s, t2, det))
        if op["kind"] == "WINDOW":
            if framed:
                code.append(L((x0 + x1) / 2.0, b, (x0 + x1) / 2.0, t2, det))
            # 窗台板向室内挑出 60，剖面上一眼能认出是窗
            code.append(L(x0, b, x1 + prot * 60.0, b, det))
        else:
            # 门扇上冒头线（薄墙也能认出是门）
            hy = t2 - min(500.0, op["h"] / 4.0)
            left = x0 + frame_s if framed else x0
            right = x1 - frame_s if framed else x1
            code.append(L(left, hy, right, hy, det))

    boxes = {"LEFT": (0.0, wall, 1.0), "RIGHT": (width - wall, width, -1.0)}
    for op in ops_cut:
        x0, x1, prot = boxes[op["side"]]
        cut_opening(x0, x1, prot, op)
    for iw in iwalls:
        for op in iw["ops"]:
            cut_opening(iw["x"], iw["x"] + iw["thick"], 1.0, op)

    # 楼板（每层楼面一条板顶 + 一条板底；首层地面即地坪，不重复）
    # 两端被剖到的墙之间净宽内画，不穿进墙带
    x_lo, x_hi = wall, width - wall
    for r in rows[1:]:
        code.append(L(x_lo, r["elev"], x_hi, r["elev"], lev))
        code.append(L(x_lo, r["elev"] - slab, x_hi, r["elev"] - slab, det))
    # 梁：楼板底下返 h，画两条梁侧线 + 一条梁底线
    for bm in bms:
        e = rows[bm["floor"] - 1]["elev"]
        bt = e - slab - bm["h"]
        code.append(L(bm["x0"], e - slab, bm["x0"], bt, det))
        code.append(L(bm["x1"], e - slab, bm["x1"], bt, det))
        code.append(L(bm["x0"], bt, bm["x1"], bt, det))
    # 楼梯断面：踏步逐级（每级一平一竖两条线）+ 梯段板斜线 + 两端收头
    for st in sts:
        y0 = rows[st["floor"] - 1]["elev"]
        hs = rows[st["floor"] - 1]["height"]
        run = (st["x1"] - st["x0"]) / st["treads"]
        rsr = hs / st["treads"]
        x = st["x0"]
        y = y0
        for _k in range(st["treads"]):
            code.append(L(x, y, x + run, y, det))
            code.append(L(x + run, y, x + run, y + rsr, det))
            x += run
            y += rsr
        # 梯段板：斜线距踏步线一个板厚（用楼板厚），两端各一条竖线收头
        th0 = max(slab, 100.0)
        code.append(L(st["x0"], y0 - th0, st["x1"], y0 + hs - th0, det))
        code.append(L(st["x0"], y0 - th0, st["x0"], y0, det))
        code.append(L(st["x1"], y0 + hs - th0, st["x1"], y0 + hs, det))
    # 屋面
    if roof_u == "FLAT":
        code.append(L(0.0, roof_bottom, width, roof_bottom, det))       # 屋面板底
        code.append(L(0.0, roof_top, width, roof_top, lev))            # 屋面板顶
        if parapet > 0:
            # 女儿墙：两端都是剖到的，画成窄矩形 + 压顶线
            cap = annot_size(1.5, sc)
            for outer, inner in ((0.0, wall), (width, width - wall)):
                code.append(L(outer, roof_top, outer, roof_top + parapet, lev))
                code.append(L(inner, roof_top, inner, roof_top + parapet, lev))
                code.append(L(outer, roof_top + parapet, inner, roof_top + parapet, lev))
                if parapet >= 2 * cap:
                    code.append(L(outer, roof_top + parapet - cap, inner,
                                  roof_top + parapet - cap, det))
    elif roof_u == "GABLE":
        code.append(L(0.0, roof_bottom, width / 2.0, roof_bottom + rise, det))
        code.append(L(width / 2.0, roof_bottom + rise, width, roof_bottom, det))
        code.append(L(0.0, roof_top, width / 2.0, roof_top + rise, lev))
        code.append(L(width / 2.0, roof_top + rise, width, roof_top, lev))
    # 标高（右侧）
    if marks:
        mx = width + annot_size(8.0, sc)
        for r in rows:
            code.append('(aa:elev %.4f %.4f "%s" %.4f %.4f)'
                        % (mx, r["elev"], format_elevation(r["elev"] / 1000.0), lh, th))
        # 檐口标高取墙顶（建筑标高），与立面口径一致；屋面板厚只体现在几何上
        code.append('(aa:elev %.4f %.4f "%s" %.4f %.4f)'
                    % (mx, top, format_elevation(top / 1000.0), lh, th))
        if roof_u == "GABLE":
            # 双坡：屋脊标高与檐口排在同一条竖列（不压在屋脊线上）
            code.append('(aa:elev %.4f %.4f "%s" %.4f %.4f)'
                        % (mx, top + rise,
                           format_elevation((top + rise) / 1000.0), lh, th))

    session.ensure_layers([LAYERS["sheet"], LAYERS["name"]])
    before = session.snapshot()
    session.lisp(" ".join(code), libraries=("aa_core.lisp", "aa_symbol.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("剖面没有生成任何图元")

    rows_txt = "~".join("%s~%.4f~%.4f" % (r["no"], r["elev"], r["height"]) for r in rows)
    att_defs = [
        ("AA_TYPE", "component type", "SECTION"),
        ("AA_ID", "component id", section_id),
        ("AA_W", "section width", "%.4f" % width),
        ("AA_FLOORS", "floor count", str(len(rows))),
        ("AA_ROWS", "floor rows", rows_txt),
        ("AA_TOP", "top elevation", "%.4f" % top),
        ("AA_TOTAL", "total height incl roof", "%.4f" % total_top),
        ("AA_ROOF", "roof kind", roof_u),
        ("AA_SLAB", "slab thickness", "%.4f" % slab),
        ("AA_WALL", "wall thickness", "%.4f" % wall),
        ("AA_PARAPET", "parapet height", "%.4f" % (parapet if roof_u == "FLAT" else 0.0)),
        ("AA_RISE", "gable rise", "%.4f" % (rise if roof_u in ("GABLE", "EAVE") else 0.0)),
        ("AA_OPENINGS", "cut openings", str(len(ops_cut))),
        ("AA_INWALLS", "cut inner walls", str(len(iwalls))),
        ("AA_BEAMS", "cut beams", str(len(bms))),
        ("AA_STAIRS", "cut stairs", str(len(sts))),
        ("AA_ANGLE", "rotation deg", "%.4f" % angle),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (float(at[0]), float(at[1])), att_vals,
                            rotation=angle, layer=LAYERS["elev"])
    session.expect_attributes(block, {"AA_TYPE": "SECTION", "AA_ID": section_id,
                                      "AA_ROOF": roof_u,
                                      "AA_FLOORS": str(len(rows))})

    # 尺寸：左侧三道竖向（洞口/层高/总高，口径同立面）+ 底部一道横向（墙厚/净宽/隔墙/楼梯）
    dim_n = 0
    if dims:
        ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))

        def W(x, y):
            return (float(at[0]) + x * ca - y * sa, float(at[1]) + x * sa + y * ca)

        session.ensure_layers([LAYERS["dim"]])
        session.ensure_dim_style(text_height=annot_size(2.5, sc),
                                 arrow_size=annot_size(1.5, sc),
                                 ext_offset=annot_size(1.0, sc))
        ys_a = [0.0] + [r["elev"] for r in rows] + [top]
        for o in ops_cut:
            ys_a += [o["elev0"], o["elev1"]]
        dim_n += _dim_chain(session, W, ys_a, annot_size(9.0, sc), angle,
                            True, annot_size(5.0, sc))
        dim_n += _dim_chain(session, W,
                            [0.0] + [r["elev"] for r in rows] + [top, total_top],
                            annot_size(16.0, sc), angle)
        dim_n += _dim_chain(session, W, [0.0, total_top], annot_size(23.0, sc), angle)

        # 横向细部只注内皮到内皮的分段（隔墙/楼梯）：墙厚 240 在 1:100 上只有 2.4mm，
        # 注上去数字挤成一团，墙厚交给 AA_WALL 属性与墙身详图
        xs_h = [wall, width - wall]
        for iw in iwalls:
            xs_h += [iw["x"], iw["x"] + iw["thick"]]
        for st in sts:
            xs_h += [st["x0"], st["x1"]]
        dim_n += _dim_chain(session, W, xs_h, annot_size(9.0, sc), angle, False,
                            min_len=annot_size(15.0, sc))
        # 底部第二道：总宽（0..width，含两端墙厚），与竖向的"总高"对应
        dim_n += _dim_chain(session, W, [0.0, width], annot_size(16.0, sc), angle, False)

    return {"block": block, "handle": handle, "width": width, "floors": len(rows),
            "top": top, "total": total_top, "roof": roof_u, "slab": slab,
            "wall": wall, "angle": angle, "rows": rows, "inner_walls": len(iwalls),
            "beams": len(bms), "stairs": len(sts), "dims": dim_n,
            "openings": len(ops_cut), "geom_handles": handles}


def create_room(
    session: Session,
    room_id: str,
    wall_ids: Sequence[str],
    name: str = "",
    tol: float = 1e-6,
    show_area: bool = True,
) -> dict[str, Any]:
    """房间：闭合墙环校验 -> 内偏移轮廓 -> block -> insert -> 回读校验。

    校验规则（spec §6.2）：
      1. 所列墙必须全部存在
      2. 相邻墙首尾相接（按墙的真实端点，允许反向）
      3. 最后一堵墙的终点必须回到第一堵墙的起点（闭合）
      4. 内偏移轮廓面积必须为正
    """
    segs = []
    thick = {}
    for wid in wall_ids:
        info = wall_info(session, wid)
        ang = info["rotation_rad"]
        u = (math.cos(ang), math.sin(ang))
        p1 = info["at"]
        p2 = (p1[0] + u[0] * info["length"], p1[1] + u[1] * info["length"])
        segs.append({"id": wid, "p1": p1, "p2": p2, "u": u})
        thick[wid] = info["thick"]

    # 串成闭合环（允许墙反向、允许窗口顺序与画向不一致：每次在剩余墙里找接得上的那堵）
    ring_pts = [segs[0]["p1"], segs[0]["p2"]]
    oriented = [segs[0]]
    rest = segs[1:]
    while rest:
        last = ring_pts[-1]
        hit = None
        for i, seg in enumerate(rest):
            if math.dist(last, seg["p1"]) <= 1.0:
                hit = (i, seg, seg["p2"], seg["u"])
                break
            if math.dist(last, seg["p2"]) <= 1.0:
                hit = (i, {**seg, "u": (-seg["u"][0], -seg["u"][1])},
                       seg["p1"], (-seg["u"][0], -seg["u"][1]))
                break
        if hit is None:
            raise CadError(
                "拒绝写入：墙环断裂，墙 %s 的端点与上一个终点不重合"
                % rest[0]["id"]
            )
        i, seg, nxt, u = hit
        rest.pop(i)
        ring_pts.append(nxt)
        oriented.append({**seg, "u": u})
    if math.dist(ring_pts[-1], ring_pts[0]) > 1.0:
        raise CadError("拒绝写入：墙环未闭合（末墙终点的偏差 %.4f）"
                       % math.dist(ring_pts[-1], ring_pts[0]))
    ring_pts = ring_pts[:-1]  # 去掉重复的闭合点
    edges = [(ring_pts[i], ring_pts[(i + 1) % len(ring_pts)], oriented[i]["id"])
             for i in range(len(ring_pts))]

    inner, area = _room_inner(edges, thick, tol)
    return _store_room(session, room_id, inner, area, wall_ids, name,
                       show_area=show_area)


def create_room_edges(session: Session, room_id: str,
                      edges: list[tuple[tuple[float, float], tuple[float, float], str]],
                      name: str = "", tol: float = 1e-6) -> dict[str, Any]:
    """由任意有序边界边建房间（自动搜环用：房间边界可能落在某堵墙的中段）。"""
    walls = [e[2] for e in edges]
    unique: list[str] = []
    for w in walls:
        if not unique or unique[-1] != w:
            unique.append(w)
    thick = {}
    for w in unique:
        thick[w] = wall_info(session, w)["thick"]
    inner, area = _room_inner(edges, thick, tol)
    return _store_room(session, room_id, inner, area, unique, name)


def delete_component(session: Session, block: str) -> bool:
    """删除块参照并清理其块定义（未被引用才允许清理）。"""
    ref = session.reference(block)
    if not ref:
        return False
    session.run(
        [
            ("erase", {"handles": [ref["handle"]]}),
            ("purge", {"type": "blocks", "names": block}),
        ],
        save=True,
    )
    return True


def wall_data(session: Session) -> list[dict[str, Any]]:
    """读取全部墙段（含端点、长度、厚度、逻辑根编号）。"""
    out = []
    for e in session.components("AA_WALL_"):
        g = e["geometry"]
        attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in g.get("attribs", [])}
        ang = g.get("rotation", 0.0)
        length = float(attrs.get("AA_LEN", "0") or 0)
        p1 = (g["insert"]["x"], g["insert"]["y"])
        p2 = (p1[0] + math.cos(ang) * length, p1[1] + math.sin(ang) * length)
        out.append(
            {
                "id": attrs.get("AA_ID") or g["block"][len("AA_WALL_"):],
                "block": g["block"],
                "p1": p1,
                "p2": p2,
                "len": length,
                "floor": int(float(attrs.get("AA_FLOOR") or 1)),
                "rotation_rad": ang,
                "thick": float(attrs.get("AA_THICK", "0") or 0),
                "kind": attrs.get("AA_KIND", ""),
                "mat": attrs.get("AA_MAT", ""),
                "ax1": attrs.get("AA_AX1", ""),
                "ax2": attrs.get("AA_AX2", ""),
                "root": attrs.get("AA_ROOT", ""),
            }
        )
    return out


def opening_data(session: Session) -> list[dict[str, Any]]:
    """读取全部门窗洞口（含所在墙的层号 AA_FLOOR，缺省按 1 层）。"""
    wall_floor: dict[str, int] = {}
    for e in session.components("AA_WALL_"):
        g = e["geometry"]
        attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in g.get("attribs", [])}
        wid = attrs.get("AA_ID") or g["block"][len("AA_WALL_"):]
        try:
            wall_floor[wid] = int(float(attrs.get("AA_FLOOR") or 1))
        except ValueError:
            wall_floor[wid] = 1
    out = []
    for e in session.components("AA_OPENING_"):
        g = e["geometry"]
        attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in g.get("attribs", [])}
        out.append(
            {
                "block": g["block"],
                "id": attrs.get("AA_ID") or g["block"][len("AA_OPENING_"):],
                "kind": attrs.get("AA_KIND", "DOOR"),
                "width": float(attrs.get("AA_WIDTH", "0") or 0),
                "height": float(attrs.get("AA_HEIGHT", "0") or 0),
                "sill": float(attrs.get("AA_SILL", "0") or 0),
                "wallid": attrs.get("AA_WALLID", ""),
                "pos": float(attrs.get("AA_POS", "0") or 0),
                "frame": float(attrs.get("AA_FRAME", "0") or 0),
                "no": attrs.get("AA_NO", ""),
                "labelside": attrs.get("AA_LABELSIDE", "in") or "in",
                "floor": wall_floor.get(attrs.get("AA_WALLID", ""), 1),
            }
        )
    return out


def read_facade_openings(
    session: Session,
    wall_id: str,
    flip: bool = False,
    floor: int = 1,
) -> list[dict[str, Any]]:
    """把平面上一道墙的门窗反解成立面可用的洞口清单（x 为洞口左边距）。

    `AA_POS` 是"洞口中心到墙起点的距离"，所以左边距要减掉半个洞宽：
      · 墙的起点在人的左手边 → flip=False，x = AA_POS - 洞宽/2；
      · 墙的起点在人的右手边（如朝北的墙，从左往右看是墙的终点）→ flip=True，
        x = 墙长 - AA_POS - 洞宽/2。
    这样立面门窗位置与平面是同一套数据，不用手填坐标。
    """
    info = wall_info(session, wall_id)
    length = float(info["length"])
    out: list[dict[str, Any]] = []
    for o in opening_data(session):
        if o["wallid"] != wall_id:
            continue
        w = float(o["width"])
        half = w / 2.0
        x = (length - float(o["pos"]) - half) if flip else (float(o["pos"]) - half)
        out.append({"floor": int(floor), "x": x, "w": w,
                    "h": float(o["height"]), "sill": float(o["sill"]),
                    "kind": o["kind"], "no": o["no"]})
    out.sort(key=lambda d: d["x"])
    return out


def read_cut_openings(
    session: Session,
    p1: tuple[float, float],
    p2: tuple[float, float],
    floor: int = 1,
    tol: float = 1.0,
    walls: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """沿剖切线找被切到的墙与洞口，直接给 `create_section` 的 `openings`。

    `p1` = 剖面图上左端在平面上的对应点，`p2` = 右端对应点（剖切符号的两个端点）。
    剖切线穿过墙身时，才把墙上的门窗算进来；洞口被切到（切点落在洞口宽度内）才出。
    侧别按"离 p1 近还是离 p2 近"判：近 p1 → LEFT，近 p2 → RIGHT。
    `walls` 可只取其中几道墙（如只取两端外墙、把隔墙留给 `inner_walls`）。
    """
    a, b = (float(p1[0]), float(p1[1])), (float(p2[0]), float(p2[1]))
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        raise CadError("剖切线的两个端点重合了，给不出剖切方向")
    ux, uy = dx / length, dy / length

    ops_all = opening_data(session)
    pick = set(walls) if walls else None
    out: list[dict[str, Any]] = []
    for e in session.components("AA_WALL_"):
        wid = e["geometry"]["block"][len("AA_WALL_"):]
        if pick is not None and wid not in pick:
            continue
        info = wall_info(session, wid)
        wl = float(info["length"])
        if wl <= 1e-9:
            continue
        ang = info["rotation_rad"]
        wu = (math.cos(ang), math.sin(ang))
        w0 = info["at"]
        w1 = (w0[0] + wu[0] * wl, w0[1] + wu[1] * wl)
        # 两线段求交（参数式），交点同时在两段之内才算"切到"
        den = dx * (w1[1] - w0[1]) - dy * (w1[0] - w0[0])
        if abs(den) < 1e-9:
            continue
        t = ((w0[0] - a[0]) * (w1[1] - w0[1]) - (w0[1] - a[1]) * (w1[0] - w0[0])) / den
        s = ((w0[0] - a[0]) * dy - (w0[1] - a[1]) * dx) / den
        px, py = a[0] + dx * t, a[1] + dy * t
        if not (0.0 <= s <= 1.0):
            continue
        if math.hypot(px - w0[0], py - w0[1]) > wl + tol:
            continue
        along = s * wl
        side = "LEFT" if math.hypot(px - a[0], py - a[1]) <= \
            math.hypot(px - b[0], py - b[1]) else "RIGHT"
        for o in ops_all:
            if o["wallid"] != wid:
                continue
            half = float(o["width"]) / 2.0
            if abs(along - float(o["pos"])) > half + tol:
                continue                       # 切在墙身上、没切进洞口
            kd = "WINDOW" if str(o["kind"]).upper() in ("WINDOW", "DOORWIN") else "DOOR"
            out.append({"floor": int(floor), "h": float(o["height"]),
                        "sill": float(o["sill"]), "kind": kd, "side": side,
                        "no": o["no"], "wall": wid})
    out.sort(key=lambda d: (d["side"], d["sill"]))
    return out


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy)
    return (dx / d, dy / d) if d > 1e-12 else (1.0, 0.0)


def _clip_seg_rect(xa, ya, xb, yb, xmin, xmax, ymin, ymax):
    """Liang-Barsky：返回线段落在矩形内的参数区间 (t0, t1)，不在则 None。"""
    dx, dy = xb - xa, yb - ya
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, xa - xmin), (dx, xmax - xa), (-dy, ya - ymin), (dy, ymax - ya)):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r
    if t0 > t1:
        return None
    return (t0, t1)


def _complement(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """[0,1] 上挖掉若干区间后的剩余区间。"""
    out = []
    cur = 0.0
    for a, b in sorted(intervals):
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    if cur < 1.0:
        out.append((cur, 1.0))
    return out


def wall_sides(seg: dict, obstacles: list[dict],
               holes: list[tuple[float, float]] | None = None,
               tol: float = 1e-9) -> list[tuple[float, float, float, float]]:
    """计算墙两侧线（已裁剪掉落在其它墙体实心范围内的一段），返回局部坐标四元组。

    seg / obstacles 均为 {p1, p2, thick}。返回 (x1,y1,x2,y2)，局部坐标：
    原点=墙起点，+X=墙方向，+Y=左手法向。
    holes 为门窗洞口区间（局部 X 距离，[from, to]），洞口处同样让出缺口。
    """
    p1, p2, t = seg["p1"], seg["p2"], seg["thick"]
    length = math.dist(p1, p2)
    if length < 1e-9:
        return []
    u = _unit(p1, p2)
    n = (-u[1], u[0])
    hole_iv = []
    for a, b in (holes or []):
        lo, hi = max(0.0, min(a, b)), min(length, max(a, b))
        if hi - lo > tol:
            hole_iv.append((lo / length, hi / length))
    out = []
    for sign in (1.0, -1.0):
        a = (p1[0] + n[0] * sign * t / 2.0, p1[1] + n[1] * sign * t / 2.0)
        b = (p2[0] + n[0] * sign * t / 2.0, p2[1] + n[1] * sign * t / 2.0)
        removed = list(hole_iv)
        for ob in obstacles:
            if ob is seg:
                continue
            ub = _unit(ob["p1"], ob["p2"])
            # 共线邻墙不裁剪（同一道直墙的延续）
            if abs(u[0] * ub[1] - u[1] * ub[0]) < 1e-9:
                continue
            ob_len = math.dist(ob["p1"], ob["p2"])
            q1 = ob["p1"]
            oy = (-ub[1], ub[0])
            ax = (a[0] - q1[0]) * ub[0] + (a[1] - q1[1]) * ub[1]
            ay = (a[0] - q1[0]) * oy[0] + (a[1] - q1[1]) * oy[1]
            bx = (b[0] - q1[0]) * ub[0] + (b[1] - q1[1]) * ub[1]
            by = (b[0] - q1[0]) * oy[0] + (b[1] - q1[1]) * oy[1]
            iv = _clip_seg_rect(ax, ay, bx, by, 0.0, ob_len, -ob["thick"] / 2.0, ob["thick"] / 2.0)
            if iv and iv[1] - iv[0] > tol:
                removed.append(iv)
        for s0, s1 in _complement(removed):
            if s1 - s0 < 1e-6:
                continue
            pa = _lerp(a, b, s0)
            pb = _lerp(a, b, s1)
            la = ((pa[0] - p1[0]) * u[0] + (pa[1] - p1[1]) * u[1],
                  (pa[0] - p1[0]) * n[0] + (pa[1] - p1[1]) * n[1])
            lb = ((pb[0] - p1[0]) * u[0] + (pb[1] - p1[1]) * u[1],
                  (pb[0] - p1[0]) * n[0] + (pb[1] - p1[1]) * n[1])
            out.append((la[0], la[1], lb[0], lb[1]))

    # 转角合角：外侧墙线延伸到邻墙外墙面（否则角部会留半个墙厚的缺口）
    oh_start = [_corner_overhang(seg, p1, s, obstacles) for s in (1.0, -1.0)]
    oh_end = [_corner_overhang(seg, p2, s, obstacles) for s in (1.0, -1.0)]
    for sign, oh0, oh1 in ((1.0, oh_start[0], oh_end[0]), (-1.0, oh_start[1], oh_end[1])):
        idx = [i for i, s in enumerate(out) if abs(s[1] - sign * t / 2.0) < 1e-6]
        if not idx:
            continue
        idx.sort(key=lambda i: out[i][0])
        if oh0 > 0 and abs(out[idx[0]][0]) <= 1e-6:
            x1, y1, x2, y2 = out[idx[0]]
            out[idx[0]] = (x1 - oh0, y1, x2, y2)
        if oh1 > 0 and abs(out[idx[-1]][2] - math.dist(p1, p2)) <= 1e-6:
            x1, y1, x2, y2 = out[idx[-1]]
            out[idx[-1]] = (x1, y1, x2 + oh1, y2)
    return out


def _corner_overhang(seg: dict, end_pt, sign: float, obstacles: list[dict],
                     tol: float = CORNER_TOL) -> float:
    """端点与垂直邻墙端部相接（转角）时，该侧墙线需向外延伸的距离。

    判据：自身端点落在邻墙矩形上（含边界），而该侧端点在邻墙矩形之外；
    满足则延伸到邻墙外墙面，距离取邻墙半厚。

    容差用 0.01 mm：墙方向由 atan 回算，端点坐标会有 ~1e-5 mm 的漂移，
    用 1e-9 的严格容差会把转角误判成"端点不在邻墙上"，导致漏合角（实测踩过）。
    """
    p1, p2, t = seg["p1"], seg["p2"], seg["thick"]
    u = _unit(p1, p2)
    n = (-u[1], u[0])
    side_pt = (end_pt[0] + n[0] * sign * t / 2.0, end_pt[1] + n[1] * sign * t / 2.0)
    over = 0.0
    for ob in obstacles:
        if ob is seg:
            continue
        ub = _unit(ob["p1"], ob["p2"])
        if abs(u[0] * ub[0] + u[1] * ub[1]) > 0.02:   # 只处理互相垂直的邻墙
            continue
        lb = math.dist(ob["p1"], ob["p2"])
        tb = ob["thick"]
        nb = (-ub[1], ub[0])

        def local(pt):
            dx, dy = pt[0] - ob["p1"][0], pt[1] - ob["p1"][1]
            return (dx * ub[0] + dy * ub[1], dx * nb[0] + dy * nb[1])

        ex, ey = local(end_pt)
        if not (-tol <= ex <= lb + tol and abs(ey) <= tb / 2.0 + tol):
            continue                                # 端点没落在邻墙上，不算转角
        sx, sy = local(side_pt)
        if sx < -tol or sx > lb + tol or abs(sy) > tb / 2.0 + tol:
            over = max(over, tb / 2.0)              # 该侧在邻墙体外 -> 合角延伸
    return over


def _rect_corners(seg: dict) -> list[tuple[float, float]]:
    p1, p2, t = seg["p1"], seg["p2"], seg["thick"]
    u = _unit(p1, p2)
    n = (-u[1], u[0])
    h = t / 2.0
    return [
        (p1[0] + n[0] * h, p1[1] + n[1] * h),
        (p2[0] + n[0] * h, p2[1] + n[1] * h),
        (p2[0] - n[0] * h, p2[1] - n[1] * h),
        (p1[0] - n[0] * h, p1[1] - n[1] * h),
    ]


def _rects_overlap(a: dict, b: dict, tol: float = 1e-6) -> bool:
    """两堵墙的实心矩形是否相交（分离轴定理，矩形对矩形）。"""
    ca, cb = _rect_corners(a), _rect_corners(b)
    for seg in (a, b):
        u = _unit(seg["p1"], seg["p2"])
        for axis in (u, (-u[1], u[0])):
            pa = [c[0] * axis[0] + c[1] * axis[1] for c in ca]
            pb = [c[0] * axis[0] + c[1] * axis[1] for c in cb]
            if max(pa) < min(pb) - tol or max(pb) < min(pa) - tol:
                return False
    return True


def _in_polygon(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    """射线法判点是否在轮廓内（严格内部，落边上视为外）。"""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                inside = not inside
    return inside


def _is_exterior(session: Session, wall: dict[str, Any]) -> bool:
    """墙是不是外墙：沿墙取中段，两侧各探一点，只有一侧落在房间内才算外墙。

    内墙两侧都是房间；外墙则是"内侧是房间、外侧是室外"。
    若图纸还没有房间，无法判断，一律按外墙处理。
    """
    rooms = room_data(session)
    polys: list[list[tuple[float, float]]] = []
    for r in rooms:
        raw = r.get("pts")
        if isinstance(raw, str) and raw.strip():
            try:
                polys.append([tuple(p) for p in ast.literal_eval(raw)])
                continue
            except (ValueError, SyntaxError):
                pass
        elif raw:
            polys.append([tuple(p) for p in raw])
            continue
        if r.get("outline"):
            polys.append([tuple(p) for p in r["outline"]])
    if not polys:
        return True

    p1, p2 = tuple(wall["p1"]), tuple(wall["p2"])
    d = _unit(p1, p2)
    n = (-d[1], d[0])
    length = math.dist(p1, p2)
    gap = wall["thick"] / 2.0 + 50.0

    any_xor = False
    both_inside = 0
    samples = 0
    # 取墙中段多个采样点：墙端点正好落在房间分界处，单点判断会两头不落房间
    for frac in (0.25, 0.5, 0.75):
        base = (p1[0] + d[0] * length * frac, p1[1] + d[1] * length * frac)
        a = (base[0] + n[0] * gap, base[1] + n[1] * gap)
        b = (base[0] - n[0] * gap, base[1] - n[1] * gap)
        in_a = any(_in_polygon(a, poly) for poly in polys)
        in_b = any(_in_polygon(b, poly) for poly in polys)
        samples += 1
        if in_a != in_b:
            any_xor = True
        elif in_a and in_b:
            both_inside += 1
    if any_xor:
        return True          # 一侧室内一侧室外 = 外墙
    if both_inside == samples:
        return False         # 两侧都是房间 = 内墙
    return True              # 不贴任何房间（孤墙）按外墙处理，宁可标多也不漏
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    ln = math.hypot(dx, dy)
    return (dx / ln, dy / ln) if ln else (1.0, 0.0)


def annotate(session: Session, opening_off: float | None = None,
             wall_off: float | None = None, total_off: float | None = None,
             total: bool = True, clear: bool = True,
             exterior_only: bool = True, scale: float | None = None) -> dict[str, Any]:
    """给外墙标尺寸：洞口宽在内层、墙段（轴线）在中层、总尺寸在最外层。

    - 外侧判断：取所有墙中点均值作为"建筑内部参考点"，
      法向两侧各取一点，离参考点更远的那侧就是外侧。
    - 只标外墙（内墙两侧都是房间，标注会压在房间名和门扇上）；
      图纸里还没有房间时退化为全部墙都标。
    - 三道尺寸线分别离墙中心线 9 / 16 / 22mm，轴号圈从 24mm 起，
      所以最外道总尺寸与轴号不压线（GB/T 50001 三道尺寸顺序：洞口→轴线→总尺寸）。
    - 总尺寸按"同一条外墙线"归组，每组只注一条全长（矩形平面即四边各一条）。
    - 标注统一落在 AA-DIM 层，样式 AA-DIM（字高 250 / 箭头 150）。
    - 默认先清掉 AA-DIM 层上已有的标注，重跑幂等，不会叠出一堆重影。
    """
    walls = wall_data(session)
    if not walls:
        raise CadError("拒绝标注：图纸里没有墙")
    sc = float(scale) if scale else drawing_scale(session)
    if opening_off is None:
        opening_off = annot_size(9.0, sc)      # 内层尺寸线离墙 9mm
    if wall_off is None:
        wall_off = annot_size(16.0, sc)        # 中层（轴线）尺寸线离墙 16mm
    if total_off is None:
        total_off = annot_size(22.0, sc)       # 外层总尺寸离墙 22mm
    if exterior_only:
        walls = [w for w in walls if _is_exterior(session, w)]
    if not walls:
        raise CadError("拒绝标注：没找到可标注的外墙")

    session.ensure_layers([LAYERS["dim"]])
    session.ensure_dim_style(text_height=annot_size(2.5, sc),
                             arrow_size=annot_size(1.5, sc),
                             ext_offset=annot_size(1.0, sc))

    if clear:
        old = [e["handle"] for e in session.entities().get("entities", [])
               if e["type"] == "Dimension" and e.get("layer") == LAYERS["dim"]]
        if old:
            session.run([("erase", {"handles": old})], save=True)

    session.run([("layer.set", {"name": LAYERS["dim"]})], save=True)

    mids = [((w["p1"][0] + w["p2"][0]) / 2.0, (w["p1"][1] + w["p2"][1]) / 2.0)
            for w in walls]
    cx = sum(m[0] for m in mids) / len(mids)
    cy = sum(m[1] for m in mids) / len(mids)

    made: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    openings = opening_data(session)
    cmds: list[tuple[str, dict]] = []
    for w in walls:
        p1, p2 = tuple(w["p1"]), tuple(w["p2"])
        d = _unit(p1, p2)
        n = (-d[1], d[0])
        mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
        probe = 1000.0
        far = (mid[0] + n[0] * probe, mid[1] + n[1] * probe)
        near = (mid[0] - n[0] * probe, mid[1] - n[1] * probe)
        side = 1.0 if math.dist(far, (cx, cy)) > math.dist(near, (cx, cy)) else -1.0
        half = w["thick"] / 2.0
        ang = math.degrees(math.atan2(d[1], d[0]))
        o_off = opening_off      # 内层洞口尺寸线：离墙 9mm，贴着第二道内侧
        w_off = wall_off         # 外层墙段尺寸线：离墙 20mm，轴号圈由轴网放到它外侧

        # 墙总长（外层）：偏移从墙中心线起算，这样 20mm 是"到轴线"的固定纸面距离，
        # 墙厚不会因为比例变化把尺寸文字顶进轴号圈
        at = (mid[0] + n[0] * side * w_off,
              mid[1] + n[1] * side * w_off)
        cmds.append(("dimlinear", {"p1": list(p1), "p2": list(p2),
                                   "at": [round(at[0], 4), round(at[1], 4)],
                                   "rotation": round(ang, 6)}))
        made.append({"kind": "wall", "id": w["id"], "value": round(w["len"], 2)})
        lines.append({"p1": p1, "p2": p2, "d": d, "n": n, "side": side})

        # 洞口宽（内层）
        for o in openings:
            if o["wallid"] != w["id"]:
                continue
            o1 = (p1[0] + d[0] * (o["pos"] - o["width"] / 2.0),
                  p1[1] + d[1] * (o["pos"] - o["width"] / 2.0))
            o2 = (p1[0] + d[0] * (o["pos"] + o["width"] / 2.0),
                  p1[1] + d[1] * (o["pos"] + o["width"] / 2.0))
            omid = ((o1[0] + o2[0]) / 2.0, (o1[1] + o2[1]) / 2.0)
            oat = (omid[0] + n[0] * side * o_off,
                   omid[1] + n[1] * side * o_off)
            cmds.append(("dimlinear", {"p1": [round(v, 4) for v in o1],
                                       "p2": [round(v, 4) for v in o2],
                                       "at": [round(oat[0], 4), round(oat[1], 4)],
                                       "rotation": round(ang, 6)}))
            made.append({"kind": "opening", "id": o["id"], "value": round(o["width"], 2)})

    # 外层总尺寸：把"同一条外墙线 + 同一侧"的墙归成一组，每组注一条全长。
    # 先把方向规范化到 +x/+y 半球，避免同一立面被正向/反向拆成两组。
    groups: dict[tuple, dict[str, Any]] = {}
    for ln in lines:
        d, n, side = ln["d"], ln["n"], ln["side"]
        flip = d[0] < -1e-9 or (abs(d[0]) <= 1e-9 and d[1] < 0)
        fd = (-d[0], -d[1]) if flip else d
        fn = (-n[0], -n[1]) if flip else n
        fside = -side if flip else side
        c = fn[0] * ln["p1"][0] + fn[1] * ln["p1"][1]
        ang = round(math.degrees(math.atan2(fd[1], fd[0])) % 180.0, 1)
        key = (ang, round(c, 0), round(fside, 0))
        t1 = fd[0] * ln["p1"][0] + fd[1] * ln["p1"][1]
        t2 = fd[0] * ln["p2"][0] + fd[1] * ln["p2"][1]
        g = groups.get(key)
        if g is None:
            groups[key] = {"d": fd, "n": fn, "side": fside, "c": c,
                           "t0": min(t1, t2), "t1": max(t1, t2)}
        else:
            g["t0"] = min(g["t0"], t1, t2)
            g["t1"] = max(g["t1"], t1, t2)

    if total:
        for g in groups.values():
            d, n, c, side = g["d"], g["n"], g["c"], g["side"]
            span = g["t1"] - g["t0"]
            if span <= 1.0:
                continue
            p1 = (d[0] * g["t0"] + n[0] * c, d[1] * g["t0"] + n[1] * c)
            p2 = (d[0] * g["t1"] + n[0] * c, d[1] * g["t1"] + n[1] * c)
            mid = ((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
            at = (mid[0] + n[0] * side * total_off,
                  mid[1] + n[1] * side * total_off)
            cmds.append(("dimlinear", {"p1": [round(v, 4) for v in p1],
                                       "p2": [round(v, 4) for v in p2],
                                       "at": [round(at[0], 4), round(at[1], 4)],
                                       "rotation": round(math.degrees(math.atan2(d[1], d[0])), 6)}))
            made.append({"kind": "total", "id": "TOTAL", "value": round(span, 2)})

    res = session.run(cmds, save=True)
    handles = [r.get("handle") for r in res.data if r.get("handle")]
    if len(handles) != len(made):
        raise CadError("标注数量不符：期望 %d 条，实际生成 %d 条" % (len(made), len(handles)))
    # dimlinear 会把标注落在当前图层之外的 "0" 层，必须显式改层
    session.run([("properties.set", {"handles": handles, "layer": LAYERS["dim"]})], save=True)

    # 回读：测量值必须与墙长/洞宽一致，且全部落在 AA-DIM 层
    by_handle = {e["handle"]: e for e in session.entities().get("entities", [])
                 if e["type"] == "Dimension"}
    dims = [by_handle[h] for h in handles if h in by_handle]
    if len(dims) != len(made):
        raise CadError("回读标注数量不符：%d != %d" % (len(dims), len(made)))
    for e, want in zip(dims, made):
        if e.get("layer") != LAYERS["dim"]:
            raise CadError("标注 %s 未落在 %s 层" % (e["handle"], LAYERS["dim"]))
        m = e.get("geometry", {}).get("measurement")
        if m is None or abs(float(m) - want["value"]) > 0.01:
            raise CadError("回读测量值不符：%s(%.2f) 期望 %.2f"
                           % (want["id"], float(m or 0), want["value"]))

    return {
        "dims": len(made),
        "walls": sum(1 for m in made if m["kind"] == "wall"),
        "openings": sum(1 for m in made if m["kind"] == "opening"),
        "totals": sum(1 for m in made if m["kind"] == "total"),
        "layer": LAYERS["dim"],
        "style": "AA-DIM",
    }


def normalize_around(session: Session, wall_id: str) -> int:
    """重建指定墙及其所有相交/相接的邻墙，使裁剪与合角一致。

    只重算"碰到它"的那一圈墙，避免每画一堵墙就全图重建。
    返回被重建的墙数量。
    """
    walls = wall_data(session)
    by_id = {w["id"]: w for w in walls}
    w = by_id.get(wall_id)
    if not w:
        return 0
    target = [w] + [x for x in walls if x["id"] != wall_id and _rects_overlap(w, x)]
    openings = opening_data(session)
    final = [{**t, "root": t["root"] or t["id"]} for t in target]
    sides = {}
    for t in target:
        others = [x for x in walls if x["id"] != t["id"]]
        seg_len = math.dist(t["p1"], t["p2"])
        sides[t["id"]] = wall_sides(
            t, others, holes=_hole_spans(openings, t["id"], seg_len)
        )
    _apply_layout(session, target, final, sides, [])
    return len(target)


def _next_free_wall_id(session: Session, reserved: set[str]) -> str:
    mx = 0
    for e in session.references():
        b = e["geometry"]["block"]
        if b.startswith("AA_WALL_"):
            m = re.search(r"(\d+)$", b)
            if m:
                mx = max(mx, int(m.group(1)))
    for x in reserved:
        m = re.search(r"(\d+)$", x)
        if m:
            mx = max(mx, int(m.group(1)))
    n = mx + 1
    while "W%03d" % n in reserved:
        n += 1
    return "W%03d" % n


def split_at_intersections(session: Session, tol: float = 1e-6) -> dict[str, Any]:
    """墙体相交自动切断。

    规则（spec §5.1，实测版）：
      - 只在"两段内部"相交时切断；端点相接（T 形）不动。
      - 切断后的第一段沿用原编号，其余分段分配新编号，并用 AA_ROOT 记录逻辑墙号。
      - 洞口不允许跨越切点：先校验，校验通过才动图；失败不留半成品。
      - 洞口跟随所在分段迁移（重建参照，偏移量按新墙起点换算）。
    """
    walls = wall_data(session)
    if len(walls) < 2:
        return {"splits": 0, "segments": [], "openings_moved": []}
    by_id = {w["id"]: w for w in walls}

    segs = " ".join(
        '(list "%s" (list %.4f %.4f 0.0) (list %.4f %.4f 0.0))'
        % (w["id"], w["p1"][0], w["p1"][1], w["p2"][0], w["p2"][1])
        for w in walls
    )
    raw = session.lisp("(aa:xsec (list %s))" % segs,
                       libraries=("aa_core.lisp", "aa_intersect.lisp")).strip()
    if not raw:
        return {"splits": 0, "segments": [], "openings_moved": []}

    def interior(t: float) -> bool:
        return tol < t < 1.0 - tol

    cut_ts: dict[str, set[float]] = {}
    for rec in raw.split(";"):
        parts = rec.split("|")
        if len(parts) != 6:
            continue
        id1, id2, t1, t2 = parts[0], parts[1], float(parts[2]), float(parts[3])
        # 只在"该段内部"的位置切断；端点相接属于 T 形衔接，不切
        if interior(t1):
            cut_ts.setdefault(id1, set()).add(t1)
        if interior(t2):
            cut_ts.setdefault(id2, set()).add(t2)

    # 计算分段方案（先算，不动图）
    plan: dict[str, list[tuple[float, float]]] = {}
    for wid, ts in cut_ts.items():
        ts = sorted(t for t in ts if tol < t < 1.0 - tol)
        if not ts:
            continue
        cuts = [0.0] + ts + [1.0]
        plan[wid] = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]

    if not plan:
        return {"splits": 0, "segments": [], "openings_moved": []}

    # 校验：洞口不得跨越切点
    openings = opening_data(session)
    for wid, segs_t in plan.items():
        w = by_id[wid]
        for o in openings:
            if o["wallid"] != wid:
                continue
            lo = o["pos"] - o["width"] / 2.0
            hi = o["pos"] + o["width"] / 2.0
            for ta, _tb in segs_t[1:]:
                p = ta * w["len"]
                if lo + tol < p < hi - tol:
                    raise CadError(
                        "拒绝切断：门窗 %s 的洞口 [%.2f, %.2f] 跨越墙 %s 的切点 %.2f，"
                        "请先调整洞口位置"
                        % (o["id"], lo, hi, wid, p)
                    )

    # 开始动图之前先把整份方案算完（含墙线裁剪），失败可整体回滚
    reserved = set(by_id)
    final: list[dict[str, Any]] = []
    mapping: dict[str, list[tuple[str, float, float]]] = {}
    for w in walls:
        segs_t = plan.get(w["id"], [(0.0, 1.0)])
        seg_list = []
        for idx, (ta, tb) in enumerate(segs_t):
            nid = w["id"] if idx == 0 else _next_free_wall_id(session, reserved)
            reserved.add(nid)
            seg_list.append((nid, ta, tb))
        mapping[w["id"]] = seg_list
        for nid, ta, tb in seg_list:
            obj = dict(w)
            obj.update(
                {
                    "p1": _lerp(w["p1"], w["p2"], ta),
                    "p2": _lerp(w["p1"], w["p2"], tb),
                    "ax1": w["ax1"] if ta == 0.0 else "",
                    "ax2": w["ax2"] if tb == 1.0 else "",
                    "root": w["root"] or w["id"],
                }
            )
            obj["id"] = nid
            obj["block"] = "AA_WALL_" + nid
            final.append(obj)

    # 洞口落位（先算，不动图）
    openings_plan = []
    for o in openings:
        w = by_id[o["wallid"]]
        t = o["pos"] / w["len"] if w["len"] else 0.0
        seg_list = mapping[o["wallid"]]
        host, ta = seg_list[-1][0], seg_list[-1][1]
        for nid, a, b in seg_list:
            if a - tol <= t <= b + tol:
                host, ta = nid, a
                break
        openings_plan.append({**o, "host": host, "new_pos": o["pos"] - ta * w["len"]})

    # 侧线裁剪：邻墙轮廓 + 本段上的门窗洞口都要让出缺口
    sides_by_id = {}
    for seg in final:
        seg_len = math.dist(seg["p1"], seg["p2"])
        sides_by_id[seg["id"]] = wall_sides(
            seg, final, holes=_hole_spans(openings_plan, seg["id"], seg_len)
        )

    moved = _apply_layout(session, walls, final, sides_by_id, openings_plan)

    return {
        "splits": len(plan),
        "walls": len(final),
        "segments": [s["id"] for s in final],
        "openings_moved": moved,
    }


def _hole_spans(openings, host: str, length: float) -> list[tuple[float, float]]:
    """某段墙上的门窗洞口区间（局部 X 距离）。openings 可带 host/new_pos 或 wallid/pos。"""
    spans = []
    for o in openings:
        if o.get("host", o.get("wallid")) != host:
            continue
        p = o.get("new_pos", o.get("pos"))
        a, b = p - o["width"] / 2.0, p + o["width"] / 2.0
        spans.append((max(0.0, a), min(length, b)))
    return spans


def rebuild_wall_with_openings(session: Session, wall_id: str) -> bool:
    """按当前洞口重生成该墙块：侧线在洞口处断开，墙身真正"开洞"。"""
    walls = wall_data(session)
    by_id = {w["id"]: w for w in walls}
    w = by_id.get(wall_id)
    if not w:
        return False
    others = [x for x in walls if x["id"] != wall_id]
    holes = _hole_spans(opening_data(session), wall_id, w["len"])
    if not holes:
        return False
    seg = {**w, "root": w["root"] or w["id"]}
    sides = wall_sides(seg, others, holes=holes)
    _apply_layout(session, [w], [seg], {wall_id: sides}, [])
    return True


def _apply_layout(session, walls, final, sides_by_id, openings_plan):
    """整体重建墙网（破坏性操作）：备份 -> 拆旧 -> 建新 -> 门窗回图，异常整体回滚。"""
    backup = session.path.with_name(session.path.stem + ".bak" + session.path.suffix)
    shutil.copy2(session.path, backup)
    moved = []
    try:
        # 1) 摘掉全部门窗（墙体重建后按新墙位重新生成）
        for o in openings_plan:
            delete_component(session, o["block"])
        # 2) 拆掉原有墙体
        for w in walls:
            delete_component(session, w["block"])
        # 3) 按最终段表重建（含裁剪后的墙线）
        for seg in final:
            create_wall(
                session, seg["id"], seg["p1"], seg["p2"],
                thick=seg["thick"], kind=seg["kind"] or "INTERNAL", mat=seg["mat"],
                ax1=seg["ax1"], ax2=seg["ax2"], root=seg["root"],
                sides=sides_by_id.get(seg["id"]),
                floor=seg.get("floor", 1),
            )
        # 4) 门窗跟随新墙位回图
        for o in openings_plan:
            create_opening(
                session, o["id"], o["host"], o["kind"], o["width"], o["new_pos"],
                height=o["height"], sill=o["sill"],
            )
            moved.append({"id": o["id"], "from": o["wallid"], "to": o["host"],
                          "pos": round(o["new_pos"], 4)})
    except Exception:
        # 回滚：整体恢复动图前的文件，绝不留半成品
        shutil.copy2(backup, session.path)
        raise
    finally:
        if backup.exists():
            backup.unlink()
    return moved


def _chain_walls(segs: list[dict], tol: float) -> list[dict] | None:
    """把若干墙段按端点相接排成一条首尾贯通的有向链；排不成返回 None。

    返回的每一段 p1 -> p2 已统一为链的前进方向。
    """
    remaining = [dict(s) for s in segs]
    if len(remaining) < 2:
        return remaining if remaining else None

    first = remaining.pop(0)
    chain = [first]
    tail = first["p2"]
    # 先向尾端延伸
    while remaining:
        nxt = None
        for s in remaining:
            if math.dist(tail, s["p1"]) <= tol:
                nxt = s
                break
            if math.dist(tail, s["p2"]) <= tol:
                nxt = {**s, "p1": s["p2"], "p2": s["p1"]}
                break
        if nxt is None:
            break
        remaining.remove(s)
        chain.append(nxt)
        tail = nxt["p2"]
    # 再向头端延伸
    head = chain[0]["p1"]
    while remaining:
        nxt = None
        for s in remaining:
            if math.dist(head, s["p2"]) <= tol:
                nxt = dict(s)
                break
            if math.dist(head, s["p1"]) <= tol:
                nxt = {**s, "p1": s["p2"], "p2": s["p1"]}
                break
        if nxt is None:
            break
        remaining.remove(s)
        chain.insert(0, nxt)
        head = nxt["p1"]
    if remaining:
        return None
    return chain


def _collinear_chain(chain: list[dict], tol: float) -> bool:
    """整条链是否共线（同向、同一条直线上）。"""
    if len(chain) < 2:
        return False
    u = _unit(chain[0]["p1"], chain[0]["p2"])
    base = chain[0]["p1"]
    for s in chain:
        us = _unit(s["p1"], s["p2"])
        if abs(u[0] * us[1] - u[1] * us[0]) > 1e-6:
            return False
        if u[0] * us[0] + u[1] * us[1] < 0.999:
            return False
        dx, dy = s["p1"][0] - base[0], s["p1"][1] - base[1]
        if abs(-u[1] * dx + u[0] * dy) > tol:
            return False
    return True


def merge_walls(session: Session, wall_ids: list[str] | None = None,
                tol: float = 1e-6) -> dict[str, Any]:
    """合并共线且首尾相接的墙段。

    默认：按 AA_ROOT 分组，组内能排成共线链的多段合并回一整段（即撤销切断）。
    wall_ids：显式指定要合并的若干堵墙，新墙沿用链首编号。
    合并后沿用链上原始编号，洞口按投影换算到新墙起点。
    """
    walls = wall_data(session)
    if len(walls) < 2:
        return {"merges": 0, "walls": len(walls),
                "segments": [w["id"] for w in walls], "merged": []}
    by_id = {w["id"]: w for w in walls}
    openings = opening_data(session)

    groups: list[tuple[str, list[dict]]] = []
    if wall_ids:
        missing = [i for i in wall_ids if i not in by_id]
        if missing:
            raise CadError("拒绝合并：墙 %s 不存在" % ",".join(missing))
        chain = _chain_walls([by_id[i] for i in wall_ids], tol)
        if not chain or not _collinear_chain(chain, tol):
            raise CadError("拒绝合并：指定的墙不共线，或不是首尾相接")
        if len({round(float(s["thick"]), 4) for s in chain}) > 1:
            raise CadError("拒绝合并：指定的墙厚不一致")
        groups.append((chain[0]["id"], chain))
    else:
        buckets: dict[str, list[dict]] = {}
        for w in walls:
            buckets.setdefault(w["root"] or w["id"], []).append(w)
        for root, segs in buckets.items():
            if len(segs) < 2:
                continue
            chain = _chain_walls(segs, tol)
            if chain and _collinear_chain(chain, tol):
                groups.append((root, chain))

    if not groups:
        return {"merges": 0, "walls": len(walls),
                "segments": [w["id"] for w in walls], "merged": []}

    merged_ids = {s["id"] for _r, chain in groups for s in chain}

    final: list[dict[str, Any]] = []
    for w in walls:
        if w["id"] not in merged_ids:
            final.append({**w, "root": w["root"] or w["id"],
                          "block": "AA_WALL_" + w["id"]})

    host_of: dict[str, tuple[str, float]] = {}
    merged_report = []
    lengths: dict[str, float] = {w["id"]: float(w["len"]) for w in walls}
    for root, chain in groups:
        p1, p2 = chain[0]["p1"], chain[-1]["p2"]
        length = math.dist(p1, p2)
        u = _unit(p1, p2)
        # 轴号归属：按端点位置判断
        ax1 = ax2 = ""
        for s in chain:
            if s["ax1"] and math.dist(s["p1"], p1) <= tol:
                ax1 = s["ax1"]
            if s["ax2"] and math.dist(s["p2"], p2) <= tol:
                ax2 = s["ax2"]
        merged = {**chain[0], "p1": p1, "p2": p2, "id": root, "root": root,
                  "block": "AA_WALL_" + root, "ax1": ax1, "ax2": ax2}
        final.append(merged)
        lengths[root] = length
        for s in chain:
            off = (s["p1"][0] - p1[0]) * u[0] + (s["p1"][1] - p1[1]) * u[1]
            host_of[s["id"]] = (root, off)
        merged_report.append({"id": root, "from": [s["id"] for s in chain],
                              "length": round(length, 4)})

    # 门窗落位：投影到合并后的墙起点
    openings_plan = []
    for o in openings:
        if o["wallid"] in host_of:
            host, off = host_of[o["wallid"]]
            new_pos = o["pos"] + off
        else:
            host, new_pos = o["wallid"], o["pos"]
        host_len = lengths.get(host, 0.0)
        if new_pos - o["width"] / 2.0 < -tol or new_pos + o["width"] / 2.0 > host_len + tol:
            raise CadError("拒绝合并：门窗 %s 合并后将超出墙 %s 的墙段范围" % (o["id"], host))
        openings_plan.append({**o, "host": host, "new_pos": new_pos})

    sides_by_id = {}
    for seg in final:
        seg_len = math.dist(seg["p1"], seg["p2"])
        sides_by_id[seg["id"]] = wall_sides(
            seg, final, holes=_hole_spans(openings_plan, seg["id"], seg_len)
        )
    moved = _apply_layout(session, walls, final, sides_by_id, openings_plan)

    return {
        "merges": len(groups),
        "walls": len(final),
        "segments": [s["id"] for s in final],
        "merged": merged_report,
        "openings_moved": moved,
    }


def create_wall(
    session: Session,
    wall_id: str,
    p1: tuple[float, float],
    p2: tuple[float, float],
    thick: float = 240.0,
    kind: str = "INTERNAL",
    mat: str = "",
    ax1: str = "",
    ax2: str = "",
    root: str = "",
    sides: list[tuple[float, float, float, float]] | None = None,
    snap_axis: bool = False,
    snap_tol: float = 300.0,
    floor: int = 1,
) -> dict[str, Any]:
    """墙体：LISP 生成本地几何 -> block -> insert（起点+旋转）-> 回读校验。

    snap_axis=True 时先把端点吸附到最近轴线（"先轴后墙"），吸附量在返回值里如实报告；
    画完若图上有轴网，会自动回填 ax1/ax2（原有的非空值不覆盖）。
    `floor` 记在 `AA_FLOOR` 上：门窗表要按层统计樘数，平面自身不带层号（v1.0.32）。
    """
    try:
        floor = int(floor)
    except (TypeError, ValueError):
        raise CadError("墙体层号必须是整数（收到 %r）" % (floor,))
    if floor < 1:
        raise CadError("墙体层号必须 ≥ 1（收到 %s）" % floor)
    block = "AA_WALL_" + wall_id
    snapped = None
    if snap_axis:
        grids = axis_grids(session)
        if grids:
            p1s = list(p1)
            p2s = list(p2)
            for i in (0, 1):
                c = "x" if i == 0 else "y"
                for pt in (p1s, p2s):
                    best, bd = None, None
                    for g in grids:
                        for v in (g["xpos"] if c == "x" else g["ypos"]):
                            d = abs(v - pt[i])
                            if bd is None or d < bd:
                                best, bd = v, d
                    if best is not None and bd is not None and bd <= snap_tol:
                        pt[i] = best
            if tuple(p1s) != tuple(p1) or tuple(p2s) != tuple(p2):
                snapped = {"p1": [round(v, 3) for v in p1s],
                           "p2": [round(v, 3) for v in p2s]}
                p1, p2 = tuple(p1s), tuple(p2s)
    session.ensure_layers([LAYERS["wall"]])

    before = session.snapshot()
    sides_lisp = "nil"
    if sides:
        sides_lisp = "(list %s)" % " ".join(
            "(list %.4f %.4f %.4f %.4f)" % s for s in sides
        )
    value = session.lisp(
        "(aa:wall (list %s %s 0.0) (list %s %s 0.0) %s %s)"
        % (p1[0], p1[1], p2[0], p2[1], thick, sides_lisp),
        libraries=("aa_core.lisp", "aa_wall.lisp"),
    )
    handles = session.new_handles(before)
    length, angle = value.split("#")

    att_handles = session.define_attributes(
        [
            ("AA_TYPE", "component type", "WALL"),
            ("AA_ID", "component id", wall_id),
            ("AA_THICK", "wall thickness", "%.4f" % float(thick)),
            ("AA_KIND", "wall kind", kind),
            ("AA_MAT", "material", mat),
            ("AA_AX1", "start axis", ax1),
            ("AA_AX2", "end axis", ax2),
            ("AA_LEN", "length", "%.4f" % float(length)),
            ("AA_ROOT", "logical wall id", root or wall_id),
            ("AA_FLOOR", "floor no", str(int(floor))),
        ]
    )

    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(
        block,
        p1,
        {
            "AA_TYPE": "WALL",
            "AA_ID": wall_id,
            "AA_THICK": "%.4f" % float(thick),
            "AA_KIND": kind,
            "AA_MAT": mat,
            "AA_AX1": ax1,
            "AA_AX2": ax2,
            "AA_LEN": "%.4f" % float(length),
            "AA_ROOT": root or wall_id,
            "AA_FLOOR": str(int(floor)),
        },
        rotation=float(angle) * 57.29577951308232,
        layer=LAYERS["wall"],
    )
    session.expect_attributes(
        block,
        {
            "AA_ID": wall_id,
            "AA_TYPE": "WALL",
            "AA_THICK": "%.4f" % float(thick),
            "AA_LEN": "%.4f" % float(length),
            "AA_KIND": kind,
        },
    )
    bound = bind_walls_to_axis(session, tol=50.0, only_empty=True) if axis_grids(session) else None
    res = {
        "block": block,
        "handle": handle,
        "length": float(length),
        "angle_deg": float(angle) * 57.29577951308232,
        "geom_handles": handles,
    }
    if snapped:
        res["snapped"] = snapped
    if bound is not None:
        for u in bound["walls"]:
            if u["wall"] == wall_id:
                res["ax1"], res["ax2"] = u["ax1"], u["ax2"]
    return res


def layer_table(path) -> dict[str, dict[str, Any]]:
    """读 DXF 的 LAYER 表：{层名: {color: ACI, linetype: str, lineweight: mm}}。"""
    lines_in = [ln.strip() for ln in Path(path).read_text(encoding="utf-8",
                                                          errors="replace").splitlines()]
    out: dict[str, dict[str, Any]] = {}
    section = None
    rec: dict[str, Any] | None = None
    i = 0
    n = len(lines_in)
    while i < n - 1:
        code, val = lines_in[i], lines_in[i + 1]
        i += 2
        if code == "0":
            if rec is not None and rec.get("name"):
                out[rec["name"]] = {"color": rec["color"],
                                    "linetype": rec["linetype"],
                                    "lineweight": rec["lineweight"]}
            rec = None
            if val == "SECTION":
                section = None
            elif val == "ENDSEC":
                section = None
            elif section == "TABLES" and val == "LAYER":
                rec = {"name": None, "color": 7, "linetype": "Continuous",
                       "lineweight": -3.0}
            continue
        if code == "2" and section is None:
            section = val
            continue
        if rec is None:
            continue
        if code == "2" and rec["name"] is None:
            rec["name"] = val
        elif code == "62":
            rec["color"] = abs(int(val))
        elif code == "6":
            rec["linetype"] = val
        elif code == "370":
            rec["lineweight"] = int(val) / 100.0
    if rec is not None and rec.get("name"):
        out[rec["name"]] = {"color": rec["color"], "linetype": rec["linetype"],
                            "lineweight": rec["lineweight"]}
    return out


def layer_of_block(path, block_name: str) -> set[str]:
    """块定义内出现过的图层名集合（DXF 组 8），用于核对构件是否落对层。"""
    lines_in = [ln.strip() for ln in Path(path).read_text(encoding="utf-8",
                                                          errors="replace").splitlines()]
    out: set[str] = set()
    section = cur = None
    i = 0
    while i < len(lines_in) - 1:
        code, val = lines_in[i], lines_in[i + 1]
        i += 2
        if code == "0":
            if val == "SECTION":
                section = None
            elif val == "ENDSEC":
                section, cur = None, None
            elif section == "BLOCKS":
                if val == "BLOCK":
                    cur = None
                elif val == "ENDBLK":
                    cur = None
            continue
        if code == "2":
            if section is None:
                section = val
            elif section == "BLOCKS" and cur is None:
                cur = val
            continue
        if section == "BLOCKS" and cur == block_name and code == "8" and val:
            out.add(val)
    return out


def block_geometry(path, block_name: str) -> list[dict[str, Any]]:
    """直接解析 DXF 文本，返回指定块定义内的图元几何（用于核对墙线/开洞是否落地）。

    返回 [{"type": "LINE", "pts": [(x,y),(x,y)]}, {"type": "LWPOLYLINE", "pts": [...]}]
    """
    lines_in = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()]
    blocks: dict[str, list] = {}
    section = None
    cur_name = None
    cur_ents = None
    ent = None
    i = 0
    while i + 1 < len(lines_in):
        code, val = lines_in[i], lines_in[i + 1]
        i += 2
        try:
            code_n = int(code)
        except ValueError:
            continue
        if code_n == 0:
            if val == "SECTION":
                section, cur_name, cur_ents, ent = None, None, None, None
            elif val == "ENDSEC":
                section, cur_name, cur_ents, ent = None, None, None, None
            elif section == "BLOCKS":
                if val == "BLOCK":
                    cur_name, cur_ents, ent = None, [], None
                elif val == "ENDBLK":
                    if cur_name:
                        blocks[cur_name] = cur_ents
                    cur_name, cur_ents, ent = None, None, None
                elif cur_ents is not None:
                    ent = {"type": val, "pts": [], "lt": None, "layer": None, "txt": None, "r": None,
                           "sx": None, "sy": None, "ex": None, "ey": None, "sol": {}}
                    cur_ents.append(ent)
            continue
        if code_n == 2:
            if section is None:
                section = val
            elif cur_ents is not None and cur_name is None:
                cur_name = val
            continue
        if section != "BLOCKS" or ent is None:
            continue
        if ent["type"] == "SOLID":
            # SOLID 的四个角点走 10/11/12/13 + 20/21/22/23（不是常规的 10/20 单点）
            if code_n in (10, 11, 12, 13):
                ent["sol"].setdefault(code_n, {})["x"] = float(val)
            elif code_n in (20, 21, 22, 23):
                ent["sol"].setdefault(code_n - 10, {})["y"] = float(val)
            elif code_n == 8:
                ent["layer"] = val
            continue
        if code_n == 10:
            if ent["type"] == "LWPOLYLINE":
                ent["pts"].append([float(val), None])
            else:
                ent["sx"] = float(val)
        elif code_n == 20:
            if ent["type"] == "LWPOLYLINE" and ent["pts"] and ent["pts"][-1][1] is None:
                ent["pts"][-1][1] = float(val)
            elif ent["sy"] is None:
                ent["sy"] = float(val)
        elif code_n == 11:
            ent["ex"] = float(val)
        elif code_n == 21:
            ent["ey"] = float(val)
        elif code_n == 6:
            ent["lt"] = val
        elif code_n == 8:
            ent["layer"] = val
        elif code_n == 1:
            ent["txt"] = val
        elif code_n == 40:
            ent["r"] = float(val)

    out = []
    for e in blocks.get(block_name, []):
        if e["type"] == "LINE" and None not in (e["sx"], e["sy"], e["ex"], e["ey"]):
            out.append({"type": "LINE", "lt": e["lt"], "layer": e["layer"], "pts": [(e["sx"], e["sy"]), (e["ex"], e["ey"])]})
        elif e["type"] == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e["pts"] if p[1] is not None]
            if pts:
                out.append({"type": "LWPOLYLINE", "lt": e["lt"], "layer": e["layer"], "pts": pts})
        elif e["type"] in ("TEXT", "MTEXT") and e["txt"] is not None:
            at = (e["sx"], e["sy"]) if None not in (e["sx"], e["sy"]) else None
            out.append({"type": e["type"], "text": e["txt"], "layer": e["layer"],
                        "pts": [at] if at else [], "h": e["r"]})
        elif e["type"] == "CIRCLE" and None not in (e["sx"], e["sy"], e["r"]):
            out.append({"type": "CIRCLE", "r": e["r"], "layer": e["layer"], "pts": [(e["sx"], e["sy"])]})
        elif e["type"] == "SOLID":
            sol = e["sol"]
            pts = []
            for k in (10, 11, 12, 13):
                p = sol.get(k) or {}
                if "x" in p and "y" in p:
                    pts.append((p["x"], p["y"]))
            if pts:
                out.append({"type": "SOLID", "layer": e["layer"], "pts": pts})
    return out


# ---------------- 房间自动环搜索（v0.4） ----------------

def _graph_key(pt: tuple[float, float], snap: float = 1e-3) -> tuple[float, float]:
    """把墙端点规整到 0.001 mm 网格，消除旋转/回读带来的 ~1e-5 漂移。"""
    return (round(pt[0] / snap) * snap, round(pt[1] / snap) * snap)


def _wall_breaks(walls: list[dict], snap: float = 1e-3) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
    """把每堵墙按"被别的墙打断的位置"切成子段，返回 [(p, q, wall_id)]。

    只在搜索时切，不改图纸——这样没跑过 split 的 T 接/十字交叉也能正确成环。
    切点来源：
      1) 某个墙的端点落在本墙内部（T 接）；
      2) 两墙非共线相交的点（十字交叉，双方内部）。
    """
    segs = []
    for w in walls:
        p1, p2 = w["p1"], w["p2"]
        L = math.dist(p1, p2)
        if L <= snap:
            continue
        u = _unit(p1, p2)
        cuts = []
        for o in walls:
            if o is w:
                continue
            others = [o["p1"], o["p2"]]
            for q in others:                       # T 接
                t = (q[0] - p1[0]) * u[0] + (q[1] - p1[1]) * u[1]
                d = abs((q[0] - p1[0]) * u[1] - (q[1] - p1[1]) * u[0])
                if d <= snap and snap < t < L - snap:
                    cuts.append(t)
            ub = _unit(o["p1"], o["p2"])
            if abs(u[0] * ub[0] + u[1] * ub[1]) > 0.999:
                continue                           # 共线跳过（同一条墙的延续）
            pt = _line_intersect(p1, u, o["p1"], ub)
            if pt is None:
                continue
            t = (pt[0] - p1[0]) * u[0] + (pt[1] - p1[1]) * u[1]
            s = (pt[0] - o["p1"][0]) * ub[0] + (pt[1] - o["p1"][1]) * ub[1]
            ob_len = math.dist(o["p1"], o["p2"])
            if snap < t < L - snap and snap < s < ob_len - snap:
                cuts.append(t)
        cuts.sort()
        merged = []
        for t in cuts:
            if not merged or t - merged[-1] > snap:
                merged.append(t)
        ts = [0.0] + merged + [L]
        for a, b in zip(ts, ts[1:]):
            pa = (p1[0] + u[0] * a, p1[1] + u[1] * a)
            pb = (p1[0] + u[0] * b, p1[1] + u[1] * b)
            segs.append((_graph_key(pa, snap), _graph_key(pb, snap), w["id"]))
    return segs


def find_room_rings(session: Session, min_area: float = 1.0, snap: float = 1e-3) -> list[list[str]]:
    """在墙中线构成的无向平面图上枚举所有有界面（房间候选），返回墙编号的有序列表。

    做法是平面图的"半边面遍历"（half-edge face traversal）：
    - 顶点 = 墙端点与打断点（按 0.001 mm 吸附），边 = 墙的子段；
    - 每个半边只属于一条面边界，沿"目标点处取逆时针紧前出边"走，绕一圈即一个面；
    - 有界面（逆时针、面积为正）即房间；外轮廓（顺时针、面积为负）丢掉；
    - 面积为 0 的退化面（开放缺口、悬挂墙）丢掉。

    这样不必枚举所有回路（回路数是指数级的），是线性复杂度；连续的同墙子段会合并回一个墙号。
    """
    walls = [w for w in wall_data(session) if math.dist(w["p1"], w["p2"]) > snap]
    subsegs = _wall_breaks(walls, snap)
    verts: dict[tuple[float, float], int] = {}
    pts: list[tuple[float, float]] = []

    def vid(p):
        k = _graph_key(p, snap)
        if k not in verts:
            verts[k] = len(pts)
            pts.append(k)
        return verts[k]

    edges: list[tuple[int, int, str]] = []
    for pa, pb, wid in subsegs:
        u, v = vid(pa), vid(pb)
        if u != v:
            edges.append((u, v, wid))

    # 每个顶点上的出边，按方向角排序
    out: dict[int, list[tuple[float, int, int]]] = {}
    for ei, (u, v, _wid) in enumerate(edges):
        for a, b in ((u, v), (v, u)):
            ang = math.atan2(pts[b][1] - pts[a][1], pts[b][0] - pts[a][0])
            out.setdefault(a, []).append((ang, b, ei))
    for a in out:
        out[a].sort(key=lambda t: t[0])

    def next_half(u: int, v: int) -> tuple[int, int, int]:
        """从半边 u->v 走到 v，返回 v 处"逆时针紧前"的那条出边（把面留在左侧）。

        具体是：以 v->u 的方向角为基准，在 v 的出边里找角度小于它的最大者，
        没有就回绕到最大角度 —— 等价于把这条半边沿顶点逆时针转一格。
        """
        back = math.atan2(pts[u][1] - pts[v][1], pts[u][0] - pts[v][0])
        cand = out[v]
        prev = None
        for t in cand:
            if t[0] < back - 1e-12:
                prev = t
            else:
                break
        if prev is None:
            prev = cand[-1]
        return (v, prev[1], prev[2])

    visited: set[tuple[int, int]] = set()
    rings: list[dict[str, Any]] = []
    halfs = [(u, v, ei) for ei, (u, v, _wid) in enumerate(edges)]
    halfs += [(v, u, ei) for ei, (u, v, _wid) in enumerate(edges)]
    for start in halfs:
        if (start[0], start[1]) in visited:
            continue
        face_pts: list[int] = []
        face_walls: list[str] = []
        face_edges: list[tuple[tuple[float, float], tuple[float, float], str]] = []
        h = start
        closed = False
        for _ in range(len(edges) * 2 + 3):
            visited.add((h[0], h[1]))
            face_pts.append(h[0])
            face_walls.append(edges[h[2]][2])
            face_edges.append((pts[h[0]], pts[h[1]], edges[h[2]][2]))
            h = next_half(h[0], h[1])
            if (h[0], h[1]) == (start[0], start[1]):
                closed = True
                break
        if not closed or len(face_walls) < 3:
            continue
        poly = [pts[i] for i in face_pts]
        area = _poly_signed_area(poly)
        if area <= min_area:          # 逆时针才有界；顺时针是外轮廓
            continue
        # 同墙的子段合并回一个墙号（打断只是搜索手段，不改图）
        ring: list[str] = []
        for wid in face_walls:
            if not ring or ring[-1] != wid:
                ring.append(wid)
        if len(ring) > 1 and ring[0] == ring[-1]:
            ring.pop()
        if len(ring) >= 3:
            rings.append({"walls": ring, "edges": face_edges})
    return rings


def room_data(session: Session) -> list[dict[str, Any]]:
    """读取全部房间构件。"""
    out = []
    for e in session.components("AA_ROOM_"):
        g = e["geometry"]
        attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in g.get("attribs", [])}
        out.append(
            {
                "block": g["block"],
                "id": attrs.get("AA_ID") or g["block"][len("AA_ROOM_"):],
                "name": attrs.get("AA_NAME", ""),
                "area": float(attrs.get("AA_AREA", "0") or 0),
                "perimeter": float(attrs.get("AA_PERIMETER", "0") or 0),
                "walls": [x for x in (attrs.get("AA_WALLS", "") or "").split(";") if x],
                "show_area": attrs.get("AA_AREA_SHOW", "1") != "0",
                "pts": [
                    (float(p.split(",")[0]), float(p.split(",")[1]))
                    for p in (attrs.get("AA_PTS", "") or "").split(";")
                    if p and "," in p
                ],
            }
        )
    return out


def auto_rooms(session: Session, prefix: str = "R", name: str = "",
               min_area: float = 1.0) -> dict[str, Any]:
    """自动搜房间：枚举墙环 -> 跳过已建过的同一墙环 -> 逐个 create_room。

    跳过判据是"墙编号集合完全一致"，因此重复执行不会生成重复房间。
    """
    rings = find_room_rings(session, min_area=min_area)
    existing = room_data(session)
    taken = {frozenset(r["walls"]) for r in existing}
    used_ids = {r["id"] for r in existing}
    created, skipped = [], []
    for ring in rings:
        key = frozenset(ring["walls"])
        if key in taken:
            skipped.append({"walls": ring["walls"], "reason": "该墙环已有房间"})
            continue
        n = 1
        while "%s%03d" % (prefix, n) in used_ids:
            n += 1
        rid = "%s%03d" % (prefix, n)
        res = create_room_edges(session, rid, ring["edges"], name=name or rid)
        used_ids.add(rid)
        taken.add(key)
        created.append({
            "id": rid,
            "walls": ring["walls"],
            "area": round(res["area"], 2),
            "perimeter": round(res["perimeter"], 2),
        })
    if created:
        refresh_opening_labels(session)
    return {
        "rings": len(rings),
        "rooms": len(created),
        "created": created,
        "skipped": skipped,
    }


# ---------------- 图框 / 标题栏 / 出图（v0.7） ----------------

# GB/T 14689 基本幅面（mm），图框内留边：装订边 a=25，其余 c（A0/A1 取 10，A2~A4 取 5）
SHEETS: dict[str, tuple[float, float]] = {
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
    "A4": (297.0, 210.0),
}
SHEET_BIND = 25.0                        # 装订边 a
SHEET_EDGE = {"A0": 10.0, "A1": 10.0, "A2": 5.0, "A3": 5.0, "A4": 5.0}
TITLE_W, TITLE_H = 180.0, 56.0           # GB/T 10609.1 标题栏
TITLE_BANDS = (36.0, 24.0, 12.0)         # 标题栏行分界（自下而上，mm）


def _text_w(s: str, h: float) -> float:
    """估算单行文字宽度：汉字按 1 个字高，西文数字按 0.55 字高。"""
    return sum(h * (1.0 if ord(ch) > 127 else 0.55) for ch in s)


def _insert_tf(pt: tuple[float, float], ref: dict[str, Any]) -> tuple[float, float]:
    """块内局部点 -> 世界坐标（按 INSERT 的插入点/旋转/缩放）。"""
    g = ref["geometry"]
    ip = g["insert"]
    sc = g.get("scale") or {"x": 1.0, "y": 1.0}
    rot = float(g.get("rotation") or 0.0)
    c, s = math.cos(rot), math.sin(rot)
    x = float(pt[0]) * float(sc.get("x", 1.0) or 1.0)
    y = float(pt[1]) * float(sc.get("y", 1.0) or 1.0)
    return (ip["x"] + x * c - y * s, ip["y"] + x * s + y * c)


def drawing_extent(session: Session, pad: float = 0.0,
                   include_sheets: bool = False) -> tuple[float, float, float, float] | None:
    """整张图的外廓：墙、房间、门窗、轴号、尺寸线、表格文字全算进去（图幅自身默认排除）。

    自动排图必须按这个外廓走，否则尺寸线/轴号圈/表格会跑到图框外。
    """
    xs: list[float] = []
    ys: list[float] = []

    def add(x: float, y: float) -> None:
        xs.append(float(x))
        ys.append(float(y))

    cache: dict[str, list[dict[str, Any]]] = {}

    def block_pts(name: str) -> list[dict[str, Any]]:
        if name not in cache:
            cache[name] = block_geometry(session.path, name)
        return cache[name]

    for e in session.entities().get("entities", []):
        t = str(e.get("type", "")).lower()
        g = e.get("geometry") or {}
        if t == "line":
            for k in ("a", "b"):
                p = g.get(k)
                if p:
                    add(p["x"], p["y"])
        elif t in ("text", "mtext"):
            p = g.get("insert") or g.get("position")
            if p:
                h = float(g.get("height", 200) or 200)
                w = _text_w(str(g.get("value", "")), h)
                add(p["x"], p["y"])
                add(p["x"] + w, p["y"] + h)
        elif t == "circle":
            c = g.get("center") or {}
            r = float(g.get("radius", 0) or 0)
            if c:
                add(c["x"] - r, c["y"] - r)
                add(c["x"] + r, c["y"] + r)
        elif t == "block reference":
            name = str(g.get("block", ""))
            if not include_sheets and name.startswith("AA_SHEET_"):
                continue
            for gi in block_pts(name):
                for p in gi.get("pts") or []:
                    if p:
                        add(*_insert_tf(p, e))
                r = float(gi.get("r") or 0)
                for p in gi.get("pts") or []:
                    if p and r:
                        add(_insert_tf(p, e)[0] - r, _insert_tf(p, e)[1] - r)
                        add(_insert_tf(p, e)[0] + r, _insert_tf(p, e)[1] + r)
        elif t == "dimension":
            for k in ("p13", "p14", "defpt", "textMid"):
                p = g.get(k)
                if p and (abs(p.get("x", 0)) > 1e-9 or abs(p.get("y", 0)) > 1e-9):
                    add(p["x"], p["y"])

    if not xs:
        return None
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def _title_cells() -> list[dict[str, Any]]:
    """标题栏单元格（局部坐标，原点=标题栏左下角，单位 mm）。"""
    return [
        {"x": 0.0, "y": 36.0, "w": 180.0, "h": 20.0, "label": "", "key": "drawing", "size": 7.0},
        {"x": 0.0, "y": 24.0, "w": 120.0, "h": 12.0, "label": "工程名称", "key": "project", "size": 4.0},
        {"x": 120.0, "y": 24.0, "w": 60.0, "h": 12.0, "label": "图号", "key": "number", "size": 4.0},
        {"x": 0.0, "y": 12.0, "w": 60.0, "h": 12.0, "label": "设计", "key": "design", "size": 4.0},
        {"x": 60.0, "y": 12.0, "w": 60.0, "h": 12.0, "label": "制图", "key": "drawn", "size": 4.0},
        {"x": 120.0, "y": 12.0, "w": 60.0, "h": 12.0, "label": "审核", "key": "check", "size": 4.0},
        {"x": 0.0, "y": 0.0, "w": 60.0, "h": 12.0, "label": "比例", "key": "scale", "size": 4.0},
        {"x": 60.0, "y": 0.0, "w": 60.0, "h": 12.0, "label": "日期", "key": "date", "size": 4.0},
        {"x": 120.0, "y": 0.0, "w": 60.0, "h": 12.0, "label": "单位", "key": "unit", "size": 4.0},
    ]


def sheet_layout(size: str = "A3", scale: float = 100.0) -> dict[str, Any]:
    """图框几何参数（全部换算到模型单位，即图纸 mm × 比例分母）。"""
    size = size.upper()
    if size not in SHEETS:
        raise CadError("不支持的图幅：%s（可选 %s）" % (size, "、".join(SHEETS)))
    if scale <= 0:
        raise CadError("比例必须为正数")
    w_mm, h_mm = SHEETS[size]
    a = SHEET_BIND
    c = SHEET_EDGE[size]
    iw = (w_mm - a - c) * scale
    ih = (h_mm - 2 * c) * scale
    return {
        "size": size,
        "scale": float(scale),
        "sheet_w": w_mm * scale,
        "sheet_h": h_mm * scale,
        "outer": (0.0, 0.0, w_mm * scale, h_mm * scale),
        "inner_org": (a * scale, c * scale),
        "inner_w": iw,
        "inner_h": ih,
        "title_w": TITLE_W * scale,
        "title_h": TITLE_H * scale,
    }


def create_sheet(
    session: Session,
    sheet_id: str = "S001",
    size: str = "A3",
    scale: float | None = None,
    at: tuple[float, float] | None = None,
    project: str = "",
    drawing: str = "",
    number: str = "",
    date: str = "",
    design: str = "",
    drawn: str = "",
    check: str = "",
    unit: str = "",
    pad: float = 1500.0,
) -> dict[str, Any]:
    """图框 + 标题栏：按 GB/T 14689 幅面绘制，标题栏按 GB/T 10609.1 简化为 9 格。

    size 传 "ATUO"/"AUTO" 时按图形外廓自动挑"能放下的最小图幅"（A4→A0）。
    scale 省略时读图档比例标记 / 已有图幅；都没有按 1:100。
    at = 内框左下角（模型坐标）。不给则按图形外廓自动居中排图；
    图形超出内框时报错，提示换大图幅或调小比例。
    """
    if scale is None:
        scale = drawing_scale(session)
    size_text = str(size).strip().upper()
    auto = size_text in ("AUTO", "ATUO")
    promoted: list[str] = []
    if auto:
        size_text = "A3"
    lay = sheet_layout(size_text, float(scale))
    ext = drawing_extent(session, pad=0.0)
    order = ("A4", "A3", "A2", "A1", "A0")
    if size_text not in order:
        raise CadError("未知图幅 %s（可选 A0–A4 / AUTO）" % size_text)
    if ext and at is None:
        need_w = (ext[2] - ext[0]) + 2 * pad
        need_h = (ext[3] - ext[1]) + 2 * pad
        start = 0 if auto else order.index(size_text)
        chosen = None
        for i in range(start, len(order)):
            l = sheet_layout(order[i], float(scale))
            if need_w <= l["inner_w"] and need_h <= l["inner_h"]:
                chosen = (order[i], i, l)
                break
        if not chosen:
            raise CadError(
                "图形放不进 A0@1:%g（需 %.0f×%.0f，可用 %.0f×%.0f）：请调小比例或拆图"
                % (scale, need_w, need_h,
                   sheet_layout("A0", float(scale))["inner_w"],
                   sheet_layout("A0", float(scale))["inner_h"]))
        if chosen[0] != size_text:
            promoted.append("%s→%s" % (size_text, chosen[0]))
            size_text = chosen[0]
            lay = chosen[2]
    session.ensure_layers([LAYERS["border"], LAYERS["sheet"], LAYERS["title"]])
    block = "AA_SHEET_" + sheet_id
    if session.block_exists(block):
        raise CadError("图幅 %s 已存在，请用 set-sheet 修改或换编号" % sheet_id)

    # 自动排图：把图形外廓居中放进内框
    ext = drawing_extent(session, pad=0.0)
    if at is None:
        if ext:
            cx = (ext[0] + ext[2]) / 2.0
            cy = (ext[1] + ext[3]) / 2.0
            need_w = (ext[2] - ext[0]) + 2 * pad
            need_h = (ext[3] - ext[1]) + 2 * pad
            if need_w > lay["inner_w"] or need_h > lay["inner_h"]:
                raise CadError(
                    "图形放不进 %s@1:%g 内框（需 %.0f×%.0f，可用 %.0f×%.0f）："
                    "请换大图幅或调小比例" % (lay["size"], scale, need_w, need_h,
                                          lay["inner_w"], lay["inner_h"])
                )
            w_mm = SHEETS[lay["size"]][0]
            inner_cx = (w_mm + SHEET_BIND - SHEET_EDGE[lay["size"]]) * scale / 2.0
            inner_cy = lay["sheet_h"] / 2.0
            at = (cx - inner_cx, cy - inner_cy)
        else:
            at = (0.0, 0.0)
    at = (float(at[0]), float(at[1]))

    s = float(scale)
    iw, ih = lay["inner_w"], lay["inner_h"]
    ox0, oy0, ox1, oy1 = lay["outer"]          # 图幅外框：局部原点=图幅左下角
    ix, iy = lay["inner_org"]                  # 内框左下角（装订边 a / 其余边 c）
    segs: list[tuple[tuple[float, float], tuple[float, float], str]] = []

    def rect(x0: float, y0: float, x1: float, y1: float, layer: str) -> None:
        segs.append(((x0, y0), (x1, y0), layer))
        segs.append(((x1, y0), (x1, y1), layer))
        segs.append(((x1, y1), (x0, y1), layer))
        segs.append(((x0, y1), (x0, y0), layer))

    rect(ox0, oy0, ox1, oy1, LAYERS["border"])          # 幅面线：细线（GB/T 14689）
    rect(ix, iy, ix + iw, iy + ih, LAYERS["sheet"])

    # 标题栏：贴内框右下角，尺寸按图纸 mm × 比例
    tx0 = ix + iw - lay["title_w"]
    ty0 = iy
    tw, th = TITLE_W * s, TITLE_H * s
    rect(tx0, ty0, tx0 + tw, ty0 + th, LAYERS["sheet"])   # 标题栏外框用图框线（粗）
    for y in TITLE_BANDS:
        segs.append(((tx0, ty0 + y * s), (tx0 + tw, ty0 + y * s), LAYERS["title"]))
    for x in (60.0, 120.0):
        segs.append(((tx0 + x * s, ty0), (tx0 + x * s, ty0 + 24.0 * s), LAYERS["title"]))
    # 工程名称行（24~36）的 120 宽分格界线
    segs.append(((tx0 + 120.0 * s, ty0 + 24.0 * s), (tx0 + 120.0 * s, ty0 + 36.0 * s),
                 LAYERS["title"]))

    values = {"drawing": drawing, "project": project, "number": number, "design": design,
              "drawn": drawn, "check": check, "scale": ("1:%g" % scale), "date": date,
              "unit": unit}
    texts: list[tuple[tuple[float, float], str, str, float]] = []
    for cell in _title_cells():
        cx = tx0 + cell["x"] * s
        cy = ty0 + cell["y"] * s
        if cell["label"]:
            texts.append(((cx + 2.0 * s, cy + (cell["h"] - 4.5) * s),
                          cell["label"], LAYERS["title"], 2.5 * s))
        val = str(values.get(cell["key"], "") or "")
        if not val:
            continue
        hgt = cell["size"] * s
        w = _text_w(val, hgt)
        px = cx + max(2.0 * s, (cell["w"] * s - w) / 2.0)
        py = cy + (cell["h"] * s - hgt) / 2.0 + ((1.5 * s) if cell["label"] else 0.0)
        texts.append(((px, py), val, LAYERS["title"], hgt))

    before = session.snapshot()
    body = []
    for p1, p2, layer in segs:
        body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                    % (p1[0], p1[1], p2[0], p2[1], layer))
    for pt, txt, layer, hgt in texts:
        safe = txt.replace('"', "'")
        body.append('(aa:mktext-r (list %.3f %.3f) "%s" "%s" %.3f 0.0)'
                    % (pt[0], pt[1], safe, layer, hgt))
    session.lisp("(progn %s (princ \"ok\"))" % " ".join(body), libraries=("aa_core.lisp",))
    handles = session.new_handles(before)

    att_defs = [
        ("AA_TYPE", "component type", "SHEET"),
        ("AA_ID", "component id", sheet_id),
        ("AA_SIZE", "paper size", lay["size"]),
        ("AA_SCALE", "plot scale 1:n", "%g" % scale),
        ("AA_PROJECT", "project name", project),
        ("AA_DRAWING", "drawing title", drawing),
        ("AA_NO", "drawing number", number),
        ("AA_DATE", "date", date),
        ("AA_DESIGN", "designer", design),
        ("AA_DRAWN", "draftsman", drawn),
        ("AA_CHECK", "checker", check),
        ("AA_UNIT", "company", unit),
        ("AA_BIND", "binding margin", "%.1f" % SHEET_BIND),
    ]
    att_handles = session.define_attributes(att_defs)
    att_vals = {t: v for t, _d, v in att_defs}

    base_local = at
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, base_local, att_vals, layer=LAYERS["sheet"])
    session.expect_attributes(block, {"AA_ID": sheet_id, "AA_TYPE": "SHEET",
                                      "AA_SIZE": lay["size"], "AA_SCALE": "%g" % scale})

    # 回读：外框几何 = 图幅换算值，标题栏落在内框右下
    geom = block_geometry(session.path, block)
    xs = [p[0] for g in geom for p in g["pts"]]
    ys = [p[1] for g in geom for p in g["pts"]]
    got_w = max(xs) - min(xs)
    got_h = max(ys) - min(ys)
    if abs(got_w - lay["sheet_w"]) > 0.5 or abs(got_h - lay["sheet_h"]) > 0.5:
        raise CadError("图框尺寸回读不符：期望 %.0f×%.0f，实际 %.0f×%.0f"
                       % (lay["sheet_w"], lay["sheet_h"], got_w, got_h))
    n_lines = sum(1 for g in geom if g["type"] == "LINE")
    if n_lines != len(segs):
        raise CadError("图框线数回读不符：期望 %d，实际 %d" % (len(segs), n_lines))

    return {
        "block": block,
        "handle": handle,
        "size": lay["size"],
        "scale": float(scale),
        "at": list(at),
        "inner": [lay["inner_w"], lay["inner_h"]],
        "outer_wh": [lay["sheet_w"], lay["sheet_h"]],
        "lines": n_lines,
        "texts": sum(1 for g in geom if g["type"] == "TEXT"),
        "extent": ext,
        "drawing_scale": drawing_scale(session),
        "promoted": promoted[0] if promoted else None,
    }


def set_sheet(session: Session, sheet_id: str, **fields: Any) -> dict[str, Any]:
    """改标题栏内容：删旧图框重画（保持同一编号、同一位置、同一图幅比例）。"""
    block = "AA_SHEET_" + sheet_id
    ref = session.reference(block)
    if not ref:
        raise CadError("找不到图幅 %s" % sheet_id)
    attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in ref["geometry"].get("attribs", [])}
    params = {
        "size": attrs.get("AA_SIZE", "A3"),
        "scale": float(attrs.get("AA_SCALE", "100") or 100),
        "at": (ref["geometry"]["insert"]["x"], ref["geometry"]["insert"]["y"]),
        "project": attrs.get("AA_PROJECT", ""),
        "drawing": attrs.get("AA_DRAWING", ""),
        "number": attrs.get("AA_NO", ""),
        "date": attrs.get("AA_DATE", ""),
        "design": attrs.get("AA_DESIGN", ""),
        "drawn": attrs.get("AA_DRAWN", ""),
        "check": attrs.get("AA_CHECK", ""),
        "unit": attrs.get("AA_UNIT", ""),
    }
    params.update({k: v for k, v in fields.items() if v is not None})
    delete_component(session, block)
    return create_sheet(session, sheet_id, **params)


ACI_RGB = {
    1: (255, 60, 60), 2: (255, 235, 60), 3: (70, 230, 90), 4: (70, 220, 235),
    5: (80, 140, 255), 6: (230, 90, 230), 7: (240, 240, 240), 8: (150, 150, 150),
    9: (190, 190, 190),
}

LW_MIN_MM = 0.20          # 低于这个线宽按预览的 1px 细线处理，不再加粗


def _block_geometry_cached(path, name, cache):
    if name not in cache:
        cache[name] = block_geometry(path, name)
    return cache[name]


def emphasize_lineweights(session: Session, png: str | Path, window: Sequence[float],
                          scale: float, min_mm: float = LW_MIN_MM) -> dict[str, Any]:
    """在已导出的 PNG 上按图层线宽补粗线（预览用）。

    CADCraft 的 png 导出不画线宽（实测 0.7 与默认一样细），这里按“1 纸面 mm = scale 图纸单位”
    算出像素换算，把线宽 ≥ min_mm 的图元在同一位置重画成对应像素粗细，颜色取图层 ACI。
    只覆盖加粗，不改变细线，也不改 DXF 本身（打印仍按组 370 的真实线宽）。
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:                       # 没装 Pillow 就退化成原图，不报错
        return {"thickened": 0, "skipped": "no-pillow"}

    out = Path(png)
    img = Image.open(out).convert("RGB")
    draw = ImageDraw.Draw(img)
    w_px, h_px = img.size
    x0, y0, x1, y1 = [float(v) for v in window]
    # CLI 的 png 导出是"等比 fit 不裁切"：窗口按短边铺满，另一方向留黑边，
    # 所以像素换算必须用 min(宽比, 高比)，再把内容居中，否则补粗线会整体偏移。
    fit = min(w_px / (x1 - x0), h_px / (y1 - y0))
    ox = (w_px - (x1 - x0) * fit) / 2.0
    oy = (h_px - (y1 - y0) * fit) / 2.0
    px_per_mm = fit * float(scale)            # 1 mm 纸面 = scale 图纸单位

    table = layer_table(session.path)
    cache: dict[str, list] = {}
    thick = 0
    colored = 0
    pieces: list[tuple[list, dict, Any]] = []
    for ref in session.references():
        g = ref["geometry"]
        block = g.get("block")
        if not block:
            continue
        for e in _block_geometry_cached(session.path, block, cache):
            pieces.append((e["pts"], e, ref))
    for e in session.entities().get("entities", []):
        p = (e.get("geometry") or {}).get("pts")
        if p and len(p) >= 2 and e.get("type") not in ("Block Reference", "Dimension"):
            pieces.append((p, e, None))

    for pts, e, ref in pieces:
        lay = e.get("layer") or (ref.get("layer") if ref else None) or "0"
        spec = table.get(lay)
        if not spec:
            continue
        lw = float(spec["lineweight"])
        width = max(1, int(round(lw * px_per_mm)))
        rgb = ACI_RGB.get(spec["color"], (240, 240, 240))
        # 白线由 CLI 自己画；纸面线宽 ≥ 0.2 补粗；非白层（红轴/青门窗/黄楼梯/绿箭头）统一上色，
        # 这样预览跟天正的彩色预览一致，细线也能看出层色。
        if spec["color"] == 7 and width < 2:
            continue
        world = [_insert_tf((p[0], p[1]), ref) if ref else (p[0], p[1])
                 for p in pts if p]
        scr = [(ox + (p[0] - x0) * fit, oy + (y1 - p[1]) * fit) for p in world]
        for a, b in zip(scr, scr[1:]):
            draw.line([a, b], fill=rgb, width=width)
        if spec["color"] == 7 and e["type"] in ("LINE", "LWPOLYLINE"):
            thick += 1
        elif spec["color"] != 7:
            colored += 1
    img.save(out)
    return {"thickened": thick, "colored": colored, "px_per_mm": round(px_per_mm, 2)}


def export(session: Session, out: str | Path, window: Sequence[float] | None = None,
           lineweights: bool = True, scale: float | None = None) -> dict[str, Any]:
    """出图：png / svg / pdf 由扩展名决定；window=(x0,y0,x1,y1) 限定图幅范围。

    png 默认补画线宽（预览看得见粗墙/粗图框）；scale 省略时自动从图幅取比例，
    没有图幅按 1:100。svg/pdf 交给 CLI 原生输出，不补粗。
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = ["run", str(session.path), "--export", str(out)]
    if window:
        argv += ["--window=%g,%g,%g,%g" % tuple(window)]
    session._exec(argv)
    if not out.exists() or out.stat().st_size < 2048:
        raise CadError("导出失败或产物异常：%s" % out)
    res: dict[str, Any] = {"path": str(out), "bytes": out.stat().st_size}
    if lineweights and out.suffix.lower() == ".png" and window:
        s = scale if scale else None
        if s is None:
            for ref in session.references():
                attrs = {a["tag"]: a.get("text", {}).get("value", "")
                         for a in ref["geometry"].get("attribs", [])}
                if attrs.get("AA_TYPE") == "SHEET" and attrs.get("AA_SCALE"):
                    s = float(attrs["AA_SCALE"])
                    break
        res.update(emphasize_lineweights(session, out, window, s or 100.0))
    return res


def _pt_seg_dist(p: tuple[float, float], a: tuple[float, float],
                 b: tuple[float, float]) -> float:
    """点到线段距离（T 接判断用）。"""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    ln2 = dx * dx + dy * dy
    if ln2 <= 1e-12:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / ln2))
    return math.dist(p, (ax + t * dx, ay + t * dy))


def audit(session: Session, tol: float = 1.0) -> dict[str, Any]:
    """图面自检：把"画完看着不对"的常见问题先挑出来，别等到出图才发现。

    检查项（都不改图，只报问题）：
      1. `wall_endpoint` 墙端点没接上任何墙（漏墙/墙没画到）；
      2. `opening_outside` 门窗洞口跑出所属墙段；
      3. `room_text_overlap` 两个房间的名称/面积文字压在一起；
      4. `dim_over_axis` 尺寸文字压在轴号圈里；
      5. `outside_sheet` 有图幅时，图形外廓超出内框。
    返回 `{issues, count, by_kind, scale}`，issue 里带 `level`（error/warn）与 `handles`/`detail`。
    """
    issues: list[dict[str, Any]] = []

    def add(kind: str, level: str, message: str,
            handles: Sequence[str] = (), detail: str = "") -> None:
        issues.append({"kind": kind, "level": level, "message": message,
                       "handles": list(handles), "detail": detail})

    sc = drawing_scale(session)

    # 1) 墙端点是否接上（端点对端点，或落在别的墙身上 = T 接）
    walls = wall_data(session)
    for w in walls:
        for key, other_key in (("p1", "p2"), ("p2", "p1")):
            p = tuple(w[key])
            hit = math.dist(p, tuple(w[other_key])) <= tol
            for o in walls:
                if o["id"] == w["id"]:
                    continue
                if (math.dist(p, tuple(o["p1"])) <= tol or
                        math.dist(p, tuple(o["p2"])) <= tol or
                        _pt_seg_dist(p, tuple(o["p1"]), tuple(o["p2"])) <= tol):
                    hit = True
                    break
            if not hit:
                add("wall_endpoint", "error",
                    "墙 %s 的 %s 端没接上别的墙" % (w["id"], key),
                    handles=[w.get("handle", "")], detail="%s=(%.3f, %.3f)" % (key, p[0], p[1]))

    # 2) 门窗是否跑出墙段
    for o in opening_data(session):
        info = wall_info(session, o["wallid"]) if o.get("wallid") else None
        if not info:
            continue
        if o["pos"] - o["width"] / 2.0 < -tol or o["pos"] + o["width"] / 2.0 > info["length"] + tol:
            add("opening_outside", "error",
                "门窗 %s 超出墙 %s 长度（洞口中心 %.1f，宽 %.1f，墙长 %.1f）"
                % (o["id"], o["wallid"], o["pos"], o["width"], info["length"]),
                handles=[o.get("handle", "")])

    # 3) 房间文字互相重叠
    def _texts(block: str) -> list[tuple[str, tuple[float, float, float, float], str]]:
        out = []
        for g in block_geometry(session.path, block):
            if g["type"] not in ("TEXT", "MTEXT") or not g.get("pts"):
                continue
            tx, ty = g["pts"][0]
            th = float(g.get("h") or 0) or annot_size(2.5, sc)
            out.append((block, (tx, ty, tx + _text_w(g["text"], th), ty + th), g["text"]))
        return out

    room_boxes = []
    for r in room_data(session):
        for block, box, text in _texts(r["block"]):
            room_boxes.append((r["id"], box, text))
    for i in range(len(room_boxes)):
        for j in range(i + 1, len(room_boxes)):
            a, b = room_boxes[i][1], room_boxes[j][1]
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                add("room_text_overlap", "warn",
                    "房间文字重叠：%s「%s」× %s「%s」"
                    % (room_boxes[i][0], room_boxes[i][2],
                       room_boxes[j][0], room_boxes[j][2]))

    # 4) 尺寸文字压轴号圈
    circles = []
    for e in session.components("AA_AXGRID_"):
        for g in block_geometry(session.path, e["geometry"]["block"]):
            if g["type"] == "CIRCLE" and g.get("pts"):
                circles.append((g["pts"][0][0], g["pts"][0][1], float(g.get("r") or 0)))
    dim_h = annot_size(2.5, sc)
    if circles:
        for e in session.entities().get("entities", []):
            if e.get("type") != "Dimension":
                continue
            mid = (e.get("geometry") or {}).get("textMid")
            if not mid:
                continue
            for cx, cy, r in circles:
                if math.dist((mid["x"], mid["y"]), (cx, cy)) <= r + dim_h / 2.0:
                    add("dim_over_axis", "warn",
                        "尺寸文字 %.0f 压在轴号圈里（圈心 %.0f, %.0f）"
                        % (float((e.get("geometry") or {}).get("measurement") or 0), cx, cy),
                        handles=[e.get("handle", "")])
                    break

    # 5) 图形外廓是否在图幅内框里
    # 多图幅（图纸集）时不能拿全图外廓去比单张图幅——各图并排在同一模型空间，
    # 改判"外廓落在所有图幅内框的并集里"，并检查图幅之间不重叠。
    ext = drawing_extent(session, pad=0.0)
    frames = []
    for e in session.components("AA_SHEET_"):
        attrs = {a["tag"]: a.get("text", {}).get("value", "")
                 for a in e["geometry"].get("attribs", [])}
        lay = sheet_layout(attrs.get("AA_SIZE", "A3"),
                           float(attrs.get("AA_SCALE", "100") or 100))
        ip = e["geometry"]["insert"]
        x0, y0 = ip["x"], ip["y"]        # insert 点是内框左下角
        frames.append({"id": attrs.get("AA_ID", e["geometry"]["block"]),
                       "handle": e.get("handle", ""),
                       "box": (x0, y0, x0 + lay["inner_w"], y0 + lay["inner_h"])})
    if len(frames) == 1:
        b = frames[0]["box"]
        if ext and (ext[0] < b[0] - tol or ext[1] < b[1] - tol
                    or ext[2] > b[2] + tol or ext[3] > b[3] + tol):
            add("outside_sheet", "error",
                "图形外廓超出图幅 %s 的外框" % frames[0]["id"],
                handles=[frames[0]["handle"]], detail="ext=%r sheet=%r" % (ext, b))
    elif len(frames) > 1:
        ux0 = min(f["box"][0] for f in frames)
        uy0 = min(f["box"][1] for f in frames)
        ux1 = max(f["box"][2] for f in frames)
        uy1 = max(f["box"][3] for f in frames)
        if ext and (ext[0] < ux0 - tol or ext[1] < uy0 - tol
                    or ext[2] > ux1 + tol or ext[3] > uy1 + tol):
            add("outside_sheet", "error",
                "图形外廓超出图纸集全部图幅的并集",
                detail="ext=%r union=%r" % (ext, (ux0, uy0, ux1, uy1)))
        for i, a in enumerate(frames):
            for b in frames[i + 1:]:
                ov = (min(a["box"][2], b["box"][2]) - max(a["box"][0], b["box"][0])
                      > tol and min(a["box"][3], b["box"][3])
                      - max(a["box"][1], b["box"][1]) > tol)
                if ov:
                    add("sheet_overlap", "error",
                        "图幅 %s 与 %s 的外框重叠（出图会互相框进来）"
                        % (a["id"], b["id"]),
                        handles=[a["handle"], b["handle"]],
                        detail="%r vs %r" % (a["box"], b["box"]))

    by_kind: dict[str, int] = {}
    for it in issues:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    return {"issues": issues, "count": len(issues), "by_kind": by_kind,
            "errors": sum(1 for it in issues if it["level"] == "error"), "scale": sc}


def sheet_window(session: Session, sheet_id: str) -> list[float]:
    """图幅的导出窗口：外框四条边（含 5% 余量）。"""
    block = "AA_SHEET_" + sheet_id
    ref = session.reference(block)
    if not ref:
        raise CadError("找不到图幅 %s" % sheet_id)
    attrs = {a["tag"]: a.get("text", {}).get("value", "") for a in ref["geometry"].get("attribs", [])}
    lay = sheet_layout(attrs.get("AA_SIZE", "A3"), float(attrs.get("AA_SCALE", "100") or 100))
    ip = ref["geometry"]["insert"]
    x, y = ip["x"], ip["y"]
    w = lay["sheet_w"]
    h = lay["sheet_h"]
    m = 0.05 * max(w, h)
    return [x - m, y - m, x + w + m, y + h + m]


# ---------------- 楼层复制（v1.0.34） ----------------

def copy_floor(session: Session, src_floor: int, dst_floor: int,
               offset: Sequence[float] = (0.0, 0.0),
               prefix: str = "") -> dict[str, Any]:
    """整层复制：把源层的墙 / 门窗 / 房间按偏移复制到目标层，层号自动改写。

    做法是"按构件数据重建"而不是拷贝图元：源层从 `AA_FLOOR` 过滤墙，
    逐堵墙 `create_wall`（新编号、新层号）、逐樘门 `create_opening`（宿主墙换成新墙）、
    逐个房间 `create_room`（墙号换成新墙，面积重算并校验与源层一致），
    所以新层是完整的可回读构件，不是一堆断开的线。

    prefix 是新编号前缀（强烈建议按层给，如 "2" → 2W001 / 2M001 / 2R001）；
    留空且与源层编号冲突时直接报错，不静默改号。目标层已有构件也拒绝（避免叠图）。
    楼梯、柱、台阶、散水暂不复制（它们没有 AA_FLOOR，见文档 §33.4）。
    """
    src = int(src_floor)
    dst = int(dst_floor)
    if src < 1 or dst < 1:
        raise CadError("层号必须 ≥ 1（收到 源 %r / 目标 %r）" % (src_floor, dst_floor))
    if src == dst:
        raise CadError("源层与目标层不能相同（都是 %d 层）" % src)
    if len(offset) != 2:
        raise CadError("偏移要给 dx,dy 两个数：%r" % (offset,))
    dx, dy = float(offset[0]), float(offset[1])
    walls = [w for w in wall_data(session) if w["floor"] == src]
    if not walls:
        raise CadError("源层 %d 没有墙（AA_FLOOR）可复制" % src)
    if any(w["floor"] == dst for w in wall_data(session)):
        raise CadError("目标层 %d 已有墙，拒绝叠图（先删旧层或换层号）" % dst)
    pre = str(prefix)

    def new_id(old: str) -> str:
        return pre + old

    existing = {w["id"] for w in wall_data(session)}
    clash = [w["id"] for w in walls if new_id(w["id"]) in existing]
    if clash:
        raise CadError("新墙编号与图上已有墙冲突（给 prefix 换号）：%s" % ", ".join(clash[:4]))

    wall_map: dict[str, str] = {}
    made_walls = []
    for w in walls:
        nid = new_id(w["id"])
        res = create_wall(session, nid,
                          (w["p1"][0] + dx, w["p1"][1] + dy),
                          (w["p2"][0] + dx, w["p2"][1] + dy),
                          thick=w["thick"], kind=w["kind"], mat=w["mat"],
                          ax1=w["ax1"], ax2=w["ax2"], floor=dst)
        wall_map[w["id"]] = nid
        made_walls.append(nid)

    made_ops, skipped_ops = [], []
    for o in opening_data(session):
        if o["floor"] != src:
            continue
        host = wall_map.get(o["wallid"])
        if not host:
            skipped_ops.append({"id": o["id"], "why": "宿主墙不在源层"})
            continue
        nid = new_id(o["id"])
        create_opening(session, nid, host, o["kind"], o["width"], o["pos"],
                       height=o["height"], sill=o["sill"], frame=o["frame"],
                       no=o["no"], label_side=o["labelside"])
        made_ops.append(nid)

    src_rooms = [r for r in room_data(session)
                 if r["walls"] and all(w in wall_map for w in r["walls"])]
    made_rooms, skipped_rooms = [], []
    for r in room_data(session):
        if not r["walls"]:
            continue
        if not all(w in wall_map for w in r["walls"]):
            skipped_rooms.append({"id": r["id"], "why": "围合墙不在源层"})
            continue
        nid = new_id(r["id"])
        create_room(session, nid, [wall_map[w] for w in r["walls"]],
                    name=r["name"], show_area=r["show_area"])
        made_rooms.append(nid)

    # 回读校验：层号、数量、面积
    back_walls = [w for w in wall_data(session) if w["floor"] == dst]
    if sorted(w["id"] for w in back_walls) != sorted(made_walls):
        raise CadError("楼层复制回读不符：写 %d 堵 / 读 %d 堵" % (len(made_walls), len(back_walls)))
    back_ops = [o for o in opening_data(session) if o["floor"] == dst]
    if len(back_ops) != len(made_ops):
        raise CadError("楼层复制回读不符：门窗 写 %d / 读 %d" % (len(made_ops), len(back_ops)))
    area_ok = True
    for old, nid in zip(src_rooms, made_rooms):
        new_area = next((r["area"] for r in room_data(session) if r["id"] == nid), None)
        if new_area is None or abs(new_area - old["area"]) > 1.0:
            area_ok = False
    if not area_ok:
        raise CadError("复制后房间面积与源层不一致（墙厚/偏移把环弄断了）")

    return {"ok": True, "src": src, "dst": dst, "offset": [dx, dy],
            "walls": made_walls, "openings": made_ops, "rooms": made_rooms,
            "counts": {"walls": len(made_walls), "openings": len(made_ops),
                       "rooms": len(made_rooms)},
            "skipped_openings": skipped_ops, "skipped_rooms": skipped_rooms}


# ---------------- 图纸集 / 图纸目录 / 批量出图（v1.0.33） ----------------

SHEET_INDEX_HEADER = ["序号", "图号", "图名", "图幅", "比例", "备注"]


def _sheet_info(session: Session, sheet_id: str) -> dict[str, Any]:
    """读一张图幅的幅面与比例（图纸集校验/目录用）。"""
    ref = session.reference("AA_SHEET_" + sheet_id)
    if not ref:
        raise CadError("找不到图幅 %s" % sheet_id)
    attrs = {a["tag"]: a.get("text", {}).get("value", "")
             for a in ref["geometry"].get("attribs", [])}
    return {
        "sheet": sheet_id,
        "size": (attrs.get("AA_SIZE") or "A3").upper(),
        "scale": float(attrs.get("AA_SCALE") or drawing_scale(session)),
    }


def _sheet_item_rows(items: list[dict[str, Any]]) -> str:
    cols = []
    for it in items:
        cols.append("~".join([it["no"], it["name"], it["sheet"],
                              "%.6g" % it["scale"], it["size"],
                              it.get("note", "")]))
    return "@@".join(cols)


def create_sheet_set(session: Session, set_id: str,
                     items: list[dict[str, Any]]) -> dict[str, Any]:
    """图纸集：登记"图号 → 图名 → 图幅 → 比例"，是批量出图与图纸目录的唯一数据源。

    items 每项 `{no, name, sheet, note?}`：no=图号（如 建施-01），name=图名，
    sheet=图幅编号（图上已有 `AA_SHEET_<编号>`）。比例与图幅从图幅本身读，不手填，
    避免"目录写 A2、图框是 A3"这类错。图号重复、图幅不存在、同一图幅被两张图占用都拒绝。
    """
    sid = str(set_id).strip()
    if not sid or "~" in sid or "@@" in sid:
        raise CadError("图纸集编号不能为空且不能含 ~ / @@：%r" % (set_id,))
    if session.reference("AA_SHEETSET_" + sid):
        raise CadError("图纸集 %s 已存在（不覆盖，改图号请删旧建新）" % sid)
    if not items:
        raise CadError("图纸集不能为空：至少登记一张图")
    seen_no, seen_sheet, rows = set(), set(), []
    for it in items:
        no = str(it.get("no", "")).strip()
        name = str(it.get("name", "")).strip()
        sheet = str(it.get("sheet", "")).strip()
        note = str(it.get("note", "")).strip()
        if not no or not name or not sheet:
            raise CadError("图纸集每项都要有 图号 / 图名 / 图幅：%r" % (it,))
        for s in (no, name, note):
            if "~" in s or "@@" in s:
                raise CadError("图号/图名/备注不能含 ~ 或 @@：%r" % (s,))
        if no in seen_no:
            raise CadError("图号重复：%s" % no)
        if sheet in seen_sheet:
            raise CadError("图幅 %s 已被另一张图占用（一张图幅只登记一张图）" % sheet)
        info = _sheet_info(session, sheet)
        seen_no.add(no)
        seen_sheet.add(sheet)
        rows.append({"no": no, "name": name, "sheet": sheet,
                     "scale": info["scale"], "size": info["size"], "note": note})
    atts = session.define_attributes([
        ("AA_TYPE", "component type", "SHEETSET"),
        ("AA_ID", "sheet set id", sid),
        ("AA_COUNT", "sheet count", str(len(rows))),
        ("AA_ITEMS", "no~name~sheet~scale~size~note @@ rows", _sheet_item_rows(rows)),
    ])
    block = "AA_SHEETSET_" + sid
    session.make_block(block, (0.0, 0.0), atts)
    values = {"AA_TYPE": "SHEETSET", "AA_ID": sid, "AA_COUNT": str(len(rows)),
              "AA_ITEMS": _sheet_item_rows(rows)}
    session.insert(block, (0.0, 0.0), values)
    back = read_sheet_set(session, sid)
    if len(back["items"]) != len(rows):
        raise CadError("图纸集回读条目数不符：写入 %d / 回读 %d"
                       % (len(rows), len(back["items"])))
    return {"ok": True, "block": block, "id": sid, "count": len(rows),
            "items": back["items"]}


def read_sheet_set(session: Session, set_id: str) -> dict[str, Any]:
    """回读图纸集：`{id, count, items:[{no,name,sheet,size,scale,note}]}`。"""
    attrs = session.attributes("AA_SHEETSET_" + set_id)
    if not attrs or attrs.get("AA_TYPE") != "SHEETSET":
        raise CadError("没找到图纸集 %s" % set_id)
    items = []
    for r in (attrs.get("AA_ITEMS") or "").split("@@"):
        if not r:
            continue
        c = r.split("~")
        if len(c) < 6:
            raise CadError("图纸集条目解析不了：%r" % r)
        items.append({"no": c[0], "name": c[1], "sheet": c[2],
                      "scale": float(c[3] or 0), "size": c[4], "note": c[5]})
    return {"id": attrs.get("AA_ID") or set_id,
            "count": int(float(attrs.get("AA_COUNT") or len(items))), "items": items}


def create_sheet_index(session: Session, set_id: str, table_id: str,
                       at: tuple[float, float], title: str = "图纸目录",
                       note: str = "", widths: list[float] | None = None,
                       scale: float | None = None,
                       with_scale: bool = False) -> dict[str, Any]:
    """图纸目录：按图纸集自动生成"序号/图号/图名/图幅/比例/备注"表。

    `with_scale=True` 标题后面带出图比例（目录一般不注，默认不带）。
    """
    st = read_sheet_set(session, set_id)
    sc = float(scale) if scale else drawing_scale(session)
    rows = []
    for i, it in enumerate(st["items"], 1):
        rows.append([str(i), it["no"], it["name"], it["size"],
                     "1:%g" % it["scale"] if it["scale"] else "-", it["note"]])
    if widths is None:
        widths = [10.0, 26.0, 74.0, 14.0, 16.0, 26.0]
    res = draw_table(session, at, title, SHEET_INDEX_HEADER, rows,
                     [w * sc for w in widths], row_height=5.0 * sc,
                     text_height=3.0 * sc, table_id=table_id, scale=sc)
    session.run([("attedit", {"handle": res["handle"],
                              "values": {"AA_TYPE": "SHEET_INDEX"}})], save=True)
    attrs = session.attributes(res["block"])
    if attrs.get("AA_TYPE") != "SHEET_INDEX":
        raise CadError("图纸目录 AA_TYPE 回写失败：%s" % attrs.get("AA_TYPE"))
    if note:
        hgt = 2.5 * sc
        nx, ny = res["at"][0], res["at"][1] - res["height"] - 6.0 * sc
        session.lisp(
            '(progn (aa:mktext-r (list %.3f %.3f) "%s" "AA-TABLE" %.3f 0.0) (princ "ok"))'
            % (nx, ny, note.replace('"', "'"), hgt),
            libraries=("aa_core.lisp",),
        )
    return {"ok": True, "block": res["block"], "id": table_id, "set": set_id,
            "handle": res["handle"], "at": res["at"], "width": res["width"],
            "height": res["height"], "count": len(rows), "note": note}


def read_sheet_index(session: Session, table_id: str) -> list[dict[str, Any]]:
    """回读图纸目录（表体数据）。"""
    attrs = session.attributes("AA_TABLE_" + table_id)
    if not attrs or attrs.get("AA_TYPE") != "SHEET_INDEX":
        raise CadError("没找到图纸目录 %s" % table_id)
    out = []
    for r in (attrs.get("AA_ROWS") or "").split("@@"):
        if not r:
            continue
        c = r.split("~") + [""] * 6
        out.append({"no": c[1], "name": c[2], "size": c[3],
                    "scale": c[4], "note": c[5]})
    return out


def _safe_file_stem(text: str) -> str:
    """图号/图名转安全文件名：去掉 Windows 非法字符，空白压成一个下划线。"""
    bad = '\\/:*?"<>|'
    s = "".join(" " if ch in bad else ch for ch in text)
    return "_".join(s.split())


def export_sheet_set(session: Session, set_id: str, outdir: str | Path,
                     fmt: str = "png", prefix: str = "") -> dict[str, Any]:
    """按图纸集批量出图：一张图幅一个文件，命名 `图号 图名.扩展名`。

    图幅窗口取 `sheet_window`（外框含 5% 余量）；每张出完立刻校验产物存在且 > 2KB，
    缺一张就整体报错并列出已完成清单，避免"报了成功却少一张"。
    """
    fmt = fmt.lower().lstrip(".")
    if fmt not in ("png", "svg", "pdf"):
        raise CadError("只支持 png / svg / pdf：%r" % fmt)
    st = read_sheet_set(session, set_id)
    out_dir = Path(outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for it in st["items"]:
        stem = _safe_file_stem(("%s %s" % (prefix, it["no"])) if prefix else it["no"])
        out = out_dir / ("%s_%s.%s" % (stem, _safe_file_stem(it["name"]), fmt))
        window = sheet_window(session, it["sheet"])
        try:
            res = export(session, out, window=window)
        except Exception as exc:
            raise CadError("图纸集出图失败（已完成 %d/%d）：%s → %s：%s"
                           % (len(files), st["count"], it["no"], out.name, exc))
        files.append({"no": it["no"], "name": it["name"], "sheet": it["sheet"],
                      "path": str(out), "bytes": res["bytes"]})
    return {"ok": True, "set": set_id, "count": len(files),
            "outdir": str(out_dir), "format": fmt, "files": files}


# ---------------- 参数变更重绘（v0.4） ----------------

def _validate_opening_slot(session: Session, wall_len: float, pos: float, width: float,
                           wall_id: str, exclude: str = "", tol: float = 1e-6) -> None:
    """洞口落位校验：宽度为正、完全落在墙段内、与同墙其它洞口不重叠。"""
    if width <= 0:
        raise CadError("拒绝修改：洞口宽度必须为正实数（收到 %s）" % width)
    lo, hi = pos - width / 2.0, pos + width / 2.0
    if lo < -tol or hi > wall_len + tol:
        raise CadError(
            "拒绝修改：洞口 [%.4f, %.4f] 超出墙 %s 的可用范围 [0, %.4f]"
            % (lo, hi, wall_id, wall_len)
        )
    for oid, opos, owidth in _openings_on_wall(session, wall_id):
        if oid == exclude:
            continue
        olo, ohi = opos - owidth / 2.0, opos + owidth / 2.0
        if min(hi, ohi) - max(lo, olo) > tol:
            raise CadError(
                "拒绝修改：洞口与同墙洞口 %s [%.4f, %.4f] 重叠" % (oid, olo, ohi)
            )


def set_wall(session: Session, wall_id: str, thick: float | None = None,
             kind: str | None = None, mat: str | None = None,
             ax1: str | None = None, ax2: str | None = None,
             tol: float = 1e-6) -> dict[str, Any]:
    """改墙厚/类型/材质/轴号后重绘：洞口符号与邻墙裁剪一起重建。

    只改属性不动几何的函数没有存在意义——墙厚变了，两侧墙面线、洞口边线长度、
    邻墙的裁剪区全都跟着变，所以这里走"整体重建"而不是改属性值。
    """
    walls = wall_data(session)
    by_id = {w["id"]: w for w in walls}
    w = by_id.get(wall_id)
    if not w:
        raise CadError("找不到墙 %s" % wall_id)

    new_thick = w["thick"] if thick is None else float(thick)
    if new_thick <= 0:
        raise CadError("拒绝修改：墙厚必须为正实数（收到 %s）" % new_thick)

    seg = {
        **w,
        "thick": new_thick,
        "kind": kind or w["kind"],
        "mat": w.get("mat", "") if mat is None else mat,
        "ax1": w.get("ax1", "") if ax1 is None else ax1,
        "ax2": w.get("ax2", "") if ax2 is None else ax2,
        "root": w["root"] or w["id"],
    }

    openings = [o for o in opening_data(session) if o["wallid"] == wall_id]
    for o in openings:
        lo, hi = o["pos"] - o["width"] / 2.0, o["pos"] + o["width"] / 2.0
        if lo < -tol or hi > w["len"] + tol:
            raise CadError("拒绝修改：既有洞口 %s 已超出该墙段范围" % o["id"])

    holes = [(o["pos"] - o["width"] / 2.0, o["pos"] + o["width"] / 2.0) for o in openings]
    others = [x for x in walls if x["id"] != wall_id]
    sides = wall_sides(seg, others, holes=holes)

    plan = [{**o, "host": wall_id, "new_pos": o["pos"]} for o in openings]
    _apply_layout(session, [w], [seg], {wall_id: sides}, plan)
    # 墙厚变了，邻墙的裁剪与合角必须跟着重算
    normalized = normalize_around(session, wall_id)

    attrs = session.attributes("AA_WALL_" + wall_id)
    if abs(float(attrs["AA_THICK"]) - new_thick) > 1e-4:
        raise CadError("回读校验失败：AA_THICK=%s，期望 %.4f" % (attrs["AA_THICK"], new_thick))
    if attrs.get("AA_KIND") != seg["kind"]:
        raise CadError("回读校验失败：AA_KIND=%s，期望 %s" % (attrs.get("AA_KIND"), seg["kind"]))

    return {
        "wall": wall_id,
        "thick": new_thick,
        "kind": seg["kind"],
        "len": w["len"],
        "openings_rebuilt": [o["id"] for o in openings],
        "sides": [tuple(round(v, 4) for v in s) for s in sides],
        "normalized": normalized,
    }


def set_opening(session: Session, opening_id: str, pos: float | None = None,
                width: float | None = None, height: float | None = None,
                sill: float | None = None, kind: str | None = None,
                frame: float | None = None, no: str | None = None,
                label_side: str | None = None,
                tol: float = 1e-6) -> dict[str, Any]:
    """改门窗位置/宽度/类型/窗框厚/编号/编号侧向后重绘：符号重画，所属墙洞口同步重排。"""
    od = {o["id"]: o for o in opening_data(session)}
    o = od.get(opening_id)
    if not o:
        raise CadError("找不到门窗 %s" % opening_id)

    wall = wall_info(session, o["wallid"])
    new_pos = o["pos"] if pos is None else float(pos)
    new_width = o["width"] if width is None else float(width)
    new_height = o["height"] if height is None else float(height)
    new_sill = o["sill"] if sill is None else float(sill)
    new_kind = kind or o["kind"]
    new_frame = (o.get("frame") or 60.0) if frame is None else float(frame)
    new_no = (o.get("no") or "") if no is None else no
    new_side = (o.get("labelside") or "in") if label_side is None else label_side

    # 先校验，校验不过就一个字节都不动
    _validate_opening_slot(session, wall["length"], new_pos, new_width, o["wallid"],
                           exclude=opening_id, tol=tol)

    backup = session.path.with_name(session.path.stem + ".bak" + session.path.suffix)
    shutil.copy2(session.path, backup)
    try:
        delete_component(session, o["block"])
        create_opening(session, opening_id, o["wallid"], new_kind, new_width, new_pos,
                       height=new_height, sill=new_sill, frame=new_frame, no=new_no,
                       label_side=new_side)
    except Exception:
        shutil.copy2(backup, session.path)
        raise
    finally:
        if backup.exists():
            backup.unlink()

    attrs = session.attributes("AA_OPENING_" + opening_id)
    if abs(float(attrs["AA_POS"]) - new_pos) > 1e-4:
        raise CadError("回读校验失败：AA_POS=%s，期望 %.4f" % (attrs["AA_POS"], new_pos))
    if abs(float(attrs["AA_WIDTH"]) - new_width) > 1e-4:
        raise CadError("回读校验失败：AA_WIDTH=%s，期望 %.4f" % (attrs["AA_WIDTH"], new_width))

    return {
        "opening": opening_id,
        "wall": o["wallid"],
        "pos": new_pos,
        "width": new_width,
        "kind": new_kind,
        "height": new_height,
        "frame": new_frame,
        "no": new_no,
    }


def set_room(session: Session, room_id: str, name: str | None = None) -> dict[str, Any]:
    """改房间名称并重绘名称文字。

    房间几何只有一个名称 TEXT，属性改不了它，所以走"整体重建"：
    校验 → 备份 → 摘除旧参照与块定义 → 用已存的 AA_PTS 轮廓重画 → 回读断言 → 删备份。
    AA_PTS 是房间创建时存下的净空轮廓点串（"x,y;x,y;..."），因此改名不必重算墙环。
    """
    rooms = {r["id"]: r for r in room_data(session)}
    r = rooms.get(room_id)
    if not r:
        known = ", ".join(sorted(rooms)) or "（图纸里没有房间）"
        raise CadError("找不到房间 %s；现有房间：%s" % (room_id, known))

    new_name = r["name"] if name is None else name
    if new_name == r["name"]:
        return {"room": room_id, "name": new_name, "changed": 0}
    if not r["pts"]:
        raise CadError("拒绝修改：房间 %s 缺少轮廓数据（旧版图纸），请用 room/room --auto 重建"
                       % room_id)

    backup = session.path.with_name(session.path.stem + ".bak" + session.path.suffix)
    shutil.copy2(session.path, backup)
    try:
        delete_component(session, r["block"])
        res = _store_room(session, room_id, list(r["pts"]), r["area"], r["walls"], new_name,
                          show_area=r.get("show_area", True))
    except Exception:
        shutil.copy2(backup, session.path)
        raise
    finally:
        if backup.exists():
            backup.unlink()

    attrs = session.attributes("AA_ROOM_" + room_id)
    if attrs.get("AA_NAME") != new_name:
        raise CadError("回读校验失败：AA_NAME=%r，期望 %r" % (attrs.get("AA_NAME"), new_name))
    if abs(float(attrs.get("AA_AREA", "0")) - r["area"]) > 1e-2:
        raise CadError("回读校验失败：改名的同时面积变了（%s -> %s）"
                       % (r["area"], attrs.get("AA_AREA")))
    return {"room": room_id, "name": new_name, "changed": 1,
            "area": res["area"], "perimeter": res["perimeter"]}


def draw_table(session: Session, table_at: tuple[float, float], title: str,
               header: list[str], body: list[list[str]], widths: list[float],
               row_height: float | None = None, text_height: float | None = None,
               table_id: str = "", scale: float | None = None) -> dict[str, Any]:
    """在图上画一张表：纯几何（线框 + 居中文字），列宽行高完全按图纸 mm 控制。

    原生 table 命令的列宽不受控（文字会溢出到邻列），所以这里用线 + 文字自绘；
    at 仍然是表格**左上角**，表格向下生长。
    表格按 mm 取规格（行高 4mm、字高 2.5mm），并包成 AA_TABLE_<编号> 块，
    把标题/表头/数据/列宽存进属性，换出图比例时可原样重画（v0.9.5）。
    """
    lay = LAYERS.get("table", LAYERS["dim"])
    session.ensure_layers([lay])
    sc = float(scale) if scale else drawing_scale(session)
    if row_height is None:
        row_height = annot_size(4.0, sc)
    if text_height is None:
        text_height = annot_size(2.5, sc)
    if not table_id:
        n = len(session.components("AA_TABLE_")) + 1
        table_id = "T%03d" % n
    block = "AA_TABLE_" + table_id
    if session.block_exists(block):
        raise CadError("表格 %s 已存在，请换编号" % table_id)
    ncol = len(widths)
    title_h = row_height * 1.15
    data_rows = [[str(c) for c in r] for r in body]
    rows = [[title], list(header)] + data_rows
    heights = [title_h, row_height] + [row_height] * len(body)
    total_w = sum(widths)
    total_h = sum(heights)
    x0 = float(table_at[0])
    y0 = float(table_at[1])

    body: list[str] = []

    def seg(x1: float, y1: float, x2: float, y2: float) -> None:
        body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                    % (x1, y1, x2, y2, lay))

    def txt(cx: float, cy: float, s: str, hgt: float) -> None:
        if not s:
            return
        w = _text_w(s, hgt)
        body.append('(aa:mktext-r (list %.3f %.3f) "%s" "%s" %.3f 0.0)'
                    % (cx - w / 2.0, cy - hgt / 2.0, s.replace('"', "'"), lay, hgt))

    # 横线（每行分界 + 上下边）
    y = y0
    seg(x0, y, x0 + total_w, y)
    for h in heights:
        y -= h
        seg(x0, y, x0 + total_w, y)

    # 竖线：标题行整格，其余按列宽分
    seg(x0, y0, x0, y0 - total_h)
    seg(x0 + total_w, y0, x0 + total_w, y0 - total_h)
    col_x = [x0]
    for w in widths:
        col_x.append(col_x[-1] + w)
    for x in col_x[1:-1]:
        seg(x, y0 - title_h, x, y0 - total_h)

    # 文字
    y_top = y0
    for ri, line in enumerate(rows):
        h = heights[ri]
        cy = y_top - h / 2.0
        if ri == 0:
            txt(x0 + total_w / 2.0, cy, title, text_height * 1.25)
        else:
            hgt = text_height * (1.1 if ri == 1 else 1.0)
            for ci in range(ncol):
                cell = line[ci] if ci < len(line) else ""
                if str(cell).strip():
                    txt((col_x[ci] + col_x[ci + 1]) / 2.0, cy, str(cell), hgt)
        y_top -= h

    before = session.snapshot()
    session.lisp("(progn %s (princ \"ok\"))" % " ".join(body), libraries=("aa_core.lisp",))
    handles = session.new_handles(before)

    # 属性里存一份可重建的表格数据：列用 ~ 分隔、行用 @@ 分隔
    att_defs = [
        ("AA_TYPE", "component type", "TABLE"),
        ("AA_ID", "component id", table_id),
        ("AA_TITLE", "table title", title),
        ("AA_HEADER", "header cells", "~".join(str(x) for x in header)),
        ("AA_ROWS", "rows", "@@".join("~".join(r) for r in data_rows)),
        ("AA_WIDTHS", "column widths", "~".join("%.2f" % w for w in widths)),
        ("AA_ATX", "anchor x", "%.4f" % x0),
        ("AA_ATY", "anchor y", "%.4f" % y0),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=lay)
    return {"at": [x0, y0], "width": total_w, "height": total_h,
            "by": "geometry", "rows": len(rows), "cols": ncol,
            "block": block, "id": table_id, "handle": handle}


FLOOR_HEADER = ["层号", "楼层标高", "层高", "平面图号", "层名"]


def create_floor_table(
    session: Session,
    table_id: str,
    at: tuple[float, float],
    floors: list[dict[str, Any]],
    title: str = "楼层表",
    scale: float | None = None,
    widths: list[float] | None = None,
) -> dict[str, Any]:
    """楼层表：各层层号 / 标高 / 层高 / 平面图号 / 层名，画成表并成为后续立、剖面的数据源。

    floors 每项 {no, height, plan, name, elev?}；elev 省略时按层高自下而上累加（首层 ±0.000）。
    表本身还是 draw_table 画的，只是把 AA_TYPE 改写成 FLOOR_TABLE，并回读校验层数/总高。
    """
    sc = float(scale) if scale else drawing_scale(session)
    if not floors:
        raise CadError("楼层表至少要有一层")
    norm: list[dict[str, Any]] = []
    elev = 0.0
    for i, f in enumerate(floors):
        no = str(f.get("no") or (i + 1)).strip()
        try:
            h = float(f.get("height") or 0)
        except (TypeError, ValueError):
            raise CadError("第 %d 层层高不是数字：%r" % (i + 1, f.get("height")))
        if h <= 0:
            raise CadError("第 %d 层层高必须大于 0（当前 %s）" % (i + 1, h))
        if f.get("elev") in (None, ""):
            e = elev
        else:
            try:
                e = float(f["elev"])
            except (TypeError, ValueError):
                raise CadError("第 %d 层标高不是数字：%r" % (i + 1, f["elev"]))
        if i and e <= norm[-1]["elev"] + 1e-6:
            raise CadError("第 %d 层标高 %s 没有高于下一层 %s，请按自下而上排序"
                           % (i + 1, format_elevation(e / 1000.0),
                              format_elevation(norm[-1]["elev"] / 1000.0)))
        if i and e < norm[-1]["elev"] + norm[-1]["height"] - 1e-6:
            raise CadError("第 %d 层标高 %s 低于下一层顶 %s，层高与标高对不上"
                           % (i + 1, format_elevation(e / 1000.0),
                              format_elevation((norm[-1]["elev"] + norm[-1]["height"]) / 1000.0)))
        norm.append({"no": no, "elev": e, "height": h,
                     "plan": str(f.get("plan") or "").strip(),
                     "name": str(f.get("name") or "").strip()})
        elev = e + h

    rows = [[f["no"], format_elevation(f["elev"] / 1000.0), "%.0f" % f["height"],
             f["plan"], f["name"]] for f in norm]
    if widths is None:
        widths = [16.0, 26.0, 20.0, 32.0, 26.0]
    res = draw_table(session, at, title, FLOOR_HEADER, rows,
                     [w * sc for w in widths], table_id=table_id, scale=sc)
    session.run([("attedit", {"handle": res["handle"],
                              "values": {"AA_TYPE": "FLOOR_TABLE"}})], save=True)
    attrs = session.attributes(res["block"])
    if attrs.get("AA_TYPE") != "FLOOR_TABLE":
        raise CadError("楼层表 AA_TYPE 回写失败：%s" % attrs.get("AA_TYPE"))
    return {"ok": True, "block": res["block"], "id": table_id, "handle": res["handle"],
            "at": res["at"], "width": res["width"], "height": res["height"],
            "count": len(norm), "floors": norm,
            "total_height": round(elev, 4),
            "top_elev": round(norm[-1]["elev"], 4)}


OPENING_HEADER = ["序号", "门窗编号", "类别", "洞口尺寸(宽×高)", "窗台高", "樘数", "所在层"]


def _levels_text(levels: Sequence[int]) -> str:
    """把 {1,2,3} 压成 "1-3"，不连续写成 "1,3"。"""
    ls = sorted(set(int(x) for x in levels))
    if not ls:
        return ""
    if ls == list(range(ls[0], ls[-1] + 1)):
        return str(ls[0]) if len(ls) == 1 else "%d-%d" % (ls[0], ls[-1])
    return ",".join(str(x) for x in ls)


def opening_summary(session: Session) -> list[dict[str, Any]]:
    """按"编号 + 类别 + 宽高 + 窗台高"归并门窗洞口，给出樘数与所在层。"""
    groups: dict[tuple, dict[str, Any]] = {}
    for o in opening_data(session):
        key = (str(o["no"] or "").strip(), str(o["kind"]).upper(),
               round(o["width"], 1), round(o["height"], 1), round(o["sill"], 1))
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"no": key[0], "kind": key[1], "width": key[2],
                               "height": key[3], "sill": key[4], "count": 0, "levels": []}
        g["count"] += 1
        g["levels"].append(o.get("floor", 1))
    out = []
    for g in groups.values():
        if not g["no"]:
            # 没注编号的洞口：按规范术语补一个 A- 前缀占位，别留空白
            g["no"] = "--"
        g["levels"] = sorted(set(int(x) for x in g["levels"]))
        g["level_text"] = _levels_text(g["levels"])
        out.append(g)
    # 门在前、窗在后，同类别按编号排
    out.sort(key=lambda x: (0 if x["kind"] == "DOOR" else 1, x["no"], x["sill"]))
    return out


def create_opening_table(
    session: Session,
    table_id: str,
    at: tuple[float, float],
    title: str = "门窗表",
    scale: float | None = None,
    widths: list[float] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """门窗表：从平面上的 `AA_OPENING` 自动统计，按编号归并成表（v1.0.32）。

    统计口径：编号 + 类别 + 洞口宽高 + 窗台高 完全相同的归一行；
    樘数是图上实际数量，所在层取洞口所在墙的 `AA_FLOOR`（同一编号跨层则写 "1-3"）。
    没有洞口时不画空表，直接报错——空表在图纸上比没表更容易被误读。
    """
    sc = float(scale) if scale else drawing_scale(session)
    items = opening_summary(session)
    if not items:
        raise CadError("图上一个门窗洞口都没有（AA_OPENING），不生成空的门窗表")
    rows = []
    for i, it in enumerate(items, 1):
        rows.append([
            str(i), it["no"],
            "门" if it["kind"] == "DOOR" else ("窗" if it["kind"] == "WINDOW" else "门连窗"),
            "%d×%d" % (round(it["width"]), round(it["height"])),
            "%d" % round(it["sill"]) if it["kind"] != "DOOR" else "-",
            str(it["count"]), it["level_text"],
        ])
    if widths is None:
        widths = [10.0, 22.0, 12.0, 30.0, 16.0, 12.0, 22.0]
    res = draw_table(session, at, title, OPENING_HEADER, rows,
                     [w * sc for w in widths], table_id=table_id, scale=sc)
    session.run([("attedit", {"handle": res["handle"],
                              "values": {"AA_TYPE": "OPENING_TABLE"}})], save=True)
    attrs = session.attributes(res["block"])
    if attrs.get("AA_TYPE") != "OPENING_TABLE":
        raise CadError("门窗表 AA_TYPE 回写失败：%s" % attrs.get("AA_TYPE"))
    if note:
        hgt = 2.5 * sc
        nx, ny = res["at"][0], res["at"][1] - res["height"] - 6.0 * sc
        session.lisp(
            '(progn (aa:mktext-r (list %.3f %.3f) "%s" "AA-TABLE" %.3f 0.0) (princ "ok"))'
            % (nx, ny, note.replace('"', "'"), hgt),
            libraries=("aa_core.lisp",),
        )
    return {"ok": True, "block": res["block"], "id": table_id, "handle": res["handle"],
            "at": res["at"], "width": res["width"], "height": res["height"],
            "count": len(rows), "total": sum(it["count"] for it in items),
            "items": items, "note": note}


def read_opening_table(session: Session, table_id: str) -> list[dict[str, Any]]:
    """回读门窗表（表体数据），给出编号、类别、宽高、窗台高、樘数、所在层。"""
    attrs = session.attributes("AA_TABLE_" + table_id)
    if not attrs or attrs.get("AA_TYPE") != "OPENING_TABLE":
        raise CadError("没找到门窗表 %s" % table_id)
    out: list[dict[str, Any]] = []
    for r in attrs.get("AA_ROWS", "").split("@@"):
        if not r:
            continue
        c = r.split("~") + [""] * 7
        size = c[3].split("×")
        if len(size) != 2:
            raise CadError("门窗表的洞口尺寸解析不了：%r" % c[3])
        out.append({
            "no": c[1], "kind": c[2],
            "width": float(size[0]), "height": float(size[1]),
            "sill": 0.0 if c[4] in ("-", "") else float(c[4]),
            "count": int(float(c[5] or 0)),
            "levels": [int(x) for x in
                       (c[6].replace("-", ",").split(",") if c[6] else [])],
            "level_text": c[6],
        })
    return out


def read_floors(session: Session, table_id: str) -> list[dict[str, Any]]:
    """回读楼层表（从表体数据反解），给出立面/剖面要用的层号、标高、层高、图号。"""
    attrs = session.attributes("AA_TABLE_" + table_id)
    if not attrs or attrs.get("AA_TYPE") != "FLOOR_TABLE":
        raise CadError("没找到楼层表 %s" % table_id)
    rows = [r.split("~") for r in attrs.get("AA_ROWS", "").split("@@") if r]
    out: list[dict[str, Any]] = []
    for r in rows:
        cells = r + [""] * (5 - len(r))
        text = cells[1].replace("±", "")
        try:
            elev = float(text) * 1000.0
        except ValueError:
            raise CadError("楼层表里标高解析不了：%r" % cells[1])
        out.append({"no": cells[0], "elev": elev, "height": float(cells[2]),
                    "plan": cells[3], "name": cells[4]})
    return out


def openings_report(session: Session, csv_path: str | Path | None = None,
                    table_at: tuple[float, float] | None = None,
                    title: str = "门窗表") -> dict[str, Any]:
    """门窗表：同编号同尺寸合并计数，列出洞口宽高与所在墙，可导出 CSV / 图上表格。"""
    kinds = {"DOOR": "门", "WINDOW": "窗", "DOORWIN": "门连窗"}
    groups: dict[str, dict[str, Any]] = {}
    for o in sorted(opening_data(session), key=lambda x: (x["no"], x["id"])):
        no = o["no"] or opening_no(o["kind"], o["width"], o["height"])
        g = groups.setdefault(no, {
            "编号": no,
            "类型": kinds.get(o["kind"], o["kind"]),
            "宽(mm)": "%.0f" % o["width"],
            "高(mm)": "%.0f" % o["height"],
            "樘数": 0,
            "_walls": [],
        })
        g["樘数"] += 1
        if o["wallid"]:
            g["_walls"].append(o["wallid"])

    rows = []
    for no in sorted(groups):
        g = groups[no]
        rows.append({
            "编号": g["编号"],
            "类型": g["类型"],
            "宽(mm)": g["宽(mm)"],
            "高(mm)": g["高(mm)"],
            "樘数": g["樘数"],
            "所在墙": ";".join(sorted(set(g["_walls"]))),
        })

    out: dict[str, Any] = {
        "marks": len(rows),
        "openings": sum(r["樘数"] for r in rows),
        "rows": rows,
    }

    if csv_path:
        p = Path(csv_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        cols = ["编号", "类型", "宽(mm)", "高(mm)", "樘数", "所在墙"]
        lines = [",".join(cols)]
        for row in rows:
            lines.append(",".join(str(row[c]) for c in cols))
        lines.append(",".join(["合计", "%d 种" % len(rows), "", "",
                               "%d 樘" % out["openings"], ""]))
        p.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")  # BOM：Excel 双击不乱码
        out["csv"] = str(p)

    if table_at:
        body = [[r["编号"], r["类型"], r["宽(mm)"], r["高(mm)"],
                 str(r["樘数"]), r["所在墙"]] for r in rows]
        body.append(["合计", "%d 种" % len(rows), "", "",
                     "%d 樘" % out["openings"], ""])
        out["table"] = draw_table(
            session, table_at, title,
            header=["编号", "类型", "宽(mm)", "高(mm)", "樘数", "所在墙"],
            body=body,
            widths=[1800.0, 1600.0, 1900.0, 1700.0, 1300.0, 2900.0],
        )
    return out


def rooms_report(session: Session, csv_path: str | Path | None = None,
                 table_at: tuple[float, float] | None = None,
                 title: str = "房间面积表") -> dict[str, Any]:
    """房间汇总：按编号列出面积/周长/墙环，可导出 CSV，也可在图上插入表格。"""
    rows = []
    for r in sorted(room_data(session), key=lambda x: x["id"]):
        rows.append({
            "房间编号": r["id"],
            "房间名称": r["name"],
            "净面积(mm2)": "%.2f" % r["area"],
            "净面积(m2)": "%.2f" % (r["area"] / 1e6),
            "周长(mm)": "%.2f" % r["perimeter"],
            "围合墙": ";".join(r["walls"]),
        })
    total = sum(r["area"] for r in room_data(session))

    out: dict[str, Any] = {
        "rooms": len(rows),
        "total_area_m2": round(total / 1e6, 2),
        "rows": rows,
    }

    if csv_path:
        p = Path(csv_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        cols = ["房间编号", "房间名称", "净面积(mm2)", "净面积(m2)", "周长(mm)", "围合墙"]
        lines = [",".join(cols)]
        for row in rows:
            lines.append(",".join(row[c] for c in cols))
        mean = "%.2f" % (total / len(rows) / 1e6) if rows else "0.00"
        lines.append(",".join(["合计", "%d 间" % len(rows), "%.2f" % total,
                               "%.2f" % (total / 1e6), "", ""]))
        p.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")  # BOM：Excel 双击不乱码
        out["csv"] = str(p)
        out["mean_area_m2"] = float(mean)

    if table_at:
        grid = [["%s" % title, "", "", ""],
                ["编号", "名称", "净面积(m²)", "周长(mm)"]]
        for row in rows:
            grid.append([row["房间编号"], row["房间名称"], row["净面积(m2)"], row["周长(mm)"]])
        grid.append(["合计", "%d 间" % len(rows),
                     "%.2f" % (total / 1e6) if rows else "0.00", ""])
        out["table"] = draw_table(
            session, table_at, title,
            header=["编号", "名称", "净面积(m²)", "周长(mm)"],
            body=grid[2:],
            widths=[1600.0, 2600.0, 2600.0, 2300.0],
        )
    return out


# ---------------- 详图：详图符号 + 门窗大样（v1.0.35，B7 第四项） ----------------

def create_detail_mark(
    session: Session,
    mark_id: str,
    at: tuple[float, float],
    detail: str,
    sheetno: str = "—",
    scale: float | None = None,
) -> dict[str, Any]:
    """详图符号（GB/T 50001）：直径 14mm 粗圆 + 水平直径线，上半详图编号、下半图纸号。

    与索引符号的区别只在直径（索引 10mm、详图 14mm）与 `AA_KIND`，图面画法一致；
    同一张图上的详图，图纸号写 "—"。
    """
    block = "AA_SYM_" + mark_id
    if session.block_exists(block):
        raise CadError("符号 %s 已存在，请换编号" % mark_id)
    det = str(detail).strip()
    if not det:
        raise CadError("详图符号必须给详图编号")
    sc = float(scale) if scale else drawing_scale(session)
    d = annot_size(14.0, sc)
    session.ensure_layers([LAYERS["name"]])
    before = session.snapshot()
    session.lisp(
        '(aa:idx %.3f %.3f %.4f "%s" "%s" %.4f)'
        % (float(at[0]), float(at[1]), d,
           det.replace('"', "'"), str(sheetno).replace('"', "'"),
           annot_size(4.0, sc)),
        libraries=("aa_core.lisp", "aa_symbol.lisp"),
    )
    handles = session.new_handles(before)
    if not handles:
        raise CadError("详图符号没有生成任何图元")
    att_defs = [
        ("AA_TYPE", "component type", "SYMBOL"),
        ("AA_ID", "component id", mark_id),
        ("AA_KIND", "symbol kind", "DETAIL_MARK"),
        ("AA_DETAIL", "detail no", det),
        ("AA_SHEETNO", "sheet no", str(sheetno)),
        ("AA_DIAM", "circle diameter", "%.4f" % d),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=LAYERS["name"])
    session.expect_attributes(block, {"AA_TYPE": "SYMBOL", "AA_KIND": "DETAIL_MARK",
                                      "AA_DETAIL": det})
    return {"block": block, "handle": handle, "kind": "DETAIL_MARK",
            "detail": det, "sheetno": str(sheetno), "diameter": d,
            "geom_handles": handles}


def read_detail_mark(session: Session, mark_id: str) -> dict[str, Any]:
    """回读详图符号：详图编号 / 图纸号 / 圆直径。"""
    attrs = session.attributes("AA_SYM_" + mark_id)
    if not attrs or attrs.get("AA_KIND") != "DETAIL_MARK":
        raise CadError("没找到详图符号 %s" % mark_id)
    return {"id": mark_id, "detail": attrs.get("AA_DETAIL", ""),
            "sheetno": attrs.get("AA_SHEETNO", "—"),
            "diameter": float(attrs.get("AA_DIAM") or 0)}


def create_opening_detail(
    session: Session,
    detail_id: str,
    at: tuple[float, float],
    opening_id: str | None = None,
    no: str | None = None,
    ratio: float = 20.0,
    factor: float | None = None,
    wall_depth: float = 240.0,
    title: str | None = None,
    dims: bool = True,
    scale: float | None = None,
) -> dict[str, Any]:
    """门窗大样：从图上已有洞口读尺寸，按 `ratio`（默认 1:20）放大重画一幅大样。

    `at` = 洞口**左下角**（窗台面/门槛）。`opening_id` 指定具体一樘；也可用 `no` 指定编号，
    但同编号多樘时拒绝（必须指明是哪一樘）。`factor` 给定时直接用它（= 出图比例/详图比例）。

    画法（GB/T 50104 门窗大样习惯）：洞口轮廓 + 两侧墙垛断面 + 窗框/门框 + 中梃/亮子/双扇，
    窗再加窗台板；尺寸只注洞口宽、高（窗台高注在立面/墙身节点，这里只存属性）。
    大样图名与比例（"1:20"）一并画在块内，整块落 `AA_OD_<编号>`，属性回读源洞口与放大倍数。

    **为什么放大**：我们只有模型空间一个比例（1:100 出图），1:20 的详图必须把几何放大 5 倍
    来画，注字仍按 1:100 的纸面字高（2.5mm），所以几何乘 `factor`、文字与尺寸偏移不乘。
    """
    block = "AA_OD_" + detail_id
    if session.block_exists(block):
        raise CadError("大样 %s 已存在，请换编号" % detail_id)
    ratio = float(ratio)
    if ratio <= 0:
        raise CadError("详图比例必须大于 0（收到 %s）" % ratio)
    sc = float(scale) if scale else drawing_scale(session)
    f = float(factor) if factor is not None else sc / ratio
    if f <= 0:
        raise CadError("大样放大倍数必须大于 0（收到 %s）" % f)
    wall_depth = float(wall_depth)
    if wall_depth <= 0:
        raise CadError("墙垛厚度必须大于 0（收到 %s）" % wall_depth)

    ops = opening_data(session)
    if not ops:
        raise CadError("图上没有门窗洞口，无法生成大样")
    if opening_id:
        hit = [o for o in ops if o["id"] == str(opening_id)]
        if not hit:
            raise CadError("图上没有洞口 %s" % opening_id)
    elif no:
        hit = [o for o in ops if o["no"] == str(no)]
        if not hit:
            raise CadError("图上没有编号为 %s 的门窗" % no)
        if len(hit) > 1:
            raise CadError("编号 %s 在图上有多樘（%d），大样请用具体洞口编号" % (no, len(hit)))
    else:
        raise CadError("大样必须指定洞口编号或门窗编号")
    o = hit[0]
    w, hh = float(o["width"]), float(o["height"])
    if w <= 0 or hh <= 0:
        raise CadError("洞口 %s 的宽高不合法（%s×%s）" % (o["id"], w, hh))
    kind = "WINDOW" if str(o["kind"]).upper().startswith("WIN") else "DOOR"
    ref = o["no"] or o["id"]
    if not title:
        title = "%s %s大样" % (ref, "窗" if kind == "WINDOW" else "门")

    ann = lambda mm: annot_size(mm, sc)  # noqa: E731
    W, H = w * f, hh * f
    WD = wall_depth * f
    fr = 60.0 * f            # 门窗框厚 60
    mull = 60.0 * f          # 中梃宽 60
    sfl = 40.0 * f           # 扇框内缩 40
    wext = 300.0 * f         # 墙垛上下各多画 300

    lay_wall = LAYERS["wall"]
    lay_open = LAYERS["opening"]
    lay_dim = LAYERS["dim"]
    lay_name = LAYERS["name"]
    session.ensure_layers([lay_wall, lay_open, lay_dim, lay_name])

    body: list[str] = []

    def seg(x1: float, y1: float, x2: float, y2: float, lay: str) -> None:
        body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                    % (x1, y1, x2, y2, lay))

    def txt(x: float, y: float, s: str, hgt: float, ang: float = 0.0) -> None:
        if not s:
            return
        body.append('(aa:mktext-r (list %.3f %.3f) "%s" "%s" %.3f %.4f)'
                    % (x, y, str(s).replace('"', "'"), lay_name, hgt, ang))

    def rect(x1: float, y1: float, x2: float, y2: float, lay: str) -> None:
        seg(x1, y1, x2, y1, lay)
        seg(x2, y1, x2, y2, lay)
        seg(x2, y2, x1, y2, lay)
        seg(x1, y2, x1, y1, lay)

    # 洞口 + 两侧墙垛断面
    rect(0.0, 0.0, W, H, lay_open)
    for xs in (0.0, W):
        d = -1.0 if xs == 0.0 else 1.0
        seg(xs, -wext, xs + d * WD, -wext, lay_wall)
        seg(xs, H + wext, xs + d * WD, H + wext, lay_wall)
        seg(xs + d * WD, -wext, xs + d * WD, H + wext, lay_wall)

    # 框
    rect(fr, fr, W - fr, H - fr, lay_open)

    xspans = [fr, W - fr]
    yspans = [fr, H - fr]
    if kind == "WINDOW":
        if w >= 1200.0:
            xspans = [fr, W / 2.0 - mull / 2.0, W / 2.0 + mull / 2.0, W - fr]
        if hh >= 1800.0:
            ty = H - fr - 600.0 * f
            yspans = [fr, ty - mull / 2.0, ty + mull / 2.0, H - fr]
    else:
        if w >= 900.0:
            seg(W / 2.0 - 20.0 * f, fr, W / 2.0 - 20.0 * f, H - fr, lay_open)
            seg(W / 2.0 + 20.0 * f, fr, W / 2.0 + 20.0 * f, H - fr, lay_open)
            xspans = [fr, W / 2.0 - 20.0 * f, W / 2.0 + 20.0 * f, W - fr]
    # 中梃/亮子的分隔实体（画成两条线之间的窄条）
    if len(xspans) == 4:
        seg(xspans[1], fr, xspans[1], H - fr, lay_open)
        seg(xspans[2], fr, xspans[2], H - fr, lay_open)
    if len(yspans) == 4:
        seg(fr, yspans[1], W - fr, yspans[1], lay_open)
        seg(fr, yspans[2], W - fr, yspans[2], lay_open)

    # 每个玻璃格再内缩 40 画扇框
    for i in range(len(xspans) - 1):
        for j in range(len(yspans) - 1):
            x1, x2 = xspans[i] + sfl, xspans[i + 1] - sfl
            y1, y2 = yspans[j] + sfl, yspans[j + 1] - sfl
            if x2 - x1 > 100.0 * f and y2 - y1 > 100.0 * f:
                rect(x1, y1, x2, y2, lay_open)

    # 窗台板（挑出 60、厚 100，只做窗）
    if kind == "WINDOW":
        seg(-60.0 * f, 0.0, W + 60.0 * f, 0.0, lay_wall)
        seg(-60.0 * f, -100.0 * f, W + 60.0 * f, -100.0 * f, lay_wall)
        seg(-60.0 * f, 0.0, -60.0 * f, -100.0 * f, lay_wall)
        seg(W + 60.0 * f, 0.0, W + 60.0 * f, -100.0 * f, lay_wall)

    ndim = 0
    if dims:
        th = ann(2.5)
        tick = ann(2.0)
        # 洞口宽：下方一道
        dy = -100.0 * f - ann(10.0) if kind == "WINDOW" else -ann(10.0)
        for xx in (0.0, W):
            seg(xx, 0.0, xx, dy - ann(2.0), lay_dim)
        seg(0.0, dy, W, dy, lay_dim)
        for xx in (0.0, W):
            seg(xx - tick, dy + tick, xx + tick, dy - tick, lay_dim)
        label = "%g" % w
        txt(W / 2.0 - _text_w(label, th) / 2.0, dy + ann(1.2), label, th)
        ndim += 1
        # 洞口高：左侧一道
        dx = -WD - ann(10.0)
        for yy in (0.0, H):
            seg(0.0, yy, dx - ann(2.0), yy, lay_dim)
        seg(dx, 0.0, dx, H, lay_dim)
        for yy in (0.0, H):
            seg(dx - tick, yy + tick, dx + tick, yy - tick, lay_dim)
        label = "%g" % hh
        txt(dx - ann(1.2) - th, H / 2.0 - _text_w(label, th) / 2.0, label, th, 1.5708)
        ndim += 1

    # 图名 + 比例，放在尺寸线以下
    ty = dy - ann(10.0)
    body.append('(aa:title %.3f %.3f "%s" "1:%g")'
                % (0.0, ty, title.replace('"', "'"), ratio))

    before = session.snapshot()
    session.lisp("(progn %s (princ \"ok\"))" % " ".join(body),
                 libraries=("aa_core.lisp", "aa_symbol.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("门窗大样没有生成任何图元")

    bbox = [-WD - ann(12.0), ty - ann(5.0), W + WD, H + wext]
    att_defs = [
        ("AA_TYPE", "component type", "OPENING_DETAIL"),
        ("AA_ID", "component id", detail_id),
        ("AA_REF", "source opening", o["id"]),
        ("AA_NO", "opening no", ref),
        ("AA_KIND", "opening kind", kind),
        ("AA_W", "opening width", "%.4f" % w),
        ("AA_H", "opening height", "%.4f" % hh),
        ("AA_SILL", "sill height", "%.4f" % float(o["sill"])),
        ("AA_FACTOR", "enlarge factor", "%.4f" % f),
        ("AA_RATIO", "detail ratio", "1:%g" % ratio),
        ("AA_TITLE", "detail title", title),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, tuple(at), att_vals, layer=lay_name)
    session.expect_attributes(block, {"AA_TYPE": "OPENING_DETAIL", "AA_ID": detail_id,
                                      "AA_REF": o["id"]})
    return {"block": block, "handle": handle, "id": detail_id, "ref": o["id"],
            "no": ref, "kind": kind, "width": w, "height": hh,
            "sill": float(o["sill"]), "factor": f, "ratio": "1:%g" % ratio,
            "title": title, "dims": ndim, "bbox": bbox, "geom_handles": handles}


def read_opening_detail(session: Session, detail_id: str) -> dict[str, Any]:
    """回读门窗大样：源洞口、宽高窗台高、放大倍数、详图比例、图名。"""
    attrs = session.attributes("AA_OD_" + detail_id)
    if not attrs or attrs.get("AA_TYPE") != "OPENING_DETAIL":
        raise CadError("没找到门窗大样 %s" % detail_id)
    return {"id": detail_id, "ref": attrs.get("AA_REF", ""),
            "no": attrs.get("AA_NO", ""), "kind": attrs.get("AA_KIND", ""),
            "width": float(attrs.get("AA_W") or 0),
            "height": float(attrs.get("AA_H") or 0),
            "sill": float(attrs.get("AA_SILL") or 0),
            "factor": float(attrs.get("AA_FACTOR") or 0),
            "ratio": attrs.get("AA_RATIO", ""),
            "title": attrs.get("AA_TITLE", "")}




# ---------------- 详图：墙身节点（v1.0.36，B7 第四项续） ----------------

WALL_NODE_KINDS = ("SILL", "PARAPET")


def create_wall_node(
    session: Session,
    node_id: str,
    at: tuple[float, float],
    kind: str = "SILL",
    wall_thick: float = 240.0,
    slab: float = 120.0,
    sill: float = 900.0,
    parapet: float = 1200.0,
    cap: float = 60.0,
    cap_out: float = 60.0,
    ratio: float = 20.0,
    factor: float | None = None,
    title: str | None = None,
    dims: bool = True,
    scale: float | None = None,
) -> dict[str, Any]:
    """墙身节点（垂直剖面，1:20）：SILL = 窗台节点，PARAPET = 女儿墙节点。

    `at` = **墙外皮**与**室内楼面**的交点；x 正向指向室内（右侧），室外在左。
    与门窗大样同一套放大口径：几何乘 `factor = 出图比例/详图比例`，注字与尺寸偏移不乘。

    SILL 画：墙身（外皮/内皮两道）+ 室内楼板（厚 `slab`）+ 窗台板（挑出 `cap_out`、厚 100）+
    窗框（60，切到窗台上 600）+ 尺寸（墙厚、窗台高）。
    PARAPET 画：墙身 + 屋面板 + 女儿墙压顶（厚 `cap`、两侧各挑 `cap_out`）+ 尺寸（墙厚、女儿墙高）。

    只画结构轮廓与定位尺寸，**不做保温/防水/抹灰等材料分层**（没有 HATCH，分层没法填充；
    真要做只能画线，图面反而糊）。
    """
    block = "AA_WN_" + node_id
    if session.block_exists(block):
        raise CadError("墙身节点 %s 已存在，请换编号" % node_id)
    k = str(kind or "").upper()
    if k not in WALL_NODE_KINDS:
        raise CadError("墙身节点类型只能是 SILL / PARAPET（收到 %r）" % kind)
    ratio = float(ratio)
    if ratio <= 0:
        raise CadError("详图比例必须大于 0（收到 %s）" % ratio)
    sc = float(scale) if scale else drawing_scale(session)
    f = float(factor) if factor is not None else sc / ratio
    if f <= 0:
        raise CadError("大样放大倍数必须大于 0（收到 %s）" % f)
    wall_thick = float(wall_thick)
    slab = float(slab)
    cap = float(cap)
    cap_out = float(cap_out)
    if wall_thick <= 0:
        raise CadError("墙厚必须大于 0（收到 %s）" % wall_thick)
    if slab < 0 or cap < 0 or cap_out < 0:
        raise CadError("板厚/压顶厚度/挑出不能为负")
    if k == "SILL" and float(sill) <= 0:
        raise CadError("窗台高必须大于 0（收到 %s）" % sill)
    if k == "PARAPET" and float(parapet) <= 0:
        raise CadError("女儿墙高必须大于 0（收到 %s）" % parapet)

    ann = lambda mm: annot_size(mm, sc)  # noqa: E731
    T = wall_thick * f
    SB = slab * f
    CO = cap_out * f
    CP = cap * f
    S = float(sill) * f
    PH = float(parapet) * f

    lay_wall = LAYERS["wall"]
    lay_detail = LAYERS["elevdetail"]
    lay_dim = LAYERS["dim"]
    lay_name = LAYERS["name"]
    session.ensure_layers([lay_wall, lay_detail, lay_dim, lay_name])

    body: list[str] = []

    def seg(x1: float, y1: float, x2: float, y2: float, lay: str) -> None:
        body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                    % (x1, y1, x2, y2, lay))

    def txt(x: float, y: float, s: str, hgt: float, ang: float = 0.0) -> None:
        if not s:
            return
        body.append('(aa:mktext-r (list %.3f %.3f) "%s" "%s" %.3f %.4f)'
                    % (x, y, str(s).replace('"', "'"), lay_name, hgt, ang))

    def rect(x1: float, y1: float, x2: float, y2: float, lay: str) -> None:
        seg(x1, y1, x2, y1, lay)
        seg(x2, y1, x2, y2, lay)
        seg(x2, y2, x1, y2, lay)
        seg(x1, y2, x1, y1, lay)

    bottom = -(SB + 300.0 * f)
    if k == "SILL":
        top = S + 600.0 * f
        # 窗台以下：墙身实心
        seg(0.0, bottom, 0.0, S, lay_wall)
        seg(T, bottom, T, S, lay_wall)
        # 室内楼板（内皮往里 1500）
        seg(T, 0.0, T + 1500.0 * f, 0.0, lay_detail)
        seg(T, -SB, T + 1500.0 * f, -SB, lay_detail)
        seg(T + 1500.0 * f, 0.0, T + 1500.0 * f, -SB, lay_detail)
        seg(T, 0.0, T, -SB, lay_wall)
        # 窗台板（挑出 CO、厚 100）
        rect(-CO, S - 100.0 * f, T, S, lay_detail)
        # 窗台以上是洞口：只画窗框（60）+ 玻璃线，不再画墙
        seg(60.0 * f, S, 60.0 * f, top, lay_detail)
        seg(120.0 * f, S, 120.0 * f, top, lay_detail)
        seg(90.0 * f, S, 90.0 * f, top, lay_detail)
        feature_y = top
    else:
        top = PH + CP
        seg(0.0, bottom, 0.0, PH, lay_wall)
        seg(T, bottom, T, PH, lay_wall)
        # 屋面板（内皮往里 1500）
        seg(T, 0.0, T + 1500.0 * f, 0.0, lay_detail)
        seg(T, -SB, T + 1500.0 * f, -SB, lay_detail)
        seg(T + 1500.0 * f, 0.0, T + 1500.0 * f, -SB, lay_detail)
        seg(T, 0.0, T, -SB, lay_wall)
        # 压顶（两侧各挑 CO、厚 CP）
        rect(-CO, PH, T + CO, PH + CP, lay_detail)
        feature_y = top

    ndim = 0
    if dims:
        th = ann(2.5)
        tick = ann(2.0)
        # 墙厚：PARAPET 注在压顶之上；SILL 墙身止于窗台，注在墙底之下（避免压在窗框上）
        if k == "SILL":
            dy = bottom - ann(10.0)
            base_feat = bottom
            sgn = -1.0
            ty_txt = dy - ann(4.0)
        else:
            dy = feature_y + ann(10.0)
            base_feat = feature_y
            sgn = 1.0
            ty_txt = dy + ann(1.2)
        for xx in (0.0, T):
            seg(xx, base_feat, xx, dy + sgn * ann(2.0), lay_dim)
        seg(0.0, dy, T, dy, lay_dim)
        for xx in (0.0, T):
            seg(xx - tick, dy + tick, xx + tick, dy - tick, lay_dim)
        label = "%g" % wall_thick
        txt(T / 2.0 - _text_w(label, th) / 2.0, ty_txt, label, th)
        ndim += 1

        # 高度：外墙侧一道（SILL = 窗台高，PARAPET = 女儿墙高）
        hgt_val = float(sill) if k == "SILL" else float(parapet)
        dx = -CO - ann(10.0)
        for yy in (0.0, S if k == "SILL" else PH):
            seg(0.0, yy, dx - ann(2.0), yy, lay_dim)
        seg(dx, 0.0, dx, S if k == "SILL" else PH, lay_dim)
        for yy in (0.0, S if k == "SILL" else PH):
            seg(dx - tick, yy + tick, dx + tick, yy - tick, lay_dim)
        label = "%g" % hgt_val
        txt(dx - ann(1.2) - th, (S if k == "SILL" else PH) / 2.0 - _text_w(label, th) / 2.0,
            label, th, 1.5708)
        ndim += 1

    if not title:
        title = "窗台节点" if k == "SILL" else "女儿墙节点"
    ty = bottom - (ann(24.0) if k == "SILL" and dims else ann(12.0))
    body.append('(aa:title %.3f %.3f "%s" "1:%g")'
                % (0.0, ty, title.replace('"', "'"), ratio))

    before = session.snapshot()
    session.lisp("(progn %s (princ \"ok\"))" % " ".join(body),
                 libraries=("aa_core.lisp", "aa_symbol.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("墙身节点没有生成任何图元")

    bbox = [-CO - ann(26.0), ty - ann(6.0), T + 1500.0 * f, feature_y + ann(14.0)]
    att_defs = [
        ("AA_TYPE", "component type", "WALL_NODE"),
        ("AA_ID", "component id", node_id),
        ("AA_KIND", "node kind", k),
        ("AA_WALL", "wall thickness", "%.4f" % wall_thick),
        ("AA_SLAB", "slab thickness", "%.4f" % slab),
        ("AA_SILL", "sill height", "%.4f" % float(sill)),
        ("AA_PARAPET", "parapet height", "%.4f" % float(parapet)),
        ("AA_CAP", "cap thickness", "%.4f" % cap),
        ("AA_CAPOUT", "cap overhang", "%.4f" % cap_out),
        ("AA_FACTOR", "enlarge factor", "%.4f" % f),
        ("AA_RATIO", "detail ratio", "1:%g" % ratio),
        ("AA_TITLE", "detail title", title),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, tuple(at), att_vals, layer=lay_name)
    session.expect_attributes(block, {"AA_TYPE": "WALL_NODE", "AA_ID": node_id,
                                      "AA_KIND": k})
    return {"block": block, "handle": handle, "id": node_id, "kind": k,
            "wall": wall_thick, "slab": slab, "sill": float(sill),
            "parapet": float(parapet), "cap": cap, "cap_out": cap_out,
            "factor": f, "ratio": "1:%g" % ratio, "title": title,
            "dims": ndim, "bbox": bbox, "geom_handles": handles}


def read_wall_node(session: Session, node_id: str) -> dict[str, Any]:
    """回读墙身节点：类型、墙厚、窗台高/女儿墙高、压顶、放大倍数、图名。"""
    attrs = session.attributes("AA_WN_" + node_id)
    if not attrs or attrs.get("AA_TYPE") != "WALL_NODE":
        raise CadError("没找到墙身节点 %s" % node_id)
    return {"id": node_id, "kind": attrs.get("AA_KIND", ""),
            "wall": float(attrs.get("AA_WALL") or 0),
            "slab": float(attrs.get("AA_SLAB") or 0),
            "sill": float(attrs.get("AA_SILL") or 0),
            "parapet": float(attrs.get("AA_PARAPET") or 0),
            "cap": float(attrs.get("AA_CAP") or 0),
            "cap_out": float(attrs.get("AA_CAPOUT") or 0),
            "factor": float(attrs.get("AA_FACTOR") or 0),
            "ratio": attrs.get("AA_RATIO", ""),
            "title": attrs.get("AA_TITLE", "")}


# ---------------- 详图：楼梯间大样（v1.0.37，B7 第四项续） ----------------

def create_stair_detail(
    session: Session,
    detail_id: str,
    at: tuple[float, float],
    stair_id: str | None = None,
    ratio: float = 20.0,
    factor: float | None = None,
    title: str | None = None,
    dims: bool = True,
    scale: float | None = None,
) -> dict[str, Any]:
    """楼梯间大样（1:20）：从图上已有楼梯读参数，放大重画平面。

    `at` = 大样左下角（**上行方向朝上**，不再沿用平面里的旋转角；详图按正向摆放）。
    直跑 STRAIGHT 画：梯段轮廓 + 踏步线 + 梯段宽/踏步总长两道尺寸；
    双跑 DOGLEG 画：外轮廓 + 梯井 + 平台带 + 两跑踏步 + 箭头 + 梯段宽/踏步总长/平台深三道尺寸。
    尺寸文字写真实 mm（含 "10×280=2800" 这种踏步表达式），几何按 `factor = 出图比例/详图比例` 放大。
    """
    block = "AA_SD_" + detail_id
    if session.block_exists(block):
        raise CadError("楼梯大样 %s 已存在，请换编号" % detail_id)
    if not stair_id:
        raise CadError("楼梯大样必须给源楼梯编号")
    attrs = session.attributes("AA_STAIR_" + str(stair_id))
    if not attrs or attrs.get("AA_TYPE") != "STAIR":
        raise CadError("图上没有楼梯 %s" % stair_id)
    ratio = float(ratio)
    if ratio <= 0:
        raise CadError("详图比例必须大于 0（收到 %s）" % ratio)
    sc = float(scale) if scale else drawing_scale(session)
    f = float(factor) if factor is not None else sc / ratio
    if f <= 0:
        raise CadError("大样放大倍数必须大于 0（收到 %s）" % f)

    kind = (attrs.get("AA_KIND") or "STRAIGHT").upper()
    W = float(attrs.get("AA_W") or 0)
    steps = int(float(attrs.get("AA_STEPS") or 0))
    tread = float(attrs.get("AA_TREAD") or 0)
    well = float(attrs.get("AA_WELL") or 0)
    landing = float(attrs.get("AA_LANDING") or 0)
    level = (attrs.get("AA_LEVEL") or "MIDDLE").upper()
    if W <= 0 or steps < 2 or tread <= 0:
        raise CadError("楼梯 %s 的梯段宽/踏步数/踏步宽不合法" % stair_id)
    run = steps * tread
    if kind == "DOGLEG":
        if well < 0 or landing <= 0:
            raise CadError("双跑楼梯 %s 的梯井/平台深不合法" % stair_id)
        total_w = 2.0 * W + well
        depth = run + landing
    else:
        total_w = W
        depth = run

    ann = lambda mm: annot_size(mm, sc)  # noqa: E731
    Wf, WF = W * f, total_w * f
    RUNF, DEPF = run * f, (landing * f if kind == "DOGLEG" else 0.0)
    WELLF = well * f
    TRF = tread * f

    lay_stair = LAYERS["stair"]
    lay_arrow = LAYERS["stairarrow"]
    lay_dim = LAYERS["dim"]
    lay_name = LAYERS["name"]
    session.ensure_layers([lay_stair, lay_arrow, lay_dim, lay_name])

    body: list[str] = []

    def seg(x1: float, y1: float, x2: float, y2: float, lay: str) -> None:
        body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                    % (x1, y1, x2, y2, lay))

    def txt(x: float, y: float, s: str, hgt: float, ang: float = 0.0) -> None:
        if not s:
            return
        body.append('(aa:mktext-r (list %.3f %.3f) "%s" "%s" %.3f %.4f)'
                    % (x, y, str(s).replace('"', "'"), lay_name, hgt, ang))

    def rect(x1: float, y1: float, x2: float, y2: float, lay: str) -> None:
        seg(x1, y1, x2, y1, lay)
        seg(x2, y1, x2, y2, lay)
        seg(x2, y2, x1, y2, lay)
        seg(x1, y2, x1, y1, lay)

    if kind != "DOGLEG":
        rect(0.0, 0.0, Wf, RUNF, lay_stair)
        for k in range(1, steps):
            yy = k * TRF
            seg(0.0, yy, Wf, yy, lay_stair)
        ax = Wf / 2.0
        hl = ann(5.0)
        hw = ann(1.8)
        th = ann(4.0)
        if level == "TOP":
            # 顶层只有下行：箭头从头往下，字"下"放在箭头起点
            seg(ax, RUNF * 0.88, ax, RUNF * 0.12, lay_arrow)
            seg(ax, RUNF * 0.12, ax - hw, RUNF * 0.12 + hl, lay_arrow)
            seg(ax, RUNF * 0.12, ax + hw, RUNF * 0.12 + hl, lay_arrow)
            txt(ax - _text_w("下", th) / 2.0, RUNF * 0.9, "下", th)
        else:
            apex = RUNF * 0.85
            seg(ax, RUNF * 0.12, ax, apex, lay_arrow)
            seg(ax, apex, ax - hw, apex - hl, lay_arrow)
            seg(ax, apex, ax + hw, apex - hl, lay_arrow)
            txt(ax - _text_w("上", th) / 2.0, RUNF * 0.04, "上", th)
    else:
        # 左跑 + 梯井 + 右跑 + 平台带
        rect(0.0, 0.0, WF, DEPF + RUNF, lay_stair)
        seg(Wf, 0.0, Wf, RUNF, lay_stair)
        seg(Wf + WELLF, 0.0, Wf + WELLF, RUNF, lay_stair)
        seg(0.0, RUNF, Wf, RUNF, lay_stair)
        seg(Wf + WELLF, RUNF, WF, RUNF, lay_stair)
        seg(0.0, RUNF + DEPF, WF, RUNF + DEPF, lay_stair)
        for k in range(1, steps):
            yy = k * TRF
            seg(0.0, yy, Wf, yy, lay_stair)
            seg(Wf + WELLF, yy, WF, yy, lay_stair)
        hl = ann(5.0)
        hw = ann(1.8)
        th = ann(4.0)
        # 左跑上行
        ax = Wf / 2.0
        apex = RUNF * 0.45
        if level != "TOP":
            seg(ax, RUNF * 0.08, ax, apex, lay_arrow)
            seg(ax, apex, ax - hw, apex - hl, lay_arrow)
            seg(ax, apex, ax + hw, apex - hl, lay_arrow)
            txt(ax - _text_w("上", th) / 2.0, RUNF * 0.02, "上", th)
        # 右跑下行（中层及以下才有下行）
        bx = Wf + WELLF + Wf / 2.0
        if level != "FIRST":
            bot = RUNF * 0.15
            seg(bx, RUNF * 0.9, bx, bot, lay_arrow)
            seg(bx, bot, bx - hw, bot + hl, lay_arrow)
            seg(bx, bot, bx + hw, bot + hl, lay_arrow)
            txt(bx - _text_w("下", th) / 2.0, RUNF * 0.92, "下", th)

    ndim = 0
    if dims:
        th = ann(3.2)
        tick = ann(2.0)
        # 梯段宽：下方水平一道（x 0..Wf）
        dy = -ann(10.0)
        for xx in (0.0, Wf):
            seg(xx, 0.0, xx, dy - ann(2.0), lay_dim)
        seg(0.0, dy, Wf, dy, lay_dim)
        for xx in (0.0, Wf):
            seg(xx - tick, dy + tick, xx + tick, dy - tick, lay_dim)
        label = "%g" % W
        txt(Wf / 2.0 - _text_w(label, th) / 2.0, dy - ann(4.0), label, th)
        ndim += 1

        # 踏步总长：左侧竖向一道（y 0..RUNF），文字 步数×踏步宽=总长
        dx = -ann(10.0)
        for yy in (0.0, RUNF):
            seg(0.0, yy, dx - ann(2.0), yy, lay_dim)
        seg(dx, 0.0, dx, RUNF, lay_dim)
        for yy in (0.0, RUNF):
            seg(dx - tick, yy + tick, dx + tick, yy - tick, lay_dim)
        label = "%d×%g=%g" % (steps, tread, run)
        txt(dx - ann(1.2) - _text_w(label, th), RUNF / 2.0 - th / 2.0, label, th, 1.5708)
        ndim += 1

        if kind == "DOGLEG":
            # 平台深：右侧竖向一道（y RUNF..RUNF+DEPF）
            rx = WF + ann(10.0)
            for yy in (RUNF, RUNF + DEPF):
                seg(WF, yy, rx + ann(2.0), yy, lay_dim)
            seg(rx, RUNF, rx, RUNF + DEPF, lay_dim)
            for yy in (RUNF, RUNF + DEPF):
                seg(rx - tick, yy + tick, rx + tick, yy - tick, lay_dim)
            label = "%g" % landing
            txt(rx + ann(1.2), (RUNF + DEPF / 2.0) - th * 4.0, label, th, 1.5708)
            ndim += 1

    if not title:
        title = "楼梯间详图"
    ty = -ann(24.0) if dims else -ann(10.0)
    body.append('(aa:title %.3f %.3f "%s" "1:%g")'
                % (0.0, ty, title.replace('"', "'"), ratio))

    before = session.snapshot()
    session.lisp("(progn %s (princ \"ok\"))" % " ".join(body),
                 libraries=("aa_core.lisp", "aa_symbol.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("楼梯大样没有生成任何图元")

    bbox = [-ann(30.0), ty - ann(6.0), WF + ann(18.0), RUNF + DEPF + ann(16.0)]
    att_defs = [
        ("AA_TYPE", "component type", "STAIR_DETAIL"),
        ("AA_ID", "component id", detail_id),
        ("AA_REF", "source stair", str(stair_id)),
        ("AA_KIND", "stair kind", kind),
        ("AA_W", "flight width", "%.4f" % W),
        ("AA_STEPS", "steps per flight", str(steps)),
        ("AA_TREAD", "tread depth", "%.4f" % tread),
        ("AA_RUN", "run per flight", "%.4f" % run),
        ("AA_WELL", "well width", "%.4f" % well),
        ("AA_LANDING", "landing depth", "%.4f" % landing),
        ("AA_LEVEL", "floor level type", level),
        ("AA_FACTOR", "enlarge factor", "%.4f" % f),
        ("AA_RATIO", "detail ratio", "1:%g" % ratio),
        ("AA_TITLE", "detail title", title),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {t: v for t, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, tuple(at), att_vals, layer=lay_name)
    session.expect_attributes(block, {"AA_TYPE": "STAIR_DETAIL", "AA_ID": detail_id,
                                      "AA_REF": str(stair_id)})
    return {"block": block, "handle": handle, "id": detail_id, "ref": str(stair_id),
            "kind": kind, "width": W, "steps": steps, "tread": tread, "run": run,
            "well": well, "landing": landing, "level": level,
            "factor": f, "ratio": "1:%g" % ratio, "title": title,
            "dims": ndim, "bbox": bbox, "geom_handles": handles}


def read_stair_detail(session: Session, detail_id: str) -> dict[str, Any]:
    """回读楼梯大样：源楼梯、类型、梯段宽/踏步数/踏步宽/梯井/平台、倍数、比例、图名。"""
    attrs = session.attributes("AA_SD_" + detail_id)
    if not attrs or attrs.get("AA_TYPE") != "STAIR_DETAIL":
        raise CadError("没找到楼梯大样 %s" % detail_id)
    return {"id": detail_id, "ref": attrs.get("AA_REF", ""),
            "kind": attrs.get("AA_KIND", ""),
            "width": float(attrs.get("AA_W") or 0),
            "steps": int(float(attrs.get("AA_STEPS") or 0)),
            "tread": float(attrs.get("AA_TREAD") or 0),
            "run": float(attrs.get("AA_RUN") or 0),
            "well": float(attrs.get("AA_WELL") or 0),
            "landing": float(attrs.get("AA_LANDING") or 0),
            "level": attrs.get("AA_LEVEL", ""),
            "factor": float(attrs.get("AA_FACTOR") or 0),
            "ratio": attrs.get("AA_RATIO", ""),
            "title": attrs.get("AA_TITLE", "")}


# ---------------- 详图：卫生间大样（v1.0.38，B7 第四项续） ----------------

def create_wc_detail(
    session: Session,
    detail_id: str,
    at: tuple[float, float],
    width: float = 2400.0,
    depth: float = 1800.0,
    wall: float = 120.0,
    slope: float = 1.0,
    drain: tuple[float, float] | None = None,
    ratio: float = 20.0,
    factor: float | None = None,
    title: str | None = None,
    dims: bool = True,
    scale: float | None = None,
) -> dict[str, Any]:
    """卫生间大样（1:20）：净空 + 墙厚 + 坐便/台盆/地漏 + 排水坡 + 三道尺寸。

    `at` = 大样**内净空左下角**（墙身向四周各外扩 `wall`）。
    默认布置：坐便靠上墙（400×700，水槽 400×180）、台盆靠左墙（450×600）、
    地漏 100×100 在右下角内退 300；排水坡箭头从上墙中部指向地漏，坡度 `slope`%。
    洁具位置只按默认规则排，型号/间距不做猜测（属性里记尺寸，图上不注型号）。
    """
    block = "AA_WC_" + detail_id
    if session.block_exists(block):
        raise CadError("卫生间大样 %s 已存在，请换编号" % detail_id)
    w = float(width)
    h = float(depth)
    t = float(wall)
    if w <= 0 or h <= 0:
        raise CadError("卫生间净宽/净深必须大于 0")
    if t < 0:
        raise CadError("墙厚不能为负")
    ratio = float(ratio)
    if ratio <= 0:
        raise CadError("详图比例必须大于 0（收到 %s）" % ratio)
    sc = float(scale) if scale else drawing_scale(session)
    f = float(factor) if factor is not None else sc / ratio
    if f <= 0:
        raise CadError("大样放大倍数必须大于 0（收到 %s）" % f)
    if slope <= 0:
        raise CadError("排水坡度必须大于 0（收到 %s）" % slope)

    if drain is None:
        dx, dy = max(150.0, w - 300.0), 300.0
    else:
        dx, dy = float(drain[0]), float(drain[1])
    if not (0.0 <= dx <= w and 0.0 <= dy <= h):
        raise CadError("地漏 (%g,%g) 落在卫生间净空之外" % (dx, dy))

    ann = lambda mm: annot_size(mm, sc)  # noqa: E731
    Wf, Hf, TF = w * f, h * f, t * f
    DF = 100.0 * f

    lay_wall = LAYERS["wall"]
    lay_room = LAYERS["room"]
    lay_dim = LAYERS["dim"]
    lay_name = LAYERS["name"]
    session.ensure_layers([lay_wall, lay_room, lay_dim, lay_name])

    body: list[str] = []

    def seg(x1: float, y1: float, x2: float, y2: float, lay: str) -> None:
        body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                    % (x1, y1, x2, y2, lay))

    def txt(x: float, y: float, s: str, hgt: float, ang: float = 0.0) -> None:
        if not s:
            return
        body.append('(aa:mktext-r (list %.3f %.3f) "%s" "%s" %.3f %.4f)'
                    % (x, y, str(s).replace('"', "'"), lay_name, hgt, ang))

    def rect(x1: float, y1: float, x2: float, y2: float, lay: str) -> None:
        seg(x1, y1, x2, y1, lay)
        seg(x2, y1, x2, y2, lay)
        seg(x2, y2, x1, y2, lay)
        seg(x1, y2, x1, y1, lay)

    def box(x: float, y: float, r: float) -> None:
        body.append('(aa:mkcircle (list %.3f %.3f) %.3f "%s")'
                    % (x, y, r, lay_room))

    # 墙身（四周墙带）
    rect(-TF, -TF, Wf + TF, Hf + TF, lay_wall)
    rect(0.0, 0.0, Wf, Hf, lay_wall)

    # 坐便：靠上墙，水槽 + 椭圆坐圈（32 边近似）+ 内圈（坐面）
    tw, td = 400.0 * f, 700.0 * f
    tank = 180.0 * f
    cx = Wf / 2.0
    rect(cx - tw / 2.0, Hf - tank, cx + tw / 2.0, Hf, lay_room)
    bcx, bcy = cx, Hf - tank - 240.0 * f
    rx, ry = 180.0 * f, 240.0 * f

    def ellipse(ex: float, ey: float, erx: float, ery: float, segs: int) -> None:
        pts = []
        for k in range(segs):
            a = 2.0 * math.pi * k / segs
            pts.append((ex + erx * math.cos(a), ey + ery * math.sin(a)))
        for k in range(segs):
            x1, y1 = pts[k]
            x2, y2 = pts[(k + 1) % segs]
            seg(x1, y1, x2, y2, lay_room)

    ellipse(bcx, bcy, rx, ry, 32)
    ellipse(bcx, bcy, rx - 45.0 * f, ry - 55.0 * f, 32)
    # 坐圈与水箱之间的两条连接线（盖板铰点）
    for sgn in (-1.0, 1.0):
        seg(cx + sgn * 60.0 * f, Hf - tank, cx + sgn * 60.0 * f,
            Hf - tank - 20.0 * f, lay_room)

    # 台盆：靠左墙，450 深 × 600 宽；台面 + 椭圆盆 + 龙头
    by = (Hf - 600.0 * f) / 2.0
    rect(0.0, by, 450.0 * f, by + 600.0 * f, lay_room)
    ellipse(240.0 * f, by + 300.0 * f, 150.0 * f, 210.0 * f, 32)
    ellipse(240.0 * f, by + 300.0 * f, 130.0 * f, 185.0 * f, 32)
    box(50.0 * f, by + 300.0 * f, 35.0 * f)

    # 地漏：100×100 + 对角
    hd = DF / 2.0
    rect(dx * f - hd, dy * f - hd, dx * f + hd, dy * f + hd, lay_room)
    seg(dx * f - hd, dy * f - hd, dx * f + hd, dy * f + hd, lay_room)
    seg(dx * f - hd, dy * f + hd, dx * f + hd, dy * f - hd, lay_room)

    # 排水坡：从上墙中部指向地漏，箭头 + i=%
    sx, sy = Wf / 2.0, Hf - 900.0 * f
    ax, ay = dx * f, dy * f
    seg(sx, sy, ax, ay, lay_room)
    import math as _m
    ang = _m.atan2(ay - sy, ax - sx)
    hl = ann(6.0)
    hw = ann(2.0)
    seg(ax, ay, ax - hl * _m.cos(ang - 0.35), ay - hl * _m.sin(ang - 0.35), lay_room)
    seg(ax, ay, ax - hl * _m.cos(ang + 0.35), ay - hl * _m.sin(ang + 0.35), lay_room)
    label = "i=%g%%" % slope
    th = ann(2.0)
    txt((sx + ax) / 2.0 + ann(2.0), (sy + ay) / 2.0 - th, label, th)

    ndim = 0
    if dims:
        th = ann(2.5)
        tick = ann(2.0)
        # 开间：下方
        dy2 = -TF - ann(10.0)
        for xx in (0.0, Wf):
            seg(xx, -TF, xx, dy2 - ann(2.0), lay_dim)
        seg(0.0, dy2, Wf, dy2, lay_dim)
        for xx in (0.0, Wf):
            seg(xx - tick, dy2 + tick, xx + tick, dy2 - tick, lay_dim)
        label = "%g" % w
        txt(Wf / 2.0 - _text_w(label, th) / 2.0, dy2 - ann(4.0), label, th)
        ndim += 1

        # 进深：左侧
        dx2 = -TF - ann(10.0)
        for yy in (0.0, Hf):
            seg(-TF, yy, dx2 - ann(2.0), yy, lay_dim)
        seg(dx2, 0.0, dx2, Hf, lay_dim)
        for yy in (0.0, Hf):
            seg(dx2 - tick, yy + tick, dx2 + tick, yy - tick, lay_dim)
        label = "%g" % h
        txt(dx2 - ann(1.2) - th, Hf / 2.0 - _text_w(label, th) / 2.0, label, th, 1.5708)
        ndim += 1

        # 坐便中心距左墙：沿坐便中心线（室内），从内墙皮量到坐便中心
        yc = bcy
        seg(0.0, yc, cx, yc, lay_dim)
        for xx in (0.0, cx):
            seg(xx - tick, yc + tick, xx + tick, yc - tick, lay_dim)
        label = "%g" % (w / 2.0)
        txt(cx / 2.0 - _text_w(label, th) / 2.0, yc + ann(1.0), label, th)
        ndim += 1

    if not title:
        title = "卫生间大样"
    ty = -TF - ann(24.0) if dims else -TF - ann(10.0)
    body.append('(aa:title %.3f %.3f "%s" "1:%g")'
                % (0.0, ty, title.replace('"', "'"), ratio))

    before = session.snapshot()
    session.lisp("(progn %s (princ \"ok\"))" % " ".join(body),
                 libraries=("aa_core.lisp", "aa_symbol.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("卫生间大样没有生成任何图元")

    bbox = [-TF - ann(30.0), ty - ann(6.0), Wf + TF + ann(18.0), Hf + TF + ann(16.0)]
    att_defs = [
        ("AA_TYPE", "component type", "WC_DETAIL"),
        ("AA_ID", "component id", detail_id),
        ("AA_W", "clear width", "%.4f" % w),
        ("AA_H", "clear depth", "%.4f" % h),
        ("AA_WALL", "wall thickness", "%.4f" % t),
        ("AA_TOILET", "toilet footprint", "400x700"),
        ("AA_BASIN", "basin footprint", "450x600"),
        ("AA_DRAIN", "floor drain", "%.4f,%.4f" % (dx, dy)),
        ("AA_SLOPE", "slope percent", "%.4f" % slope),
        ("AA_FACTOR", "enlarge factor", "%.4f" % f),
        ("AA_RATIO", "detail ratio", "1:%g" % ratio),
        ("AA_TITLE", "detail title", title),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {k: v for k, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, tuple(at), att_vals, layer=lay_name)
    session.expect_attributes(block, {"AA_TYPE": "WC_DETAIL", "AA_ID": detail_id})
    return {"block": block, "handle": handle, "id": detail_id,
            "width": w, "depth": h, "wall": t, "drain": [dx, dy], "slope": slope,
            "factor": f, "ratio": "1:%g" % ratio, "title": title,
            "dims": ndim, "bbox": bbox, "geom_handles": handles}


def read_wc_detail(session: Session, detail_id: str) -> dict[str, Any]:
    """回读卫生间大样：净宽/净深/墙厚/洁具/地漏/坡度/倍数/比例/图名。"""
    attrs = session.attributes("AA_WC_" + detail_id)
    if not attrs or attrs.get("AA_TYPE") != "WC_DETAIL":
        raise CadError("没找到卫生间大样 %s" % detail_id)
    drain = (attrs.get("AA_DRAIN") or "0,0").split(",")
    return {"id": detail_id,
            "width": float(attrs.get("AA_W") or 0),
            "depth": float(attrs.get("AA_H") or 0),
            "wall": float(attrs.get("AA_WALL") or 0),
            "toilet": attrs.get("AA_TOILET", ""),
            "basin": attrs.get("AA_BASIN", ""),
            "drain": [float(drain[0]), float(drain[-1])],
            "slope": float(attrs.get("AA_SLOPE") or 0),
            "factor": float(attrs.get("AA_FACTOR") or 0),
            "ratio": attrs.get("AA_RATIO", ""),
            "title": attrs.get("AA_TITLE", "")}


# ---------------- 立面：阳台 / 雨篷（v1.0.39，B7 续） ----------------

def create_elev_balcony(
    session: Session,
    item_id: str,
    at: tuple[float, float],
    width: float,
    kind: str = "BALCONY",
    slab: float = 100.0,
    rail: float = 1000.0,
    depth: float = 1200.0,
    dims: bool = True,
    scale: float | None = None,
) -> dict[str, Any]:
    """立面上的阳台 / 雨篷（1:1 世界尺寸，落在已生成的立面上）。

    `at` = 挑板**板底**左端；BALCONY 画挑板 + 栏板（两侧竖线 + 压顶线），
    AWNING 画挑板 + 两端小牛腿（斜撑）。`depth`（挑出宽）在正立面看不见，只记属性。
    尺寸：阳台宽一道（下方）、栏板高一道（左侧）；雨篷只注宽。
    """
    block = "AA_EB_" + item_id
    if session.block_exists(block):
        raise CadError("阳台/雨篷 %s 已存在，请换编号" % item_id)
    kind = (kind or "BALCONY").upper()
    if kind not in ("BALCONY", "AWNING"):
        raise CadError("kind 只能是 BALCONY / AWNING（收到 %s）" % kind)
    w = float(width)
    t = float(slab)
    h = float(rail)
    d = float(depth)
    if w <= 0 or t <= 0:
        raise CadError("阳台宽/板厚必须大于 0")
    if kind == "BALCONY" and h <= 0:
        raise CadError("栏板高必须大于 0")
    if d <= 0:
        raise CadError("挑出宽必须大于 0")
    if kind == "AWNING" and h != 1000.0:
        pass  # 雨篷不用栏板高，保留参数不报错

    sc = float(scale) if scale else drawing_scale(session)
    ann = lambda mm: annot_size(mm, sc)  # noqa: E731
    lay = LAYERS["elevdetail"]
    lay_dim = LAYERS["dim"]
    lay_name = LAYERS["name"]
    session.ensure_layers([lay, lay_dim, lay_name])

    AX, AY = float(at[0]), float(at[1])
    # 几何直接按世界坐标画，块插入点用 (0,0)，避免块基点造成二次偏移
    X, Y = AX, AY
    body: list[str] = []

    def seg(x1: float, y1: float, x2: float, y2: float, layer: str) -> None:
        body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                    % (x1, y1, x2, y2, layer))

    def txt(x: float, y: float, s: str, hgt: float, ang: float = 0.0) -> None:
        body.append('(aa:mktext-r (list %.3f %.3f) "%s" "%s" %.3f %.4f)'
                    % (x, y, str(s).replace('"', "'"), lay_name, hgt, ang))

    def rect(x1: float, y1: float, x2: float, y2: float, layer: str) -> None:
        seg(x1, y1, x2, y1, layer)
        seg(x2, y1, x2, y2, layer)
        seg(x2, y2, x1, y2, layer)
        seg(x1, y2, x1, y1, layer)

    # 挑板
    rect(X, Y, X + w, Y + t, lay)
    if kind == "BALCONY":
        # 栏板：两侧竖线 + 压顶线（压顶按 60 厚示意）
        cap = min(60.0, h * 0.1)
        seg(X, Y + t, X, Y + t + h, lay)
        seg(X + w, Y + t, X + w, Y + t + h, lay)
        seg(X, Y + t + h, X + w, Y + t + h, lay)
        if cap > 0:
            seg(X, Y + t + h - cap, X + w, Y + t + h - cap, lay)
    else:
        # 雨篷：两端小牛腿（斜撑）
        b = min(300.0, w * 0.2)
        for bx in (X + b * 0.5, X + w - b * 0.5):
            seg(bx, Y, bx, Y - b, lay)
            seg(bx, Y - b, bx + b, Y, lay)

    ndim = 0
    if dims:
        th = ann(2.5)
        tick = ann(2.0)
        # 宽：阳台注在挑板下方；雨篷在门洞上方，注在板顶以上，避免压住门扇
        if kind == "AWNING":
            base = Y + t
            dy = base + ann(4.0)
            ty = dy + ann(1.2)
            sgn = 1.0
        else:
            base = Y
            dy = Y - ann(10.0)
            ty = dy - ann(4.0)
            sgn = -1.0
        for xx in (X, X + w):
            seg(xx, base, xx, dy + sgn * ann(2.0), lay_dim)
        seg(X, dy, X + w, dy, lay_dim)
        for xx in (X, X + w):
            seg(xx - tick, dy + tick, xx + tick, dy - tick, lay_dim)
        label = "%g" % w
        txt(X + w / 2.0 - _text_w(label, th) / 2.0, ty, label, th)
        ndim += 1
        if kind == "BALCONY":
            dx = X - ann(10.0)
            for yy in (Y + t, Y + t + h):
                seg(X, yy, dx - ann(2.0), yy, lay_dim)
            seg(dx, Y + t, dx, Y + t + h, lay_dim)
            for yy in (Y + t, Y + t + h):
                seg(dx - tick, yy + tick, dx + tick, yy - tick, lay_dim)
            label = "%g" % h
            txt(dx - ann(1.2) - th, Y + t + h / 2.0 - _text_w(label, th) / 2.0, label, th, 1.5708)
            ndim += 1

    before = session.snapshot()
    session.lisp("(progn %s (princ \"ok\"))" % " ".join(body),
                 libraries=("aa_core.lisp", "aa_symbol.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("阳台/雨篷没有生成任何图元")

    bbox = [AX - ann(26.0), AY - ann(36.0), AX + w + ann(10.0),
            AY + (t + h if kind == "BALCONY" else t) + ann(14.0)]
    att_defs = [
        ("AA_TYPE", "component type", "ELEV_BALCONY"),
        ("AA_ID", "component id", item_id),
        ("AA_KIND", "balcony or awning", kind),
        ("AA_W", "width", "%.4f" % w),
        ("AA_SLAB", "slab thickness", "%.4f" % t),
        ("AA_RAIL", "rail height", "%.4f" % h),
        ("AA_DEPTH", "projection depth", "%.4f" % d),
        ("AA_ATX", "anchor x", "%.4f" % AX),
        ("AA_ATY", "anchor y", "%.4f" % AY),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {k: v for k, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=lay)
    session.expect_attributes(block, {"AA_TYPE": "ELEV_BALCONY", "AA_ID": item_id})
    return {"block": block, "handle": handle, "id": item_id, "kind": kind,
            "width": w, "slab": t, "rail": h, "depth": d,
            "dims": ndim, "bbox": bbox, "geom_handles": handles}


def read_elev_balcony(session: Session, item_id: str) -> dict[str, Any]:
    """回读立面阳台/雨篷：类型、宽、板厚、栏板高、挑出宽。"""
    attrs = session.attributes("AA_EB_" + item_id)
    if not attrs or attrs.get("AA_TYPE") != "ELEV_BALCONY":
        raise CadError("没找到阳台/雨篷 %s" % item_id)
    return {"id": item_id, "kind": attrs.get("AA_KIND", ""),
            "width": float(attrs.get("AA_W") or 0),
            "slab": float(attrs.get("AA_SLAB") or 0),
            "rail": float(attrs.get("AA_RAIL") or 0),
            "depth": float(attrs.get("AA_DEPTH") or 0)}


# ---------------- 剖面：基础大放脚（v1.0.40，B7 续） ----------------

def create_foundation(
    session: Session,
    item_id: str,
    at: tuple[float, float],
    wall: float = 240.0,
    steps: int = 2,
    step_h: float = 300.0,
    step_w: float = 200.0,
    depth: float = 1500.0,
    base: float = 300.0,
    ratio: float = 20.0,
    factor: float | None = None,
    dims: bool = True,
    scale: float | None = None,
) -> dict[str, Any]:
    """基础大放脚（1:20）：以墙中心线与**室外地面**交点为 `at`，向下画基础剖面。

    墙身（wall 厚）从地面下到放脚顶，两侧对称各 `steps` 级台阶（每级高 step_h、宽 step_w），
    底部垫层厚 base；注埋深与基底宽两道尺寸。地面线向两侧出头。
    落块 `AA_FD_<id>`，`AA_TYPE=FOUNDATION`，`read_foundation` 回读。
    """
    block = "AA_FD_" + item_id
    if session.block_exists(block):
        raise CadError("基础 %s 已存在，请换编号" % item_id)
    w = float(wall)
    n = int(steps)
    sh = float(step_h)
    sw = float(step_w)
    D = float(depth)
    b = float(base)
    if w <= 0 or n < 1:
        raise CadError("墙厚必须 >0、放脚级数必须 ≥1")
    if sh <= 0 or sw <= 0 or b <= 0:
        raise CadError("台阶高/台阶宽/垫层厚必须 >0")
    if D <= n * sh + b:
        raise CadError("埋深必须大于 放脚高 + 垫层厚（现在 %g ≤ %g）" % (D, n * sh + b))
    ratio = float(ratio)
    if ratio <= 0:
        raise CadError("详图比例必须大于 0")
    sc = float(scale) if scale else drawing_scale(session)
    f = float(factor) if factor is not None else sc / ratio
    if f <= 0:
        raise CadError("大样放大倍数必须大于 0")

    ann = lambda mm: annot_size(mm, sc)  # noqa: E731
    WF, SHF, SWF, DF, BF = w * f, sh * f, sw * f, D * f, b * f
    half = WF / 2.0
    base_half = half + n * SWF

    lay_wall = LAYERS["wall"]
    lay_floor = LAYERS["step"]
    lay_dim = LAYERS["dim"]
    lay_name = LAYERS["name"]
    session.ensure_layers([lay_wall, lay_floor, lay_dim, lay_name])

    body: list[str] = []

    def seg(x1: float, y1: float, x2: float, y2: float, lay: str) -> None:
        body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                    % (x1, y1, x2, y2, lay))

    def txt(x: float, y: float, s: str, hgt: float, ang: float = 0.0) -> None:
        body.append('(aa:mktext-r (list %.3f %.3f) "%s" "%s" %.3f %.4f)'
                    % (x, y, str(s).replace('"', "'"), lay_name, hgt, ang))

    # 地面线
    seg(-base_half - ann(10.0), 0.0, base_half + ann(10.0), 0.0, lay_floor)

    y_step0 = -DF + BF            # 第一级台阶顶（垫层顶）
    y_top = y_step0 + n * SHF     # 放脚顶（墙身下口）

    # 左侧轮廓：墙脚 -> 逐级外放 -> 垫层底
    left = [(-half, 0.0), (-half, y_top)]
    for k in range(n):
        y = y_top - k * SHF
        x = -(half + (k + 1) * SWF)
        left.append((x, y))
        left.append((x, y - SHF))
    for i in range(len(left) - 1):
        seg(left[i][0], left[i][1], left[i + 1][0], left[i + 1][1], lay_wall)
    tail_y = left[-1][1]
    seg(left[-1][0], tail_y, left[-1][0], -DF, lay_wall)      # 垫层左外沿
    seg(left[-1][0], -DF, -left[-1][0], -DF, lay_wall)        # 垫层底
    seg(-left[-1][0], -DF, -left[-1][0], tail_y, lay_wall)    # 垫层右外沿
    right = [(-x, y) for (x, y) in reversed(left)][:-1]
    for i in range(len(right) - 1):
        seg(right[i][0], right[i][1], right[i + 1][0], right[i + 1][1], lay_wall)

    ndim = 0
    if dims:
        th = ann(2.5)
        tick = ann(2.0)
        # 埋深：左侧
        dx = -base_half - ann(10.0)
        for yy in (0.0, -DF):
            seg(-base_half, yy, dx - ann(2.0), yy, lay_dim)
        seg(dx, 0.0, dx, -DF, lay_dim)
        for yy in (0.0, -DF):
            seg(dx - tick, yy + tick, dx + tick, yy - tick, lay_dim)
        label = "%g" % D
        txt(dx - ann(1.2) - th, -DF / 2.0 - th / 2.0, label, th, 1.5708)
        ndim += 1
        # 基底宽：下方
        dy = -DF - ann(10.0)
        for xx in (-base_half, base_half):
            seg(xx, -DF, xx, dy - ann(2.0), lay_dim)
        seg(-base_half, dy, base_half, dy, lay_dim)
        for xx in (-base_half, base_half):
            seg(xx - tick, dy + tick, xx + tick, dy - tick, lay_dim)
        label = "%g" % (w + 2.0 * n * sw)
        txt(-_text_w(label, th) / 2.0, dy - ann(4.0), label, th)
        ndim += 1

    before = session.snapshot()
    session.lisp("(progn %s (princ \"ok\"))" % " ".join(body),
                 libraries=("aa_core.lisp", "aa_symbol.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("基础没有生成任何图元")

    bbox = [-base_half - ann(30.0), -DF - ann(30.0),
            base_half + ann(12.0), ann(10.0)]
    att_defs = [
        ("AA_TYPE", "component type", "FOUNDATION"),
        ("AA_ID", "component id", item_id),
        ("AA_WALL", "wall thickness", "%.4f" % w),
        ("AA_STEPS", "footing steps", str(n)),
        ("AA_STEPH", "step height", "%.4f" % sh),
        ("AA_STEPW", "step width", "%.4f" % sw),
        ("AA_DEPTH", "embedment depth", "%.4f" % D),
        ("AA_BASE", "cushion thickness", "%.4f" % b),
        ("AA_BASEW", "base width", "%.4f" % (w + 2.0 * n * sw)),
        ("AA_FACTOR", "enlarge factor", "%.4f" % f),
        ("AA_RATIO", "detail ratio", "1:%g" % ratio),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {k: v for k, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, tuple(at), att_vals, layer=lay_wall)
    session.expect_attributes(block, {"AA_TYPE": "FOUNDATION", "AA_ID": item_id})
    return {"block": block, "handle": handle, "id": item_id, "wall": w,
            "steps": n, "step_h": sh, "step_w": sw, "depth": D, "base": b,
            "base_width": w + 2.0 * n * sw, "factor": f,
            "ratio": "1:%g" % ratio, "dims": ndim, "bbox": bbox,
            "geom_handles": handles}


def read_foundation(session: Session, item_id: str) -> dict[str, Any]:
    """回读基础：墙厚/级数/台阶/埋深/垫层/基底宽/倍数/比例。"""
    attrs = session.attributes("AA_FD_" + item_id)
    if not attrs or attrs.get("AA_TYPE") != "FOUNDATION":
        raise CadError("没找到基础 %s" % item_id)
    return {"id": item_id,
            "wall": float(attrs.get("AA_WALL") or 0),
            "steps": int(float(attrs.get("AA_STEPS") or 0)),
            "step_h": float(attrs.get("AA_STEPH") or 0),
            "step_w": float(attrs.get("AA_STEPW") or 0),
            "depth": float(attrs.get("AA_DEPTH") or 0),
            "base": float(attrs.get("AA_BASE") or 0),
            "base_width": float(attrs.get("AA_BASEW") or 0),
            "factor": float(attrs.get("AA_FACTOR") or 0),
            "ratio": attrs.get("AA_RATIO", "")}


# ---------------- 注字：单行文字 / 引线（v1.0.41，B7 收尾） ----------------

def _rot_pt(x: float, y: float, ang: float) -> tuple[float, float]:
    ca, sa = math.cos(ang), math.sin(ang)
    return (x * ca - y * sa, x * sa + y * ca)


def create_text(
    session: Session,
    text_id: str,
    at: tuple[float, float],
    text: str,
    height: float = 3.5,
    rotation: float = 0.0,
    factor: float | None = None,
    scale: float | None = None,
) -> dict[str, Any]:
    """图上注一行字：`at` 为文字左下角（基线左端），`height` 为图面字高（mm）。

    用于门窗编号、材料做法、房间名之外的零星注字；落块 `AA_TXT_<id>`，
    `AA_TYPE=TEXT`，`read_text` 回读。rotation 单位为度（逆时针）。
    """
    if not str(text).strip():
        raise CadError("注字内容不能为空")
    if float(height) <= 0:
        raise CadError("字高必须大于 0")
    if float(rotation) <= -360 or float(rotation) >= 360:
        raise CadError("旋转角必须在 -360 ~ 360 度之间")
    block = "AA_TXT_" + text_id
    if session.block_exists(block):
        raise CadError("注字 %s 已存在，请换编号" % text_id)
    sc = float(scale) if scale else drawing_scale(session)
    f = float(factor) if factor is not None else 1.0
    if f <= 0:
        raise CadError("放大倍数必须大于 0")
    hgt = annot_size(float(height), sc) * f
    ang = math.radians(float(rotation))

    lay_name = LAYERS["name"]
    session.ensure_layers([lay_name])
    before = session.snapshot()
    # 块内按局部坐标 (0,0) 画，再 insert 到 at，避免插入点二次偏移
    session.lisp('(progn (aa:mktext-r (list 0.0 0.0) "%s" "%s" %.3f %.4f) (princ "ok"))'
                 % (str(text).replace('"', "'"), lay_name, hgt, ang),
                 libraries=("aa_core.lisp", "aa_symbol.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("注字没有生成任何图元")

    w = _text_w(str(text), hgt)
    corners = [_rot_pt(x, y, ang) for x, y in
               ((0.0, 0.0), (w, 0.0), (w, hgt), (0.0, hgt))]
    xs = [at[0] + c[0] for c in corners]
    ys = [at[1] + c[1] for c in corners]
    bbox = [min(xs), min(ys), max(xs), max(ys)]

    att_defs = [
        ("AA_TYPE", "component type", "TEXT"),
        ("AA_ID", "component id", text_id),
        ("AA_TEXT", "text content", str(text)),
        ("AA_H", "text height", "%.4f" % hgt),
        ("AA_ROT", "rotation deg", "%.4f" % float(rotation)),
        ("AA_ATX", "anchor x", "%.4f" % float(at[0])),
        ("AA_ATY", "anchor y", "%.4f" % float(at[1])),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {k: v for k, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, tuple(at), att_vals, layer=lay_name)
    session.expect_attributes(block, {"AA_TYPE": "TEXT", "AA_ID": text_id})
    return {"block": block, "handle": handle, "id": text_id, "text": str(text),
            "height": hgt, "rotation": float(rotation), "bbox": bbox,
            "geom_handles": handles}


def read_text(session: Session, text_id: str) -> dict[str, Any]:
    """回读注字：内容/字高/旋转/锚点。"""
    attrs = session.attributes("AA_TXT_" + text_id)
    if not attrs or attrs.get("AA_TYPE") != "TEXT":
        raise CadError("没找到注字 %s" % text_id)
    return {"id": text_id, "text": attrs.get("AA_TEXT", ""),
            "height": float(attrs.get("AA_H") or 0),
            "rotation": float(attrs.get("AA_ROT") or 0),
            "at": [float(attrs.get("AA_ATX") or 0),
                   float(attrs.get("AA_ATY") or 0)]}


def create_leader(
    session: Session,
    lead_id: str,
    at: tuple[float, float],
    text: str,
    to: tuple[float, float] | None = None,
    height: float = 3.0,
    shelf: float = 5.0,
    factor: float | None = None,
    scale: float | None = None,
) -> dict[str, Any]:
    """引线注字（索引/做法/材料）：`at` 为被注点，`to` 为文字基线左端（缺省右上 10mm）。

    画斜引线（带 2.5mm 箭头）+ 文字下水平短线（shelf，GB/T 50001 的"引线横段"），
    文字压在横段上。落块 `AA_LD_<id>`，`AA_TYPE=LEADER`，`read_leader` 回读。
    """
    if not str(text).strip():
        raise CadError("引注内容不能为空")
    if float(height) <= 0 or float(shelf) <= 0:
        raise CadError("字高与横段长度必须大于 0")
    block = "AA_LD_" + lead_id
    if session.block_exists(block):
        raise CadError("引注 %s 已存在，请换编号" % lead_id)
    sc = float(scale) if scale else drawing_scale(session)
    f = float(factor) if factor is not None else 1.0
    if f <= 0:
        raise CadError("放大倍数必须大于 0")
    ann = lambda mm: annot_size(mm, sc) * f  # noqa: E731
    hgt = ann(float(height))
    sh = ann(float(shelf))
    at = (float(at[0]), float(at[1]))
    if to is None:
        to = (at[0] + ann(10.0), at[1] + ann(10.0))
    to = (float(to[0]), float(to[1]))
    dx, dy = to[0] - at[0], to[1] - at[1]
    ln = math.hypot(dx, dy)
    if ln < 1e-6:
        raise CadError("引线起点与终点重合")
    ux, uy = dx / ln, dy / ln

    lay_dim = LAYERS["dim"]
    lay_name = LAYERS["name"]
    session.ensure_layers([lay_dim, lay_name])

    body: list[str] = []
    body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                % (at[0], at[1], to[0], to[1], lay_dim))
    for sgn in (1.0, -1.0):
        # 箭头两条边：从尖端沿引线反方向、再各偏 ±12°
        ca, sa = math.cos(math.radians(12.0 * sgn)), math.sin(math.radians(12.0 * sgn))
        vx, vy = -ux, -uy
        ex = vx * ca - vy * sa
        ey = vx * sa + vy * ca
        body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                    % (at[0], at[1], at[0] + ex * ann(2.5), at[1] + ey * ann(2.5), lay_dim))
    body.append('(aa:mkline (list %.3f %.3f) (list %.3f %.3f) "%s")'
                % (to[0], to[1], to[0] + sh, to[1], lay_dim))
    body.append('(aa:mktext-r (list %.3f %.3f) "%s" "%s" %.3f 0.0)'
                % (to[0] + ann(0.6), to[1] + ann(0.8), str(text).replace('"', "'"),
                   lay_name, hgt))

    before = session.snapshot()
    session.lisp("(progn %s (princ \"ok\"))" % " ".join(body),
                 libraries=("aa_core.lisp", "aa_symbol.lisp"))
    handles = session.new_handles(before)
    if not handles:
        raise CadError("引注没有生成任何图元")

    tw = _text_w(str(text), hgt)
    bbox = [min(at[0], to[0]) - ann(2.5), min(at[1], to[1]) - ann(0.5),
            to[0] + max(sh, tw) + ann(1.0), to[1] + hgt + ann(1.0)]

    att_defs = [
        ("AA_TYPE", "component type", "LEADER"),
        ("AA_ID", "component id", lead_id),
        ("AA_TEXT", "text content", str(text)),
        ("AA_H", "text height", "%.4f" % hgt),
        ("AA_SHELF", "shelf length", "%.4f" % sh),
        ("AA_ATX", "anchor x", "%.4f" % at[0]),
        ("AA_ATY", "anchor y", "%.4f" % at[1]),
        ("AA_TOX", "text x", "%.4f" % to[0]),
        ("AA_TOY", "text y", "%.4f" % to[1]),
        ("AA_SCALE", "drawing scale 1:n", "%.4g" % sc),
    ]
    att_vals = {k: v for k, _p, v in att_defs}
    att_handles = session.define_attributes(att_defs)
    session.make_block(block, (0.0, 0.0), handles + att_handles)
    handle = session.insert(block, (0.0, 0.0), att_vals, layer=lay_dim)
    session.expect_attributes(block, {"AA_TYPE": "LEADER", "AA_ID": lead_id})
    return {"block": block, "handle": handle, "id": lead_id, "text": str(text),
            "at": list(at), "to": list(to), "height": hgt, "shelf": sh,
            "bbox": bbox, "geom_handles": handles}


def read_leader(session: Session, lead_id: str) -> dict[str, Any]:
    """回读引注：内容/字高/横段/被注点/文字点。"""
    attrs = session.attributes("AA_LD_" + lead_id)
    if not attrs or attrs.get("AA_TYPE") != "LEADER":
        raise CadError("没找到引注 %s" % lead_id)
    return {"id": lead_id, "text": attrs.get("AA_TEXT", ""),
            "height": float(attrs.get("AA_H") or 0),
            "shelf": float(attrs.get("AA_SHELF") or 0),
            "at": [float(attrs.get("AA_ATX") or 0),
                   float(attrs.get("AA_ATY") or 0)],
            "to": [float(attrs.get("AA_TOX") or 0),
                   float(attrs.get("AA_TOY") or 0)]}
