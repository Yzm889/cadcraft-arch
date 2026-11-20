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
    """当前图档的出图比例分母：优先取图上 `AA_SHEET` 的 AA_SCALE，没有图幅按 100。

    `session.annot_scale` 可显式覆盖（CLI/MCP 的 --scale 参数走这里），
    这样"先画标注、后套图框"和"先套图框、后画标注"两种顺序都成立。
    """
    forced = getattr(session, "annot_scale", None)
    if forced:
        return float(forced)
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

    def new_metric(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._exec(["run", "--metric", "--save", str(self.path)])
        if not self.path.exists():
            raise CadError("新建图纸失败：%s" % self.path)
        # 一开图就把 9 个标准层按 GB/天正规格建好（颜色、线型、线宽一次到位）
        self.ensure_layers()

    # ---------- LISP ----------

    def lisp(self, code: str, libraries: Sequence[str] = ()) -> str:
        """执行一段 LISP，返回它的 prin1 值（字符串）。"""
        loads = "".join('(load "%s")' % str(LISP_DIR / lib).replace("\\", "/") for lib in libraries)
        # 用户图档自己的图层标准优先：覆盖 aa_core 里的默认层名
        sets = "".join(
            '(setq aa:*lay-%s* "%s")' % (k, LAYERS[k])
            for k in ("axis", "axistext", "wall", "opening", "room", "sheet", "title", "table")
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
    if scale not in (None, ""):
        text = str(scale)
        denom = float(text.split(":")[-1]) if ":" in text else float(text)
        label = "1:%g" % denom
    sc = float(denom) if denom else drawing_scale(session)
    session.ensure_layers([LAYERS["name"], LAYERS["sheet"]])
    before = session.snapshot()
    session.lisp(
        "(progn (setq aa:*title-h* %.4f) (setq aa:*title-scale-h* %.4f)"
        " (setq aa:*name-h* %.4f) (aa:title %.3f %.3f \"%s\" \"%s\"))"
        % (annot_size(5.0, sc), annot_size(3.5, sc), annot_size(3.5, sc),
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
            create_room(session, r["id"], r["walls"], r["name"])

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
    if label_side not in ("in", "out", "auto"):
        raise CadError("拒绝写入：label_side 只能是 in / out / auto（收到 %s）" % label_side)
    # 墙块若转了 180°（墙从右往左画），块内编号会倒着看；给文字补 180° 抵消。
    rot_deg = (math.degrees(wall["rotation_rad"]) + 360.0) % 360.0
    label_rot = math.pi if 135.0 <= rot_deg <= 225.0 else 0.0
    side = _label_side_sign(session, wall, pos, label_side)

    block = "AA_OPENING_" + opening_id
    session.ensure_layers([LAYERS["opening"]])

    before = session.snapshot()
    sc = drawing_scale(session)
    value = session.lisp(
        '(progn (setq aa:*label-h* %.4f) (aa:opening %s %s %s "%s" %s "%s" %s %s))'
        % (annot_size(1.8, sc), pos, width, thick, kind, frame, no, label_rot, side),
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
                scale: float | None = None) -> dict[str, Any]:
    """把算好的房间轮廓落图：LISP 画名称 -> block -> insert -> 回读校验。"""
    block = "AA_ROOM_" + room_id
    session.ensure_layers([LAYERS["room"]])
    sc = float(scale) if scale else drawing_scale(session)

    pts_lisp = " ".join("(list %.4f %.4f 0.0)" % (p[0], p[1]) for p in inner)
    before = session.snapshot()
    value = session.lisp(
        '(progn (setq aa:*room-h* %.4f) (aa:room (list %s) "%s"))'
        % (annot_size(2.5, sc), pts_lisp, name),
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


def create_room(
    session: Session,
    room_id: str,
    wall_ids: Sequence[str],
    name: str = "",
    tol: float = 1e-6,
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

    # 串成闭合环（允许墙反向，自动纠正）
    ring_pts = [segs[0]["p1"], segs[0]["p2"]]
    oriented = [segs[0]]
    for seg in segs[1:]:
        last = ring_pts[-1]
        if math.dist(last, seg["p1"]) <= 1.0:
            ring_pts.append(seg["p2"])
            oriented.append(seg)
        elif math.dist(last, seg["p2"]) <= 1.0:
            ring_pts.append(seg["p1"])
            oriented.append({**seg, "u": (-seg["u"][0], -seg["u"][1])})
        else:
            raise CadError(
                "拒绝写入：墙环断裂，墙 %s 的端点与上一个终点不重合" % seg["id"]
            )
    if math.dist(ring_pts[-1], ring_pts[0]) > 1.0:
        raise CadError("拒绝写入：墙环未闭合（末墙终点的偏差 %.4f）"
                       % math.dist(ring_pts[-1], ring_pts[0]))
    ring_pts = ring_pts[:-1]  # 去掉重复的闭合点
    edges = [(ring_pts[i], ring_pts[(i + 1) % len(ring_pts)], oriented[i]["id"])
             for i in range(len(ring_pts))]

    inner, area = _room_inner(edges, thick, tol)
    return _store_room(session, room_id, inner, area, wall_ids, name)


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
    """读取全部门窗洞口。"""
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
            }
        )
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
             wall_off: float | None = None, clear: bool = True,
             exterior_only: bool = True, scale: float | None = None) -> dict[str, Any]:
    """给外墙标尺寸：墙段长度在外层、洞口宽在内层，都标在建筑外侧。

    - 外侧判断：取所有墙中点均值作为"建筑内部参考点"，
      法向两侧各取一点，离参考点更远的那侧就是外侧。
    - 只标外墙（内墙两侧都是房间，标注会压在房间名和门扇上）；
      图纸里还没有房间时退化为全部墙都标。
    - 两道尺寸线分别离墙面 500 / 1150，轴号圆在 1600 以外，互不压线。
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
        wall_off = annot_size(20.0, sc)        # 外层尺寸线离墙 20mm
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

        # 墙总长（外层）
        at = (mid[0] + n[0] * side * (half + wall_off),
              mid[1] + n[1] * side * (half + wall_off))
        cmds.append(("dimlinear", {"p1": list(p1), "p2": list(p2),
                                   "at": [round(at[0], 4), round(at[1], 4)],
                                   "rotation": round(ang, 6)}))
        made.append({"kind": "wall", "id": w["id"], "value": round(w["len"], 2)})

        # 洞口宽（内层）
        for o in openings:
            if o["wallid"] != w["id"]:
                continue
            o1 = (p1[0] + d[0] * (o["pos"] - o["width"] / 2.0),
                  p1[1] + d[1] * (o["pos"] - o["width"] / 2.0))
            o2 = (p1[0] + d[0] * (o["pos"] + o["width"] / 2.0),
                  p1[1] + d[1] * (o["pos"] + o["width"] / 2.0))
            omid = ((o1[0] + o2[0]) / 2.0, (o1[1] + o2[1]) / 2.0)
            oat = (omid[0] + n[0] * side * (half + opening_off),
                   omid[1] + n[1] * side * (half + opening_off))
            cmds.append(("dimlinear", {"p1": [round(v, 4) for v in o1],
                                       "p2": [round(v, 4) for v in o2],
                                       "at": [round(oat[0], 4), round(oat[1], 4)],
                                       "rotation": round(ang, 6)}))
            made.append({"kind": "opening", "id": o["id"], "value": round(o["width"], 2)})

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
) -> dict[str, Any]:
    """墙体：LISP 生成本地几何 -> block -> insert（起点+旋转）-> 回读校验。

    snap_axis=True 时先把端点吸附到最近轴线（"先轴后墙"），吸附量在返回值里如实报告；
    画完若图上有轴网，会自动回填 ax1/ax2（原有的非空值不覆盖）。
    """
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
                           "sx": None, "sy": None, "ex": None, "ey": None}
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
            out.append({"type": e["type"], "text": e["txt"], "layer": e["layer"], "pts": [at] if at else []})
        elif e["type"] == "CIRCLE" and None not in (e["sx"], e["sy"], e["r"]):
            out.append({"type": "CIRCLE", "r": e["r"], "layer": e["layer"], "pts": [(e["sx"], e["sy"])]})
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
    scale: float = 100.0,
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

    at = 内框左下角（模型坐标）。不给则按"墙+房间"外廓自动居中排图；
    图形超出内框时报错，提示换大图幅或调小比例。
    """
    lay = sheet_layout(size, scale)
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
                    "请换大图幅或调小比例" % (size, scale, need_w, need_h,
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
    for ref in session.references():
        g = ref["geometry"]
        block = g.get("block")
        if not block:
            continue
        for e in _block_geometry_cached(session.path, block, cache):
            lay = e.get("layer") or ref.get("layer") or "0"
            spec = table.get(lay)
            if not spec or float(spec["lineweight"]) < min_mm:
                continue
            width = max(1, int(round(float(spec["lineweight"]) * px_per_mm)))
            if width < 2:
                continue
            color = ACI_RGB.get(spec["color"], (240, 240, 240))
            world = [_insert_tf((p[0], p[1]), ref) for p in e["pts"] if p]
            scr = [(ox + (p[0] - x0) * fit, oy + (y1 - p[1]) * fit) for p in world]
            for a, b in zip(scr, scr[1:]):
                draw.line([a, b], fill=color, width=width)
            if e["type"] in ("LINE", "LWPOLYLINE"):
                thick += 1
    img.save(out)
    return {"thickened": thick, "px_per_mm": round(px_per_mm, 2)}


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
        res = _store_room(session, room_id, list(r["pts"]), r["area"], r["walls"], new_name)
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


