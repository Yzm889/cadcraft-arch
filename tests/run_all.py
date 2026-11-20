"""顺序跑全部验收测试，任一失败即中止。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ["test_axis.py", "test_axis_auto.py", "test_wall.py", "test_opening.py", "test_openings.py", "test_dim.py", "test_label.py", "test_sheet.py", "test_room.py",
         "test_corner.py", "test_layers.py", "test_layer_style.py", "test_split.py", "test_merge.py",
         "test_modify.py", "test_room_auto.py", "test_room_modify.py", "test_symbols.py", "test_scale.py", "test_scale_pre.py", "test_mcp.py"]


def main() -> int:
    failed = []
    for t in TESTS:
        print("=" * 56)
        print("RUN", t)
        p = subprocess.run([sys.executable, str(ROOT / t)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(p.stdout.strip()[-1200:])
        if p.returncode != 0:
            print(p.stderr.strip()[-800:])
            failed.append(t)
    print("=" * 56)
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("ALL PASS (%d tests)" % len(TESTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

