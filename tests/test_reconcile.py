"""构件一致性检查 + 无歧义自动收尾验收（v1.0.48）。

验收：房间面积、越界洞口、零长墙、悬空门窗可修；重叠/多候选/尺寸放不下只给建议；
fix 先洞口后房间，任一失败整图回滚。
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
    delete_component,
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

    # 2) 把门窗中心改到墙外：fix 应夹回墙内（保留宽度），不删门窗
    door_h = s.component_handle("AA_OPENING_", "D001")
    s.run([("attedit", {"handle": door_h, "values": {"AA_POS": "7000"}})],
          save=True)
    bad_open = reconcile(s)
    kinds = {it["kind"] for it in bad_open["issues"]}
    assert "opening_outside" in kinds, bad_open["issues"]
    assert not any(it["kind"] == "room_area" for it in bad_open["issues"]), bad_open

    moved = reconcile(s, fix=True)
    assert any(f.get("action") == "move_opening" for f in moved["fixed"]), moved
    assert not any(it["kind"] == "opening_outside" for it in moved["issues"]), moved
    back = s.attributes("AA_OPENING_D001")
    assert abs(float(back["AA_POS"]) - 5500.0) < 1e-6, back

    # 3) 门窗越界 + 房间面积也坏：先夹回洞口，再重建房间，不应整批跳过
    room_h = s.component_handle("AA_ROOM_", "R001")
    s.run([("attedit", {"handle": room_h, "values": {"AA_AREA": "0"}})],
          save=True)
    door_h = s.component_handle("AA_OPENING_", "D001")
    s.run([("attedit", {"handle": door_h, "values": {"AA_POS": "7000"}})],
          save=True)
    both = reconcile(s)
    kinds = {it["kind"] for it in both["issues"]}
    assert {"opening_outside", "room_area"} <= kinds, both["issues"]
    done = reconcile(s, fix=True)
    actions = {f.get("action") for f in done["fixed"]}
    assert {"move_opening", "rebuild_room"} <= actions, done
    assert not done.get("fix_skipped"), done
    assert not any(it["kind"] in ("opening_outside", "room_area")
                   for it in done["issues"]), done

    # 4) 同墙洞口重叠：谁该让位不明确，只给建议，不硬改
    create_opening(s, "D002", "W001", "DOOR", 1000.0, 4500.0,
                   height=2100.0, sill=0.0)
    d2_h = s.component_handle("AA_OPENING_", "D002")
    door_h = s.component_handle("AA_OPENING_", "D001")
    s.run([("attedit", {"handle": door_h, "values": {"AA_POS": "5200"}})],
          save=True)
    overlap = reconcile(s)
    assert any(it["kind"] == "opening_overlap" for it in overlap["issues"]), overlap
    keep = reconcile(s, fix=True)
    assert not keep["fixed"], keep
    assert any(it["suggestion"] for it in keep["suggestions"]), keep.get("suggestions")
    d2 = s.attributes("AA_OPENING_D002")
    assert abs(float(d2["AA_POS"]) - 4500.0) < 1e-6, d2

    # 5) 零长墙：无门窗、无房间引用时自动删除；有门窗时只建议
    edge = OUT / "test_reconcile_edges.dxf"
    edge.unlink(missing_ok=True)
    e = Session(edge)
    e.new_metric()
    set_drawing_scale(e, 100, rescale=False)
    create_wall(e, "W100", (0.0, 0.0), (1000.0, 0.0), thick=240.0)
    w100_h = e.component_handle("AA_WALL_", "W100")
    e.run([("attedit", {"handle": w100_h, "values": {"AA_LEN": "0"}})],
          save=True)
    z = reconcile(e, fix=True)
    assert any(f.get("action") == "delete_wall" for f in z["fixed"]), z
    assert z["components"]["walls"] == 0, z

    create_wall(e, "W200", (0.0, 3000.0), (6000.0, 3000.0), thick=240.0)
    create_opening(e, "D200", "W200", "DOOR", 1000.0, 1000.0,
                   height=2100.0, sill=0.0)
    w200_h = e.component_handle("AA_WALL_", "W200")
    e.run([("attedit", {"handle": w200_h, "values": {"AA_LEN": "0"}})],
          save=True)
    z2 = reconcile(e, fix=True)
    assert not z2["fixed"], z2
    assert z2["components"]["walls"] == 1, z2
    assert any(it["kind"] == "wall_zero_len" and it["suggestion"] for it in z2["suggestions"]), z2

    # 6) 悬空门窗：唯一同向、同起点的墙可挂时自动重挂；多个候选不硬改
    hop = OUT / "test_reconcile_host.dxf"
    hop.unlink(missing_ok=True)
    h = Session(hop)
    h.new_metric()
    set_drawing_scale(h, 100, rescale=False)
    create_wall(h, "W300", (0.0, 0.0), (6000.0, 0.0), thick=240.0)
    create_opening(h, "D300", "W300", "DOOR", 1000.0, 1000.0,
                   height=2100.0, sill=0.0)
    delete_component(h, "AA_WALL_W300")
    create_wall(h, "W301", (0.0, 0.0), (6000.0, 0.0), thick=240.0)
    orphan = reconcile(h)
    assert any(it["kind"] == "opening_orphan" and it["fixable"]
               for it in orphan["issues"]), orphan
    healed = reconcile(h, fix=True)
    assert any(f.get("action") == "rehost_opening" for f in healed["fixed"]), healed
    assert not any(it["kind"] == "opening_orphan" for it in healed["issues"]), healed
    attr = h.attributes("AA_OPENING_D300")
    assert attr["AA_WALLID"] == "W301", attr

    # 7) 洞口比墙还长：放不下，只建议
    d300_h = h.component_handle("AA_OPENING_", "D300")
    h.run([("attedit", {"handle": d300_h, "values": {"AA_WIDTH": "7000"}})],
          save=True)
    too_wide = reconcile(h, fix=True)
    assert not too_wide["fixed"], too_wide
    assert any(it["kind"] == "opening_outside" and "洞口比墙还长" in it["suggestion"]
               for it in too_wide["suggestions"]), too_wide

    path.unlink(missing_ok=True)
    edge.unlink(missing_ok=True)
    hop.unlink(missing_ok=True)
    print("PASS test_reconcile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
