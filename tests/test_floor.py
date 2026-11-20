"""楼层表验收（v1.0.14，B6 第一项）。

要点：
  · 三层楼：标高自动累加（±0.000 / 3.600 / 7.200），层高 3600/3600/3300
  · 表落成 AA_TABLE_<编号> 块，AA_TYPE 改成 FLOOR_TABLE，表体数据可回读
  · read_floors 把表反解成结构化楼层，供立面/剖面用
  · 层高 <=0、标高不递增、编号重复 都要拒绝
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    create_floor_table,
    read_floors,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_floor.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()

    floors = [
        {"no": "1", "height": 3600.0, "plan": "建施-01", "name": "首层"},
        {"no": "2", "height": 3600.0, "plan": "建施-02", "name": "二层"},
        {"no": "3", "height": 3300.0, "plan": "建施-03", "name": "三层"},
    ]
    res = create_floor_table(s, "FC1", (0.0, 0.0), floors)
    assert res["count"] == 3, res
    assert abs(res["total_height"] - 10500.0) < 1e-6, res
    assert abs(res["top_elev"] - 7200.0) < 1e-6, res

    attrs = s.attributes("AA_TABLE_FC1")
    assert attrs["AA_TYPE"] == "FLOOR_TABLE", attrs
    assert "楼层标高" in attrs["AA_HEADER"], attrs
    rows = [r.split("~") for r in attrs["AA_ROWS"].split("@@")]
    assert rows[0][1] == "±0.000" and rows[1][1] == "3.600" and rows[2][1] == "7.200", rows

    back = read_floors(s, "FC1")
    assert [f["no"] for f in back] == ["1", "2", "3"], back
    assert [round(f["elev"]) for f in back] == [0, 3600, 7200], back
    assert [round(f["height"]) for f in back] == [3600, 3600, 3300], back
    assert back[0]["plan"] == "建施-01" and back[2]["name"] == "三层", back

    # 显式标高覆盖自动累加
    res2 = create_floor_table(s, "FC2", (3000.0, 0.0),
                              [{"no": "-1", "height": 3600.0, "elev": -3600.0,
                                "plan": "建施-00", "name": "地下一层"}])
    assert abs(res2["top_elev"] + 3600.0) < 1e-6, res2

    # 拒绝：层高 <= 0
    for bad in (0.0, -100.0):
        try:
            create_floor_table(s, "FCX", (0.0, 0.0),
                               [{"no": "1", "height": bad}])
        except CadError as e:
            assert "层高必须大于 0" in str(e), e
        else:
            raise AssertionError("层高 %s 应被拒绝" % bad)

    # 拒绝：标高不递增
    try:
        create_floor_table(s, "FCY", (0.0, 0.0),
                           [{"no": "1", "height": 3600.0},
                            {"no": "2", "height": 3600.0, "elev": 1800.0}])
    except CadError as e:
        assert "低于下一层顶" in str(e), e
    else:
        raise AssertionError("标高不递增应被拒绝")

    # 拒绝：编号重复
    try:
        create_floor_table(s, "FC1", (0.0, 0.0), floors)
    except CadError as e:
        assert "已存在" in str(e), e
    else:
        raise AssertionError("重复编号应被拒绝")

    print("楼层表: 3 层 3600/3600/3300，总高 10500，顶标高 7.200")
    print("PASS test_floor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
