"""墙身节点验收（v1.0.36）：窗台节点 SILL + 女儿墙节点 PARAPET。

验收：1:20 放大 5 倍；墙厚注释 240、窗台高 900 / 女儿墙高 1200 各一道；
bbox 与几何口径一致；属性回读（墙厚/板厚/窗台/女儿墙/压顶/倍数/比例）；
重号、类型错、墙厚 0、比例 0、窗台高 0、女儿墙高 0 六类拒绝；CLI --show 与库一致。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    create_wall_node,
    read_wall_node,
    set_drawing_scale,
)

OUT = ROOT / "samples"
CMD = ROOT / "tools" / "aa_cmd.py"


def cli(*args: str) -> dict:
    r = subprocess.run([sys.executable, str(CMD), *args],
                       capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or "").strip().splitlines()
    assert out, (r.returncode, r.stderr)
    return json.loads(out[-1])


def main() -> int:
    path = OUT / "test_wall_node.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    sill = create_wall_node(s, "WN1", (0.0, 0.0), "SILL", ratio=20)
    assert sill["kind"] == "SILL" and sill["factor"] == 5.0 and sill["dims"] == 2, sill
    assert sill["wall"] == 240.0 and sill["sill"] == 900.0, sill
    assert sill["ratio"] == "1:20" and sill["title"] == "窗台节点", sill
    assert sill["bbox"] == [-2900.0, -5100.0, 8700.0, 8900.0], sill["bbox"]

    para = create_wall_node(s, "WN2", (9000.0, 0.0), "PARAPET", ratio=20,
                            parapet=1200.0, cap=60.0, cap_out=60.0)
    assert para["kind"] == "PARAPET" and para["factor"] == 5.0 and para["dims"] == 2, para
    assert para["parapet"] == 1200.0 and para["cap"] == 60.0, para
    assert para["title"] == "女儿墙节点", para
    assert para["bbox"][3] == 7700.0, para["bbox"]

    back = read_wall_node(s, "WN1")
    assert back["wall"] == 240.0 and back["slab"] == 120.0, back
    assert back["sill"] == 900.0 and back["cap_out"] == 60.0, back
    assert back["factor"] == 5.0 and back["ratio"] == "1:20", back
    back2 = read_wall_node(s, "WN2")
    assert back2["parapet"] == 1200.0 and back2["cap"] == 60.0, back2

    cases = [
        (lambda: create_wall_node(s, "WN1", (0.0, 0.0)), "已存在"),
        (lambda: create_wall_node(s, "WN3", (0.0, 0.0), "CORNER"), "SILL / PARAPET"),
        (lambda: create_wall_node(s, "WN3", (0.0, 0.0), "SILL", wall_thick=0), "墙厚"),
        (lambda: create_wall_node(s, "WN3", (0.0, 0.0), "SILL", ratio=0), "比例"),
        (lambda: create_wall_node(s, "WN3", (0.0, 0.0), "SILL", sill=0), "窗台高"),
        (lambda: create_wall_node(s, "WN3", (0.0, 0.0), "PARAPET", parapet=0), "女儿墙高"),
    ]
    for fn, want in cases:
        try:
            fn()
        except CadError as e:
            assert want in str(e), (want, e)
        else:
            raise AssertionError("应拒绝：%s" % want)

    q = cli("wall-node", str(path), "WN1", "--show=WN1")
    assert q["ok"] and q["kind"] == "SILL" and q["sill"] == 900.0, q
    q = cli("wall-node", str(path), "WN2", "--show=WN2")
    assert q["ok"] and q["kind"] == "PARAPET" and q["parapet"] == 1200.0, q

    print("墙身节点: 窗台 900 / 女儿墙 1200，1:20（5 倍），各 2 道尺寸，属性回读一致")
    print("PASS test_wall_node")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
