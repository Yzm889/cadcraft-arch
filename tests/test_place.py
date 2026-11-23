"""自动排附表（v1.0.58）：空位搜索、表格塞格、可重复执行。

这一组测的都是"返工率"相关的东西：
  - 空位搜索不能算错格子（贴边的框不许占格，否则贴图签的位置永远放不下）；
  - 表格文字不许出格（缩字或截断，但不能顶到邻列）；
  - 排布要能重复跑（`--replace`），不然调一次位置就多一张表。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session,
    _NON_GRAPHIC_TYPES,
    _piece_box,
    _quality_pieces,
    clear_schedules,
    create_opening,
    create_room,
    create_sheet,
    create_text,
    create_wall,
    draw_table,
    find_free_rect,
    place_schedules,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_find_free_rect() -> None:
    """纯几何：空位搜索的方向、边界与"贴边不算占格"。"""
    inner = (0.0, 0.0, 1000.0, 1000.0)
    assert find_free_rect(inner, [], 200.0, 200.0) == (0.0, 1000.0)

    # 左上角被占 -> 让开（可以往右并排，不必往下退），但不能压在障碍上
    obstacle = (0.0, 900.0, 200.0, 1000.0)
    at = find_free_rect(inner, [obstacle], 200.0, 200.0)
    assert at is not None, at
    assert not overlap((at[0], at[1] - 200.0, at[0] + 200.0, at[1]), obstacle), at

    # 右上优先
    at = find_free_rect(inner, [], 200.0, 200.0, prefer="top-right")
    assert at is not None and at[0] > 700, at

    # 放不下就是 None，不许硬塞
    assert find_free_rect(inner, [], 1200.0, 100.0) is None
    assert find_free_rect(inner, [], 100.0, 1200.0) is None

    # search 子区必须被遵守
    at = find_free_rect(inner, [], 100.0, 100.0, search=(0.0, 0.0, 500.0, 500.0))
    assert at is not None and at[0] <= 500 and at[1] <= 500, at

    # 回归：恰好贴边的占用框不能占格。
    # 图签顶标高正好等于横带底标高，旧版按闭区间算会多标一整行，
    # 结果"贴图签上方"这个最好的位置永远放不下——这就是那时被赶到右上角的原因。
    tight = (0.0, 0.0, 1000.0, 400.0)

    def near(at, want) -> bool:
        return at is not None and abs(at[0] - want[0]) < 1e-6 and abs(at[1] - want[1]) < 1.0

    assert near(find_free_rect(tight, [(0.0, 0.0, 1000.0, 0.0)], 1000.0, 400.0), (0.0, 400.0))
    assert near(find_free_rect(tight, [(1000.0, 0.0, 1000.0, 400.0)], 1000.0, 400.0), (0.0, 400.0))
    # 真占上了就不能给
    assert find_free_rect(tight, [(0.0, 0.0, 1000.0, 5.0)], 1000.0, 400.0) is None
    print("find_free_rect ok")


def test_cell_fit(path: Path) -> None:
    """表格文字必须塞进格子：缩字优先，缩到 70% 还超才截断。"""
    s = Session(path)
    s.new_metric(scale=100)

    ok = draw_table(s, (0.0, 6000.0), "正常表", ["编号", "名称"],
                    [["A1", "门厅"]], [2000.0, 3000.0], table_id="T001")
    assert ok["truncated"] == 0 and ok["shrunk"] == 0, ok

    long = "W001;W003;W005;W007;W009;W011;W013;W015;W017;W019"
    bad = draw_table(s, (0.0, 3000.0), "超长表", ["编号", "所在墙"],
                     [["M1", long]], [2000.0, 3000.0], table_id="T002")
    assert bad["truncated"] >= 1, bad
    assert bad["width"] == 5000.0, bad      # 截断只动字，不动表格尺寸

    # 凡是落在表格框里（或压到框线）的文字，都必须完整落在框内
    box = (0.0, bad["at"][1] - bad["height"], 5000.0, bad["at"][1])
    checked = 0
    for p in _quality_pieces(s):
        if p["type"] not in ("TEXT", "MTEXT"):
            continue
        b = _piece_box(p)
        if not overlap(b, box):
            continue
        checked += 1
        assert b[0] >= box[0] - 1 and b[2] <= box[2] + 1, (b, box)
        assert b[1] >= box[1] - 1 and b[3] <= box[3] + 1, (b, box)
    assert checked >= 4, checked
    print("cell fit ok:", bad["truncated"], "格截断，", checked, "个文字全在框内")


def test_pieces_ignore_attdef(path: Path) -> None:
    """属性定义不能算成图面图元，否则利用率和空位搜索全是假的。"""
    s = Session(path)
    s.new_metric(scale=100)
    create_text(s, "K1", (0.0, 0.0), "洞口定位及编号见门窗表与平面标注", height=2.5, scale=100)

    pieces = [p for p in _quality_pieces(s) if not p.get("frame")]
    assert pieces, "至少要有一块图元"
    assert all(p["type"] not in _NON_GRAPHIC_TYPES for p in pieces), "ATTDEF 混进来了"

    texts = [p for p in pieces if p["type"] == "TEXT" and p["text"].startswith("洞口定位")]
    assert texts, [p["text"][:12] for p in pieces]
    b = _piece_box(texts[0])
    # 16 个汉字，字高 2.5mm@1:100 = 250，宽度必须按字宽算出来，不能退化成点
    assert (b[2] - b[0]) >= 16 * 250 * 0.9, b
    assert (b[3] - b[1]) >= 250, b
    print("pieces ok:", round(b[2] - b[0]), "宽")


def _tiny_floor(s: Session) -> None:
    for wid, p1, p2 in [
        ("W001", (0.0, 0.0), (6000.0, 0.0)),
        ("W002", (6000.0, 0.0), (6000.0, 4800.0)),
        ("W003", (6000.0, 4800.0), (0.0, 4800.0)),
        ("W004", (0.0, 4800.0), (0.0, 0.0)),
    ]:
        create_wall(s, wid, p1, p2, thick=240.0, kind="EXTERNAL")
    create_opening(s, "M1", "W001", "DOOR", width=1000.0, pos=1500.0)
    create_room(s, "R001", ["W001", "W002", "W003", "W004"], name="活动室")


def test_place_and_replace(path: Path) -> None:
    """排布：三样东西都放下、彼此不压、重跑不叠加。"""
    s = Session(path)
    s.new_metric(scale=100)
    _tiny_floor(s)
    create_sheet(s, "SP1", "A2", 100, at=(0.0, 0.0),
                 project="排图测试", drawing="平面图", number="建-99")

    r = place_schedules(s, "auto")
    assert r["sheet"] == "SP1", r          # auto 要能自己认出唯一图幅
    names = {p["item"] for p in r["placed"]}
    assert names == {"门窗表", "房间面积表", "指北针"}, r
    assert r["occupancy_after"] > r["occupancy_before"], r

    boxes = [(p["at"][0], p["at"][1] - p["size"][1],
              p["at"][0] + p["size"][0], p["at"][1]) for p in r["placed"]]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not overlap(boxes[i], boxes[j]), (r["placed"][i], r["placed"][j])

    # 重跑必须幂等：不清场就会 T001/T002 越堆越多
    r2 = place_schedules(s, replace=True)
    assert len(s.components("AA_TABLE_")) == 2, len(s.components("AA_TABLE_"))
    assert len(s.components("AA_SYM_N")) == 1, len(s.components("AA_SYM_N"))
    assert {p["item"] for p in r2["placed"]} == names, r2
    print("place ok:", [(p["item"], p["id"]) for p in r2["placed"]],
          "%.3f -> %.3f" % (r["occupancy_before"], r["occupancy_after"]))


def test_clear_keeps_other_tables(path: Path) -> None:
    """清场只清附表，别把图纸目录/楼层表一起删了。"""
    s = Session(path)
    s.new_metric(scale=100)
    _tiny_floor(s)
    create_sheet(s, "SP2", "A3", 100, at=(0.0, 0.0))
    place_schedules(s, "auto")
    draw_table(s, (30000.0, 20000.0), "图纸目录", ["图号", "图名"],
               [["建-01", "一层"]], [3000.0, 5000.0], table_id="TDIR")

    removed = clear_schedules(s)
    assert len(removed) == 3, removed
    left = [c["geometry"]["block"] for c in s.components("AA_TABLE_")]
    assert left == ["AA_TABLE_TDIR"], left
    print("clear ok:", removed)


def test_cli(path: Path) -> None:
    """CLI `place`：不给 --sheet 也要能自己认出图幅，且 --replace 可重复跑。"""
    import json
    import subprocess

    s = Session(path)
    s.new_metric(scale=100)
    _tiny_floor(s)
    create_sheet(s, "SC1", "A2", 100, at=(0.0, 0.0))

    cmd = [sys.executable, str(ROOT / "tools" / "aa_cmd.py"), "place", str(path)]
    for extra in ([], ["--replace"]):
        r = subprocess.run(cmd + extra, capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr or r.stdout
        d = json.loads(r.stdout)
        assert d["ok"] and d["sheet"] == "SC1", d
        assert {p["item"] for p in d["placed"]} == {"门窗表", "房间面积表", "指北针"}, d
        assert d["occupancy_after"] >= d["occupancy_before"], d
    assert len(s.components("AA_TABLE_")) == 2, "CLI 重跑不许堆表"
    print("cli ok:", [p["item"] for p in d["placed"]])


def main() -> int:
    test_find_free_rect()
    test_cell_fit(OUT / "test_place_cell.dxf")
    test_pieces_ignore_attdef(OUT / "test_place_pieces.dxf")
    test_place_and_replace(OUT / "test_place.dxf")
    test_clear_keeps_other_tables(OUT / "test_place_clear.dxf")
    test_cli(OUT / "test_place_cli.dxf")
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
