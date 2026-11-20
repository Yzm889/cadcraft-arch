"""立面阳台 / 雨篷验收（v1.0.39）。

验收：阳台画挑板 + 栏板（宽/栏板高两道尺寸），雨篷画挑板 + 牛腿（只注宽）；
竖直位置不再二次偏移（落点 y 与属性一致）；属性回读；重号、类型错、宽度 0、
栏板高 0、挑出宽 0 五类拒绝；CLI --show 与库一致。
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
    create_elev_balcony,
    create_elevation,
    read_elev_balcony,
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
    path = OUT / "test_elev_balcony.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)
    create_elevation(s, "E1", (0.0, 0.0), 6000.0, [{"height": 3600}, {"height": 3600}],
                     roof="FLAT", dims=False, marks=False)

    b = create_elev_balcony(s, "EB1", (1200.0, 3600.0), 2400.0)
    assert b["kind"] == "BALCONY" and b["dims"] == 2, b
    assert b["width"] == 2400.0 and b["slab"] == 100.0 and b["rail"] == 1000.0, b
    assert b["depth"] == 1200.0, b
    assert b["bbox"] == [-1400.0, 0.0, 4600.0, 6100.0], b["bbox"]

    a = create_elev_balcony(s, "EB2", (3200.0, 2100.0), 1600.0, kind="AWNING", slab=120.0)
    assert a["kind"] == "AWNING" and a["dims"] == 1, a
    assert a["slab"] == 120.0, a
    assert a["bbox"] == [600.0, -1500.0, 5800.0, 3620.0], a["bbox"]

    back = read_elev_balcony(s, "EB1")
    assert back["kind"] == "BALCONY" and back["rail"] == 1000.0, back
    assert back["depth"] == 1200.0, back
    back2 = read_elev_balcony(s, "EB2")
    assert back2["kind"] == "AWNING" and back2["slab"] == 120.0, back2

    cases = [
        (lambda: create_elev_balcony(s, "EB1", (0.0, 0.0), 2400.0), "已存在"),
        (lambda: create_elev_balcony(s, "EB3", (0.0, 0.0), 2400.0, kind="CANOPY"), "BALCONY / AWNING"),
        (lambda: create_elev_balcony(s, "EB3", (0.0, 0.0), 0.0), "宽/板厚"),
        (lambda: create_elev_balcony(s, "EB3", (0.0, 0.0), 2400.0, rail=0), "栏板高"),
        (lambda: create_elev_balcony(s, "EB3", (0.0, 0.0), 2400.0, depth=0), "挑出宽"),
    ]
    for fn, want in cases:
        try:
            fn()
        except CadError as e:
            assert want in str(e), (want, e)
        else:
            raise AssertionError("应拒绝：%s" % want)

    q = cli("elev-balcony", str(path), "EB1", "--show=EB1")
    assert q["ok"] and q["kind"] == "BALCONY" and q["rail"] == 1000.0, q
    q = cli("elev-balcony", str(path), "EB2", "--show=EB2")
    assert q["ok"] and q["kind"] == "AWNING" and q["slab"] == 120.0, q

    print("立面阳台/雨篷: 阳台 2400/栏板 1000（2 道尺寸）/ 雨篷 1600×120（1 道）")
    print("PASS test_elev_balcony")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
