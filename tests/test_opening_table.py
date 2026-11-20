"""门窗表验收（v1.0.32）：从平面 AA_OPENING 自动统计 + 回读。

要点：
  · 同一编号同尺寸归一行，樘数是图上真实数量，所在层取洞口所在墙的 AA_FLOOR
  · 跨层同编号写 "1-3"；不连续写 "1,3"
  · 表落 AA_TABLE_<编号>，AA_TYPE=OPENING_TABLE，AA_ROWS 可回读
  · 没有洞口时拒绝空表；重复编号拒绝
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    LAYERS,
    CadError,
    Session,
    block_geometry,
    create_opening,
    create_opening_table,
    create_wall,
    opening_data,
    opening_summary,
    read_opening_table,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_opening_table.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()

    # 三层：南墙各一道（一层 M0921 + C1215，二层同尺寸 C1215，三层 C0915）+ 北墙一层 M0921
    # 三层楼层各画在一条水平线上，避免"同位置重复墙"被识别成同一条逻辑墙
    for fl, wy in ((1, 0.0), (2, 3000.0), (3, 6000.0)):
        create_wall(s, "S%d" % fl, (0.0, wy), (6000.0, wy), thick=240.0,
                    kind="EXTERNAL", floor=fl)
    create_wall(s, "N1", (0.0, -3000.0), (6000.0, -3000.0), thick=240.0,
                kind="EXTERNAL", floor=1)

    create_opening(s, "D1", "S1", "DOOR", width=900.0, pos=1050.0, height=2100.0)
    create_opening(s, "W1", "S1", "WINDOW", width=1200.0, pos=5000.0,
                   height=1500.0, sill=900.0)
    create_opening(s, "W2", "S2", "WINDOW", width=1200.0, pos=5000.0,
                   height=1500.0, sill=900.0)
    create_opening(s, "W3", "S3", "WINDOW", width=900.0, pos=5000.0,
                   height=1500.0, sill=1500.0)
    create_opening(s, "D2", "N1", "DOOR", width=900.0, pos=1050.0, height=2100.0)

    data = opening_data(s)
    assert len(data) == 5, len(data)
    assert [o["floor"] for o in data] == [1, 1, 2, 3, 1], [o["floor"] for o in data]

    summary = opening_summary(s)
    # M0921 两樘（都在一层）→ 一行；C1215 两樘（1、2 层）→ 一行，所在层 "1-2"
    assert len(summary) == 3, summary
    door = next(x for x in summary if x["no"] == "M0921")
    assert door["count"] == 2 and door["level_text"] == "1", door
    win = next(x for x in summary if x["no"] == "C1215")
    assert win["count"] == 2 and win["level_text"] == "1-2", win
    small = next(x for x in summary if x["no"] == "C0915")
    assert small["count"] == 1 and small["level_text"] == "3", small

    res = create_opening_table(s, "MC1", (0.0, -2600.0))
    assert res["count"] == 3 and res["total"] == 5, res

    g = block_geometry(path, "AA_TABLE_MC1")
    texts = [x for x in g if x["type"] == "TEXT"]
    got = [x["text"] for x in texts]
    for want in ("门窗表", "门窗编号", "洞口尺寸(宽×高)", "樘数", "所在层", "M0921", "C1215", "C0915"):
        assert want in got, (want, got)
    assert "900×2100" in got and "1200×1500" in got, got
    assert "1-2" in got and "1,2" not in got, got

    back = read_opening_table(s, "MC1")
    assert len(back) == 3, back
    m = next(x for x in back if x["no"] == "M0921")
    assert m["kind"] == "门" and m["width"] == 900.0 and m["height"] == 2100.0, m
    assert m["count"] == 2 and m["levels"] == [1] and m["sill"] == 0.0, m
    c = next(x for x in back if x["no"] == "C1215")
    assert c["sill"] == 900.0 and c["levels"] == [1, 2], c

    # 再画一张空表会重名，必须拒绝
    try:
        create_opening_table(s, "MC1", (0.0, -6000.0))
    except CadError as e:
        assert "已存在" in str(e), e
    else:
        raise AssertionError("重复编号应被拒绝")

    # 层号非法拒绝
    try:
        create_wall(s, "X1", (0.0, -1000.0), (3000.0, -1000.0), floor=0)
    except CadError as e:
        assert "层号" in str(e), e
    else:
        raise AssertionError("层号 0 应被拒绝")

    # 没有洞口时拒绝空表（新图）
    p2 = OUT / "test_opening_table_empty.dxf"
    p2.unlink(missing_ok=True)
    s2 = Session(p2)
    s2.new_metric()
    try:
        create_opening_table(s2, "MC2", (0.0, 0.0))
    except CadError as e:
        assert "空的门窗表" in str(e), e
    else:
        raise AssertionError("没有洞口应拒绝")

    assert LAYERS["table"] in [x.get("layer") for x in g], g

    # CLI 回读口径与库口径一致（--show 只读、不回写）
    ro = subprocess.run([sys.executable, str(ROOT / "tools" / "aa_cmd.py"),
                         "opening-table", str(path), "MC1", "--show=MC1"],
                        capture_output=True, text=True, encoding="utf-8")
    assert ro.returncode == 0, ro.stdout + ro.stderr
    cli = json.loads(ro.stdout.strip().splitlines()[-1])
    assert cli["ok"] and len(cli["rows"]) == 3, cli
    assert sorted(r["no"] for r in cli["rows"]) == ["C0915", "C1215", "M0921"], cli
    win_row = next(r for r in cli["rows"] if r["no"] == "C1215")
    assert win_row["level_text"] == "1-2" and win_row["count"] == 2, cli
    print("门窗表: 3 行 / 5 樘 / M0921 2 樘(1 层) / C1215 2 樘(1,2 层) / C0915 1 樘(3 层)")
    print("PASS test_opening_table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
