"""构件一致性检查 + 房间面积修复验收（v1.0.43）。

验收：房间面积被改坏后能报出 `room_area`；`fix=True` 按当前墙环重建并恢复面积；
门窗位置越界能报 `opening_outside`，修复不会误删门窗。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    create_opening,
    create_room,
    create_wall,
    reconcile,
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
    path = OUT / "test_reconcile.dxf"
    path.unlink(missing_ok=True)

    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0)
    create_wall(s, "W002", (6000.0, 0.0), (6000.0, 4000.0), thick=240.0)
    create_wall(s, "W003", (6000.0, 4000.0), (0.0, 4000.0), thick=240.0)
    create_wall(s, "W004", (0.0, 4000.0), (0.0, 0.0), thick=240.0)
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="教室")
    create_opening(s, "D001", "W001", "DOOR", 1000.0, 1200.0,
                   height=2100.0, sill=0.0)

    clean = reconcile(s)
    assert clean["components"] == {"walls": 4, "openings": 1, "rooms": 1}, clean
    assert clean["count"] == 0, clean["issues"]

    # CLI 侧同样能查（干净图纸应 0 问题）
    q = cli("reconcile", str(path))
    assert q["ok"] and q["count"] == 0, q

    # 1) 把房间面积改坏，应报 room_area，且可 fix
    room_h = s.component_handle("AA_ROOM_", "R001")
    s.run([("attedit", {"handle": room_h, "values": {"AA_AREA": "0"}})],
          save=True)
    bad = reconcile(s)
    assert any(it["kind"] == "room_area" and it["fixable"] for it in bad["issues"]), bad

    fixed = reconcile(s, fix=True)
    assert fixed["fixed"], fixed
    assert not any(it["kind"] == "room_area" for it in fixed["issues"]), fixed
    back = s.attributes("AA_ROOM_R001")
    assert abs(float(back["AA_AREA"]) - 5760.0 * 3760.0) < 1.0, back

    # 2) 把门窗中心改到墙外，应报 opening_outside；房间面积仍正确
    door_h = s.component_handle("AA_OPENING_", "D001")
    s.run([("attedit", {"handle": door_h, "values": {"AA_POS": "7000"}})],
          save=True)
    bad_open = reconcile(s)
    kinds = {it["kind"] for it in bad_open["issues"]}
    assert "opening_outside" in kinds, bad_open["issues"]
    assert not any(it["kind"] == "room_area" for it in bad_open["issues"]), bad_open

    # 3) 门窗坏 + 房间面积也坏时，fix 不应硬重建房间而把整图炸掉；应如实跳过
    room_h = s.component_handle("AA_ROOM_", "R001")
    s.run([("attedit", {"handle": room_h, "values": {"AA_AREA": "0"}})],
          save=True)
    both = reconcile(s)
    kinds = {it["kind"] for it in both["issues"]}
    assert {"opening_outside", "room_area"} <= kinds, both["issues"]
    skipped = reconcile(s, fix=True)
    assert skipped["fix_skipped"] and not skipped["fixed"], skipped
    assert not skipped["rolled_back"], skipped

    print("PASS test_reconcile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
