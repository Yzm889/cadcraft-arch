"""参数变更重绘验收测试：改墙厚/改门窗位置后，洞口与墙线必须同步重建，拒绝时零残留。"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    block_geometry,
    create_opening,
    create_wall,
    normalize_around,
    opening_data,
    set_opening,
    set_wall,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def side_spans(path, block):
    return sorted({(round(min(q[0] for q in g["pts"]), 1), round(max(q[0] for q in g["pts"]), 1),
                    round(g["pts"][0][1], 1))
                   for g in block_geometry(path, block) if g["type"] == "LINE"})


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    path = OUT / "test_modify.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()
    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_opening(s, "D001", "W001", "DOOR", width=900.0, pos=2000.0)

    # 1) 改墙厚 240 -> 360：墙线间距、洞口边线长度、洞口缺口都要跟着变
    r = set_wall(s, "W001", 360.0, kind="INTERNAL")
    print("set_wall:", {k: r[k] for k in ("wall", "thick", "kind", "openings_rebuilt")})
    attrs = s.attributes("AA_WALL_W001")
    assert attrs["AA_THICK"] == "360.0000", attrs
    assert attrs["AA_KIND"] == "INTERNAL", attrs

    spans = side_spans(path, "AA_WALL_W001")
    print("wall spans:", spans)
    assert spans == [(0.0, 1550.0, -180.0), (0.0, 1550.0, 180.0),
                     (2450.0, 6000.0, -180.0), (2450.0, 6000.0, 180.0)], spans

    # 洞口边线（两条竖直线，长度=墙厚）必须跟着新墙厚变长；门扇线仍是洞宽
    jamb = [g for g in block_geometry(path, "AA_OPENING_D001")
            if g["type"] == "LINE" and abs(g["pts"][0][0] - g["pts"][1][0]) < 1e-6]
    jamb_len = [abs(g["pts"][0][1] - g["pts"][1][1]) for g in jamb]
    print("opening vertical lines:", jamb_len)
    assert len([L for L in jamb_len if abs(L - 360.0) < 1e-4]) == 2, jamb_len
    assert len([L for L in jamb_len if abs(L - 900.0) < 1e-4]) == 1, jamb_len

    # 2) 拒绝：墙厚为 0 => 一个字节都不改
    before = digest(path)
    try:
        set_wall(s, "W001", 0.0)
        raise AssertionError("墙厚 0 必须被拒绝")
    except CadError as e:
        print("  拒绝改墙厚 ok:", e)
    assert digest(path) == before, "拒绝时不得改动文件"

    # 3) 改门窗位置与宽度：洞口缺口跟着走
    r2 = set_opening(s, "D001", pos=3000.0, width=1200.0)
    print("set_opening:", r2)
    od = opening_data(s)
    assert abs(od[0]["pos"] - 3000.0) < 1e-6 and abs(od[0]["width"] - 1200.0) < 1e-6, od

    spans2 = side_spans(path, "AA_WALL_W001")
    assert spans2 == [(0.0, 2400.0, -180.0), (0.0, 2400.0, 180.0),
                      (3600.0, 6000.0, -180.0), (3600.0, 6000.0, 180.0)], spans2

    # 4) 拒绝：把洞口挪出墙外 / 与同墙洞口重叠 => 零残留
    create_opening(s, "D002", "W001", "DOOR", width=900.0, pos=5200.0)
    before = digest(path)
    try:
        set_opening(s, "D001", pos=5500.0, width=1200.0)
        raise AssertionError("越界洞口必须被拒绝")
    except CadError as e:
        print("  拒绝越界 ok:", e)
    try:
        set_opening(s, "D001", pos=4900.0, width=1200.0)
        raise AssertionError("重叠洞口必须被拒绝")
    except CadError as e:
        print("  拒绝重叠 ok:", e)
    assert digest(path) == before, "拒绝时不得改动文件"
    assert {o["id"] for o in opening_data(s)} == {"D001", "D002"}, opening_data(s)

    # 5) 幂等：同样的参数再来一次，结果不变
    before3 = side_spans(path, "AA_WALL_W001")
    r3 = set_wall(s, "W001", 360.0)
    spans3 = side_spans(path, "AA_WALL_W001")
    assert spans3 == before3, (spans3, before3)
    print("idempotent ok:", r3["thick"])

    # 6) 邻墙联动：改一堵墙的厚度，邻墙的裁剪边界必须跟着移动
    path2 = OUT / "test_modify_corner.dxf"
    if path2.exists():
        path2.unlink()
    s2 = Session(path2)
    s2.new_metric()
    create_wall(s2, "W001", (0.0, 0.0), (4000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s2, "W002", (4000.0, 0.0), (4000.0, 3000.0), thick=120.0, kind="PARTITION")
    normalize_around(s2, "W002")      # 与 CLI 一致：画完墙立即规整一圈
    before4 = side_spans(path2, "AA_WALL_W001")
    print("邻墙 120 厚时 W001 跨线:", before4)
    # 内墙面止于邻墙内表面 4000-60=3940；外墙面按合角补到外表面 4000+60=4060
    assert (0.0, 3940.0, 120.0) in before4, before4
    assert (0.0, 4060.0, -120.0) in before4, before4

    set_wall(s2, "W002", 300.0)
    after4 = side_spans(path2, "AA_WALL_W001")
    print("邻墙 300 厚时 W001 跨线:", after4)
    # 邻墙变厚，内墙面随之内缩到 4000-150=3850，外墙面补到 4000+150=4150
    assert (0.0, 3850.0, 120.0) in after4, after4
    assert (0.0, 4150.0, -120.0) in after4, after4

    print("PASS test_modify")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
