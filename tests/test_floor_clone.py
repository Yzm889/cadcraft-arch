"""标准层复制回归：2F 模板 -> 3F/5F，不允许逐层重画。

验收：
  · 复制前后的模板字节不变；
  · 复制层墙/门窗/房间数量与 2F 一致；
  · 复制后墙 AA_FLOOR 改为目标层，所有 AA_ID 不再带 F2 前缀；
  · 复制层自身 12 条验收全过，门窗编号无碰撞。
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "deliverables" / "幼儿园教学楼"))

import clone_standard  # noqa: E402
from aa_lib import Session, opening_data, room_data, wall_data  # noqa: E402

WORK = ROOT / "samples" / "_clone_test"
TEMPLATE = ROOT / "deliverables" / "幼儿园教学楼" / "02_二层平面图.dxf"


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def check_floor(no: int, source_counts: dict[str, int]) -> None:
    dxf = WORK / ("%02d_%s层平面图.dxf" % (no, "二三四五"[no - 2]))
    assert dxf.exists(), dxf
    s = Session(dxf)
    walls, rooms, ops = wall_data(s), room_data(s), opening_data(s)
    assert len(walls) == source_counts["walls"], (no, len(walls))
    assert len(rooms) == source_counts["rooms"], (no, len(rooms))
    assert len(ops) == source_counts["openings"], (no, len(ops))
    assert all(w["floor"] == no for w in walls), (no, [w["floor"] for w in walls])
    assert all(w["id"].startswith("F%d" % no) for w in walls), (no, [w["id"] for w in walls])
    assert all(r["id"].startswith("F%d" % no) for r in rooms), (no, [r["id"] for r in rooms])
    assert all(o["id"].startswith("F%d" % no) for o in ops), (no, [o["id"] for o in ops])
    for e in s.components("AA_"):
        a = {x["tag"]: x.get("text", {}).get("value", "")
             for x in e["geometry"].get("attribs", [])}
        aid = a.get("AA_ID", "")
        assert not aid.startswith("F2"), (no, e["geometry"]["block"], aid)
        for key in ("AA_WALLID", "AA_ROOT", "AA_WALLS"):
            assert "F2" not in a.get(key, ""), (no, e["geometry"]["block"], key, a[key])


def main() -> int:
    assert TEMPLATE.exists(), TEMPLATE
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    source = WORK / "02_二层平面图.dxf"
    shutil.copy2(TEMPLATE, source)
    before = sha1(source)

    s0 = Session(source)
    source_counts = {"walls": len(wall_data(s0)),
                     "rooms": len(room_data(s0)),
                     "openings": len(opening_data(s0))}

    old_out, old_source = clone_standard.OUT, clone_standard.SOURCE
    clone_standard.OUT, clone_standard.SOURCE = WORK, source
    try:
        for no in (3, 5):
            snap = clone_standard.clone_floor(no)
            assert not snap["errors"], snap["errors"]
            assert all(c["ok"] for c in snap["checks"]), snap["checks"]
            assert not snap["label_avoid"]["collisions"], snap["label_avoid"]
            check_floor(no, source_counts)
    finally:
        clone_standard.OUT, clone_standard.SOURCE = old_out, old_source

    assert sha1(source) == before, "复制过程改动了 2F 模板"
    shutil.rmtree(WORK, ignore_errors=True)
    print("PASS test_floor_clone: 2F -> 3F/5F，墙 %d / 房 %d / 门窗 %d，模板未变"
          % (source_counts["walls"], source_counts["rooms"], source_counts["openings"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
