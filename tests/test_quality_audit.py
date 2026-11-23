"""图面质量门禁（v1.0.57）：图签压线 / 幅面利用率 / 施工说明术语。

这些是**警告**，不进 issues/count，避免老图被判失败；但让"规范不规范"变成可测量指标。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import Session, audit, create_sheet, create_text  # noqa: E402

OUT = ROOT / "samples"
PATH = OUT / "test_quality_audit.dxf"


def main() -> int:
    s = Session(PATH)
    s.new_metric(scale=100)
    create_sheet(s, "SHQ", "A4", at=(0.0, 0.0))
    # 一条线穿过 A4 图签（内框 x 2500..29200，图签 x 11200..29200, y 500..6100）
    s.lisp('(progn (aa:mkline (list 12000.0 3000.0) (list 28000.0 3000.0) "AA-WALL") (princ "ok"))',
           libraries=("aa_core.lisp",))
    create_text(s, "J1", (3000.0, 12000.0), "洞口定位见 AA_POS；面积按鞋带公式计算",
                height=2.5, scale=100)

    d = audit(s)
    assert d["count"] == 0, d["issues"]           # 警告不能变成 error
    kinds = {w["kind"] for w in d["warnings"]}
    assert "title_block_overlap" in kinds, d["warnings"]
    assert "internal_jargon" in kinds, d["warnings"]
    assert 0.0 <= d["quality"]["occupancy"] <= 1.0, d["quality"]
    assert d["warning_count"] == len(d["warnings"]) >= 2, d
    print("质量警告:", [(w["kind"], w["message"]) for w in d["warnings"]],
          "occupancy", d["quality"]["occupancy"])

    # CLI 也要带出 warnings / warning_count，供汇总报告用
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "aa_cmd.py"),
                        "audit", str(PATH)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr or r.stdout
    cli = json.loads(r.stdout)
    assert cli["warning_count"] == d["warning_count"], cli
    assert cli["quality"]["checks"] == 3, cli
    print("CLI 质量字段 ok:", cli["warning_count"], cli["quality"])

    # 修补后的幼儿园交付图：程序问题 0、质量警告 0（S 级三项已修）
    for i in range(0, 6):
        stem = ("00_总平面索引" if i == 0 else
                "%02d_%s层平面图" % (i, "一二三四五"[i - 1]))
        f = ROOT / "deliverables" / "幼儿园教学楼" / (stem + ".dxf")
        d = audit(Session(f))
        assert d["count"] == 0, (stem, d["issues"])
        assert d["warning_count"] == 0, (stem, d["warnings"])
    print("交付集 00–05：程序问题 0 / 质量警告 0")

    print("PASS test_quality_audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
