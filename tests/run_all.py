"""顺序跑全部验收测试，任一失败即中止。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# 自动收集 tests/test_*.py，避免新加测试忘了挂进回归清单。
TESTS = sorted(p.name for p in ROOT.glob("test_*.py"))


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

