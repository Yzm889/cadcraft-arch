"""详图验收（v1.0.35）：详图符号 + 门窗大样。

一层平面画 C1515（窗）与 M0921（门），分别出 1:20 大样：
验收：详图符号圆直径 14mm（1:100 → 1400）；大样放大倍数 = 出图比例/详图比例 = 5，
尺寸注洞口宽高（2 道），图名/比例画在块内，属性可回读；同编号多樘、无参数、
未知编号、比例非法都拒绝；CLI --show 与库回读一致。
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
    create_detail_mark,
    create_opening,
    create_opening_detail,
    create_wall,
    read_detail_mark,
    read_opening_detail,
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
    path = OUT / "test_detail.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    create_wall(s, "W001", (0.0, 0.0), (7200.0, 0.0), thick=240.0)
    create_wall(s, "W002", (0.0, 0.0), (0.0, 4500.0), thick=240.0)
    create_opening(s, "D001", "W001", "WINDOW", width=1500.0, pos=1200.0,
                   height=1500.0, sill=900.0, no="C1515")
    create_opening(s, "D002", "W002", "DOOR", width=900.0, pos=1000.0,
                   height=2100.0, no="M0921")
    # 同编号第二樘，用来验"编号多樘必须指明具体洞口"
    create_opening(s, "D003", "W002", "WINDOW", width=1500.0, pos=2800.0,
                   height=1500.0, sill=900.0, no="C1515")

    # 1) 详图符号：14mm 圆，同图写 —
    mk = create_detail_mark(s, "DM1", (3000.0, 900.0), "1", "—")
    assert len(mk["geom_handles"]) == 4, mk
    assert mk["diameter"] == 1400.0, mk
    back = read_detail_mark(s, "DM1")
    assert back["detail"] == "1" and back["sheetno"] == "—" and back["diameter"] == 1400.0, back

    # 2) 窗大样 1:20 → 放大 5 倍，注宽高两道尺寸
    od = create_opening_detail(s, "OD1", (0.0, -4000.0), "D001", ratio=20)
    assert od["kind"] == "WINDOW" and od["factor"] == 5.0 and od["dims"] == 2, od
    assert od["width"] == 1500.0 and od["height"] == 1500.0, od
    assert od["ratio"] == "1:20" and od["title"] == "C1515 窗大样", od
    assert od["bbox"] == [-2400.0, -3000.0, 8700.0, 9000.0], od["bbox"]
    back = read_opening_detail(s, "OD1")
    assert back["no"] == "C1515" and back["sill"] == 900.0, back
    assert back["factor"] == 5.0 and back["ratio"] == "1:20", back
    assert back["width"] == 1500.0 and back["height"] == 1500.0, back

    # 3) 门大样：同倍放大，双扇（宽 900），无窗台板
    door = create_opening_detail(s, "OD2", (9000.0, -4000.0), "D002", ratio=20)
    assert door["kind"] == "DOOR" and door["no"] == "M0921", door
    assert door["height"] == 2100.0 and door["factor"] == 5.0, door
    assert door["title"] == "M0921 门大样", door
    assert door["bbox"][3] == 2100.0 * 5.0 + 300.0 * 5.0, door["bbox"]

    # 4) 拒绝：重号、无参数、未知编号、同编号多樘、比例非法
    cases = [
        (lambda: create_detail_mark(s, "DM1", (0.0, 0.0), "2"), "已存在"),
        (lambda: create_detail_mark(s, "DM2", (0.0, 0.0), " "), "详图编号"),
        (lambda: create_opening_detail(s, "OD1", (0.0, 0.0), "D001"), "已存在"),
        (lambda: create_opening_detail(s, "OD3", (0.0, -4000.0)), "必须指定"),
        (lambda: create_opening_detail(s, "OD3", (0.0, -4000.0), opening_id="D999"), "没有洞口"),
        (lambda: create_opening_detail(s, "OD3", (0.0, -4000.0), no="C1515"), "多樘"),
        (lambda: create_opening_detail(s, "OD3", (0.0, -4000.0), no="Z999"), "没有编号"),
        (lambda: create_opening_detail(s, "OD3", (0.0, -4000.0), "D001", ratio=0), "比例"),
    ]
    for fn, want in cases:
        try:
            fn()
        except CadError as e:
            assert want in str(e), (want, e)
        else:
            raise AssertionError("应拒绝：%s" % want)

    # 5) CLI --show 与库一致
    q = cli("detail-mark", str(path), "DM1", "--show=DM1")
    assert q["ok"] and q["detail"] == "1" and q["diameter"] == 1400.0, q
    q = cli("opening-detail", str(path), "OD1", "--show=OD1")
    assert q["ok"] and q["factor"] == 5.0 and q["ratio"] == "1:20", q

    print("详图: 符号 14mm；C1515/M0921 大样 5 倍（1:20），宽高 2 道尺寸，属性回读一致")
    print("PASS test_detail")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
