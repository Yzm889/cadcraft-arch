"""图层规格验收：新图自动建层、层色/线型/线宽符合标准、旧图可被纠正、用户可自定义。

对应需求：“不同部件在不同图层上、按标准的线型颜色画，画的时候就自动建好”。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_lib  # noqa: E402
from aa_lib import (  # noqa: E402
    LAYERS,
    LAYER_STYLES,
    Session,
    create_opening,
    create_wall,
    layer_table,
)

OUT = ROOT / "samples"


def main() -> int:
    # 1. 新图：一开图就有 9 个标准层，颜色/线型/线宽全对
    path = OUT / "test_layer_style.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()
    table = layer_table(path)
    expect = {
        "axis": (1, "CENTER", 0.15),
        "axistext": (1, "Continuous", 0.15),
        "wall": (7, "Continuous", 0.35),
        "opening": (4, "Continuous", 0.18),
        "room": (7, "Continuous", 0.18),
        "dim": (3, "Continuous", 0.15),
        "sheet": (7, "Continuous", 0.70),
        "border": (7, "Continuous", 0.15),
        "title": (7, "Continuous", 0.25),
        "table": (7, "Continuous", 0.18),
    }
    for key, (color, lt, lw) in expect.items():
        got = table.get(LAYERS[key])
        assert got is not None, ("缺层", LAYERS[key], sorted(table))
        assert got["color"] == color, (key, got)
        assert str(got["linetype"]).lower() == lt.lower(), (key, got)
        assert abs(got["lineweight"] - lw) < 0.011, (key, got)
    print("新图 10 层规格 ok:", {LAYERS[k]: (v["color"], v["linetype"], v["lineweight"])
                            for k, v in [("axis", table[LAYERS["axis"]]),
                                         ("wall", table[LAYERS["wall"]])]})

    # 2. 图层被人改坏了（全白 + Continuous），下次画墙时自动纠回来
    s.run([("layer.set", {"name": LAYERS["wall"], "color": 9,
                          "linetype": "Continuous", "lineweight": 0.05})], save=True)
    broke = layer_table(path)[LAYERS["wall"]]
    assert broke["color"] == 9 and broke["lineweight"] == 0.05, broke
    create_wall(s, "W001", (0.0, 0.0), (4000.0, 0.0), thick=240.0, kind="EXTERNAL")
    fixed = layer_table(path)[LAYERS["wall"]]
    assert fixed["color"] == 7 and fixed["linetype"] == "Continuous", fixed
    assert abs(fixed["lineweight"] - 0.35) < 0.011, fixed
    print("坏层自动纠回:", fixed)

    # 3. 部件真的落在各自层上（块内几何图层）
    create_opening(s, "D001", "W001", "DOOR", width=900.0, pos=1200.0)
    assert aa_lib.layer_of_block(path, "AA_WALL_W001") - {"0"} <= {LAYERS["wall"]}
    assert aa_lib.layer_of_block(path, "AA_OPENING_D001") - {"0"} <= {LAYERS["opening"]}
    print("部件分层 ok")

    # 4. 用户自定义：层名 + 颜色名（红）+ 线型 + 线宽 都能覆盖
    cfg = OUT / "_layer_style_custom.json"
    cfg.write_text(json.dumps({
        "axis": {"name": "AXIS", "color": "红", "linetype": "CENTER", "lineweight": 0.25},
        "wall": "WALL",
    }, ensure_ascii=False), encoding="utf-8")
    old_env = os.environ.get("AA_LAYERS_FILE")
    os.environ["AA_LAYERS_FILE"] = str(cfg)
    try:
        got = aa_lib.load_layer_config()
        assert got["layers"]["axis"] == "AXIS" and got["layers"]["wall"] == "WALL", got
        assert got["styles"]["axis"]["color"] == 1, got
        assert got["styles"]["axis"]["lineweight"] == 0.25, got

        p2 = OUT / "test_layer_style_custom.dxf"
        if p2.exists():
            p2.unlink()
        s2 = Session(p2)
        s2.new_metric()
        t2 = layer_table(p2)
        assert t2["AXIS"]["color"] == 1 and t2["AXIS"]["linetype"] == "CENTER", t2
        assert abs(t2["AXIS"]["lineweight"] - 0.25) < 0.011, t2
        assert "WALL" in t2, sorted(t2)
        print("自定义层规格 ok:", t2["AXIS"])
    finally:
        if old_env is None:
            os.environ.pop("AA_LAYERS_FILE", None)
        else:
            os.environ["AA_LAYERS_FILE"] = old_env
        aa_lib.load_layer_config()

    # 5. 预览补线宽：线宽 0.35 的墙在 PNG 里必须比"不补线宽"更粗
    p3 = OUT / "test_layer_lw.dxf"
    if p3.exists():
        p3.unlink()
    s3 = Session(p3)
    s3.new_metric()
    create_wall(s3, "W001", (0.0, 0.0), (4000.0, 0.0), thick=240.0, kind="EXTERNAL")
    win3 = (-500.0, -500.0, 4500.0, 1500.0)
    on = aa_lib.export(s3, OUT / "test_layer_lw_on.png", win3, lineweights=True, scale=100)
    off = aa_lib.export(s3, OUT / "test_layer_lw_off.png", win3, lineweights=False)
    assert on.get("thickened", 0) > 0, on

    from PIL import Image
    def bright(path):
        im = Image.open(path).convert("L")
        return sum(1 for p in im.convert('L').tobytes() if p > 100)
    n_on, n_off = bright(OUT / "test_layer_lw_on.png"), bright(OUT / "test_layer_lw_off.png")
    assert n_on > n_off, (n_on, n_off)
    print("补线宽前后亮点数:", n_off, "->", n_on, "px_per_mm", on.get("px_per_mm"))

    print("PASS test_layer_style")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
