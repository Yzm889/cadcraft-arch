"""改图事务回滚：CLI/校验中途失败时按内存字节恢复，不依赖 .bak。"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_lib  # noqa: E402
from aa_lib import Session, opening_data, room_data, set_opening, set_room  # noqa: E402

WORK = ROOT / "samples" / "_txn_test.dxf"
SOURCE = ROOT / "samples" / "demo_building.dxf"


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main() -> int:
    shutil.copy2(SOURCE, WORK)
    before = sha1(WORK)
    s = Session(WORK)

    # 1. 房间改名：删掉旧块后重建失败 -> 必须恢复原字节
    old_store = aa_lib._store_room
    def fail_store(*a, **k):
        raise aa_lib.CadError("模拟房间重建失败")
    aa_lib._store_room = fail_store
    try:
        room = room_data(s)[0]
        try:
            set_room(s, room["id"], "事务测试")
        except aa_lib.CadError as exc:
            assert "模拟房间重建失败" in str(exc), exc
        else:
            raise AssertionError("set_room 应该失败")
    finally:
        aa_lib._store_room = old_store
    assert sha1(WORK) == before, "set_room 失败后图纸字节没有恢复"
    # 只看本次工作文件的残留；samples/ 里其它测试的历史 .bak 与本用例无关。
    assert not WORK.with_name(WORK.name + ".restore.tmp").exists(), "回滚临时文件残留"
    assert not WORK.with_name(WORK.stem + ".bak.dxf").exists(), "本用例不应产生 .bak.dxf"

    # 2. 门窗修改：删掉旧块后重建失败 -> 同样必须恢复原字节
    old_create = aa_lib.create_opening
    def fail_create(*a, **k):
        raise aa_lib.CadError("模拟门窗重建失败")
    aa_lib.create_opening = fail_create
    try:
        opening = opening_data(s)[0]
        try:
            set_opening(s, opening["id"])
        except aa_lib.CadError as exc:
            assert "模拟门窗重建失败" in str(exc), exc
        else:
            raise AssertionError("set_opening 应该失败")
    finally:
        aa_lib.create_opening = old_create
    assert sha1(WORK) == before, "set_opening 失败后图纸字节没有恢复"

    WORK.unlink(missing_ok=True)
    print("PASS test_transaction: 房间/门窗失败均按内存字节回滚，无 .bak 依赖")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
