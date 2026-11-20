"""楼梯间大样验收（v1.0.37）：直跑 STRAIGHT + 双跑 DOGLEG。

验收：从图上楼梯读参数（梯段宽/踏步数/踏步宽/梯井/平台），1:20 放大 5 倍；
直跑注 2 道（梯段宽 + 踏步总长“步数×踏步宽=总长”），双跑再注平台深共 3 道；
bbox 与几何口径一致；属性回读一致；重号/没楼梯/比例 0/倍数 0/缺源楼梯五类拒绝；
CLI --show 与库一致。
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
    create_stair,
    create_stair_detail,
    read_stair_detail,
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
    path = OUT / "test_stair_detail.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    create_stair(s, "ST1", (0.0, 0.0), kind="STRAIGHT", width=1100, steps=12,
                 tread=260, angle=0, level="MIDDLE")
    straight = create_stair_detail(s, "SD1", (0.0, -8000.0), "ST1", ratio=20)
    assert straight["kind"] == "STRAIGHT" and straight["factor"] == 5.0, straight
    assert straight["dims"] == 2, straight
    assert straight["width"] == 1100.0 and straight["steps"] == 12, straight
    assert straight["tread"] == 260.0 and straight["run"] == 3120.0, straight
    assert straight["ratio"] == "1:20" and straight["title"] == "楼梯间详图", straight
    assert straight["bbox"] == [-3000.0, -3000.0, 7300.0, 17200.0], straight["bbox"]

    create_stair(s, "ST2", (30000.0, 0.0), kind="DOGLEG", width=1200, steps=10,
                 tread=280, well=120, landing=1200, angle=0, level="MIDDLE", side="LEFT")
    dog = create_stair_detail(s, "SD2", (9000.0, 0.0), "ST2", ratio=20)
    assert dog["kind"] == "DOGLEG" and dog["factor"] == 5.0, dog
    assert dog["dims"] == 3, dog
    assert dog["well"] == 120.0 and dog["landing"] == 1200.0, dog
    assert dog["run"] == 2800.0, dog
    assert dog["bbox"] == [-3000.0, -3000.0, 14400.0, 21600.0], dog["bbox"]

    back = read_stair_detail(s, "SD1")
    assert back["ref"] == "ST1" and back["kind"] == "STRAIGHT", back
    assert back["run"] == 3120.0 and back["factor"] == 5.0, back
    back2 = read_stair_detail(s, "SD2")
    assert back2["well"] == 120.0 and back2["landing"] == 1200.0, back2
    assert back2["ratio"] == "1:20", back2

    cases = [
        (lambda: create_stair_detail(s, "SD1", (0.0, 0.0), "ST1"), "已存在"),
        (lambda: create_stair_detail(s, "SD3", (0.0, 0.0), "ST9"), "没有楼梯"),
        (lambda: create_stair_detail(s, "SD3", (0.0, 0.0)), "源楼梯编号"),
        (lambda: create_stair_detail(s, "SD3", (0.0, 0.0), "ST1", ratio=0), "比例"),
        (lambda: create_stair_detail(s, "SD3", (0.0, 0.0), "ST1", factor=0), "倍数"),
    ]
    for fn, want in cases:
        try:
            fn()
        except CadError as e:
            assert want in str(e), (want, e)
        else:
            raise AssertionError("应拒绝：%s" % want)

    q = cli("stair-detail", str(path), "SD1", "--show=SD1")
    assert q["ok"] and q["kind"] == "STRAIGHT" and q["run"] == 3120.0, q
    q = cli("stair-detail", str(path), "SD2", "--show=SD2")
    assert q["ok"] and q["kind"] == "DOGLEG" and q["landing"] == 1200.0, q

    print("楼梯间大样: 直跑 12×260（2 道尺寸）/ 双跑 10×280+平台 1200（3 道），1:20（5 倍）")
    print("PASS test_stair_detail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
