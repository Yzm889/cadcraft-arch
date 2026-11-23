"""版本一致性检查：README「现状」版本必须等于 MCP SERVER_INFO 版本。

不依赖 CADCraft CLI，可直接在 CI 跑：

    python tools/check_version.py

tests/test_mcp.py 复用 version_mismatch()，README 与 SERVER_INFO 漂移时两边都会红。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def readme_version() -> str | None:
    """取 README 第一个「## 现状（vX.Y.Z」标题里的版本号；找不到返回 None。"""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"##\s*现状（v(\d+(?:\.\d+)+)", text)
    return m.group(1) if m else None


def server_version() -> str:
    sys.path.insert(0, str(ROOT / "tools"))
    import aa_mcp  # noqa: E402  延迟导入：只有检查时才需要

    return str(aa_mcp.SERVER_INFO["version"])


def version_mismatch() -> str | None:
    """一致返回 None；否则返回一句人能读的说明。"""
    rv = readme_version()
    sv = server_version()
    if rv is None:
        return "README.md 里找不到「## 现状（vX.Y.Z」标题"
    if rv != sv:
        return "README 现状版本 v%s != MCP SERVER_INFO %s" % (rv, sv)
    return None


def main() -> int:
    msg = version_mismatch()
    if msg:
        print("FAIL check_version:", msg)
        return 1
    print("PASS check_version (v%s)" % server_version())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
