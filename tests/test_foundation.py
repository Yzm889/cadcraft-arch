"""基础大放脚验收（v1.0.40）。

验收：1:20 → 5 倍；墙身/两级台阶/垫层齐备；埋深与基底宽两道尺寸；
级数与基底宽计算正确；bbox 与几何口径一致；属性回读；重号、墙厚 0、级数 0、
埋深不足、比例 0 五类拒绝；CLI --show 与库一致。
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
    create_foundation,
    read_foundation,
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
    path = OUT / "test_foundation.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    fd = create_foundation(s, "FD1", (0.0, 0.0))
    assert fd["factor"] == 5.0 and fd["dims"] == 4, fd
    assert fd["wall"] == 240.0 and fd["steps"] == 2, fd
    assert fd["depth"] == 2000.0 and fd["base"] == 300.0, fd
    assert fd["base_width"] == 500.0 and fd["cushion_width"] == 600.0, fd
    assert fd["ratio"] == "1:20", fd
    assert fd["bbox"] == [-8000.0, -13000.0, 6500.0, 1000.0], fd["bbox"]

    fd2 = create_foundation(s, "FD2", (9000.0, 0.0), wall=200.0, steps=1,
                            step_h=300.0, step_w=300.0, depth=1200.0, base=200.0)
    assert fd2["base_width"] == 800.0, fd2
    assert fd2["bbox"] == [-8750.0, -9000.0, 7250.0, 1000.0], fd2["bbox"]

    back = read_foundation(s, "FD1")
    assert back["wall"] == 240.0 and back["base_width"] == 500.0, back
    assert back["depth"] == 2000.0 and back["factor"] == 5.0, back
    back2 = read_foundation(s, "FD2")
    assert back2["steps"] == 1 and back2["base"] == 200.0, back2

    cases = [
        (lambda: create_foundation(s, "FD1", (0.0, 0.0)), "已存在"),
        (lambda: create_foundation(s, "FD3", (0.0, 0.0), wall=0), "墙厚"),
        (lambda: create_foundation(s, "FD3", (0.0, 0.0), steps=0), "放脚级数"),
        (lambda: create_foundation(s, "FD3", (0.0, 0.0), depth=500), "埋深"),
        (lambda: create_foundation(s, "FD3", (0.0, 0.0), ratio=0), "比例"),
    ]
    for fn, want in cases:
        try:
            fn()
        except CadError as e:
            assert want in str(e), (want, e)
        else:
            raise AssertionError("应拒绝：%s" % want)

    q = cli("foundation", str(path), "FD1", "--show=FD1")
    assert q["ok"] and q["steps"] == 2 and q["base_width"] == 500.0, q
    q = cli("foundation", str(path), "FD2", "--show=FD2")
    assert q["ok"] and q["steps"] == 1 and q["base_width"] == 800.0, q

    print("基础大放脚: 240 墙 / 2 级 130×65 / 埋深 2000 / 垫层 300 / 基底 500 / 垫层 600")
    print("PASS test_foundation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
