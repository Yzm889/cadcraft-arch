"""卫生间大样验收（v1.0.38）：默认布置 + 自定义净空/地漏。

验收：1:20 → 5 倍；墙带/坐便/台盆/地漏/排水坡齐备；开间/进深/坐便中距三道尺寸；
bbox 与几何口径一致；属性回读（净宽/净深/墙厚/洁具/地漏/坡度/倍数/比例）；
重号、净宽 0、比例 0、倍数 0、坡度 0、地漏越界六类拒绝；CLI --show 与库一致。
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
    create_wc_detail,
    read_wc_detail,
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
    path = OUT / "test_wc_detail.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    wc = create_wc_detail(s, "WC1", (0.0, 0.0))
    assert wc["factor"] == 5.0 and wc["dims"] == 3, wc
    assert wc["width"] == 2400.0 and wc["depth"] == 1800.0, wc
    assert wc["wall"] == 120.0 and wc["slope"] == 1.0, wc
    assert wc["drain"] == [2100.0, 300.0], wc
    assert wc["ratio"] == "1:20" and wc["title"] == "卫生间大样", wc
    assert wc["bbox"] == [-3600.0, -3600.0, 14400.0, 11200.0], wc["bbox"]

    wc2 = create_wc_detail(s, "WC2", (9000.0, 0.0), width=2000.0, depth=2200.0,
                           wall=100.0, slope=2.0, drain=(1800.0, 400.0))
    assert wc2["factor"] == 5.0 and wc2["dims"] == 3, wc2
    assert wc2["width"] == 2000.0 and wc2["depth"] == 2200.0, wc2
    assert wc2["drain"] == [1800.0, 400.0] and wc2["slope"] == 2.0, wc2
    assert wc2["bbox"] == [-3500.0, -3500.0, 12300.0, 13100.0], wc2["bbox"]

    back = read_wc_detail(s, "WC1")
    assert back["width"] == 2400.0 and back["depth"] == 1800.0, back
    assert back["toilet"] == "400x700" and back["basin"] == "450x600", back
    assert back["drain"] == [2100.0, 300.0] and back["slope"] == 1.0, back
    back2 = read_wc_detail(s, "WC2")
    assert back2["wall"] == 100.0 and back2["slope"] == 2.0, back2

    cases = [
        (lambda: create_wc_detail(s, "WC1", (0.0, 0.0)), "已存在"),
        (lambda: create_wc_detail(s, "WC3", (0.0, 0.0), width=0), "净宽"),
        (lambda: create_wc_detail(s, "WC3", (0.0, 0.0), ratio=0), "比例"),
        (lambda: create_wc_detail(s, "WC3", (0.0, 0.0), factor=0), "倍数"),
        (lambda: create_wc_detail(s, "WC3", (0.0, 0.0), slope=0), "坡度"),
        (lambda: create_wc_detail(s, "WC3", (0.0, 0.0), drain=(3000.0, 300.0)), "净空之外"),
    ]
    for fn, want in cases:
        try:
            fn()
        except CadError as e:
            assert want in str(e), (want, e)
        else:
            raise AssertionError("应拒绝：%s" % want)

    q = cli("wc-detail", str(path), "WC1", "--show=WC1")
    assert q["ok"] and q["width"] == 2400.0 and q["drain"] == [2100.0, 300.0], q
    q = cli("wc-detail", str(path), "WC2", "--show=WC2")
    assert q["ok"] and q["depth"] == 2200.0 and q["slope"] == 2.0, q

    print("卫生间大样: 2400×1800（坐便/台盆/地漏/1% 坡，3 道尺寸）；2000×2200 自定义通过")
    print("PASS test_wc_detail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
