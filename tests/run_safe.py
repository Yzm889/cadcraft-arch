#!/usr/bin/env python3
"""CADCraft 低内存回归：一次只跑一个测试，并在 Windows Job Object 里给测试树设内存硬上限。

为什么不用 tests/run_all.py：
- run_all 会把每个用例再包一层子进程和管道；桌面进程（dwm/explorer）和测试争提交内存。
- 本脚本在每个用例开始前读 Windows 的“可提交内存”，低于阈值直接停；每个用例单独起进程，
  利用 Job Object 把测试进程及其 cadcraft-cli 子进程一起限制在 --job-mb 内，超限只杀测试树，
  不会把桌面拖黑。

只支持 Windows；在 Linux/macOS 上只提供 --list。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = sorted((ROOT / "tests").glob("test_*.py"))


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def win_memory() -> dict[str, int]:
    """返回 MB。ullAvailPageFile 是当前可提交额度，不是物理内存。"""
    if os.name != "nt":
        return {}
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(st)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        raise ctypes.WinError()
    mb = 1024 * 1024
    return {
        "total_phys": int(st.ullTotalPhys // mb),
        "avail_phys": int(st.ullAvailPhys // mb),
        "total_pagefile": int(st.ullTotalPageFile // mb),
        "avail_pagefile": int(st.ullAvailPageFile // mb),
        "total_virtual": int(st.ullTotalVirtual // mb),
        "avail_virtual": int(st.ullAvailVirtual // mb),
    }


# Job Object 结构（JOBOBJECT_EXTENDED_LIMIT_INFORMATION）
class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_ulong),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_ulong),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_ulong),
        ("SchedulingClass", ctypes.c_ulong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9


def make_job(limit_mb: int):
    """建 Job；失败返回 None，脚本退化为“只靠提交额度闸 + 单进程”。"""
    if os.name != "nt":
        return None
    k32 = ctypes.windll.kernel32
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | JOB_OBJECT_LIMIT_JOB_MEMORY
        | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    )
    limit = int(limit_mb) * 1024 * 1024
    info.ProcessMemoryLimit = limit
    info.JobMemoryLimit = limit
    ok = k32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    )
    if not ok:
        k32.CloseHandle(job)
        return None
    return job


def assign_job(job, proc: subprocess.Popen) -> bool:
    if job is None or os.name != "nt":
        return False
    k32 = ctypes.windll.kernel32
    # subprocess 在 Windows 上暴露 _handle；失败就退化为仅内存闸
    return bool(k32.AssignProcessToJobObject(job, ctypes.c_void_p(int(proc._handle))))


def close_job(job) -> None:
    if job and os.name == "nt":
        ctypes.windll.kernel32.CloseHandle(job)


def mem_line(m: dict[str, int]) -> str:
    return ("物理 %s/%s MB；可提交 %s/%s MB；虚拟 %s/%s MB"
            % (m.get("avail_phys"), m.get("total_phys"),
               m.get("avail_pagefile"), m.get("total_pagefile"),
               m.get("avail_virtual"), m.get("total_virtual")))


def check_memory(min_avail_mb: int) -> bool:
    if os.name != "nt":
        return True
    m = win_memory()
    print("MEM  " + mem_line(m))
    if m["avail_pagefile"] < min_avail_mb:
        print("ABORT 可提交额度只剩 %d MB，低于安全线 %d MB；先重启或加大页面文件，别硬跑。"
              % (m["avail_pagefile"], min_avail_mb))
        return False
    if m["total_pagefile"] - m["total_phys"] < 4096:
        print("WARN 页面文件约 %d MB，偏小；16GB 机器建议系统管理或固定 24–32GB。"
              % max(0, m["total_pagefile"] - m["total_phys"]))
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="CADCraft 低内存串行回归")
    ap.add_argument("--list", action="store_true", help="只列测试文件")
    ap.add_argument("--min-avail-mb", type=int, default=2048,
                    help="每个用例前要求的最小可提交额度（MB，默认 2048）")
    ap.add_argument("--job-mb", type=int, default=2048,
                    help="每个测试树的内存硬上限（MB，默认 2048；0=不设 Job）")
    ap.add_argument("--cooldown", type=float, default=5.0,
                    help="用例之间的冷却秒数（默认 5）")
    ap.add_argument("--timeout", type=int, default=900, help="单用例超时秒数（默认 900）")
    ap.add_argument("--keep-going", action="store_true", help="失败后继续，不默认继续")
    ap.add_argument("--log", default=str(ROOT / "tests" / "_safe_run.log"))
    args = ap.parse_args()

    if not TESTS:
        print("没有 tests/test_*.py")
        return 1
    if args.list:
        for p in TESTS:
            print(p.relative_to(ROOT))
        return 0
    if os.name != "nt":
        print("此脚本只支持 Windows；当前是 %s。用 --list 只列文件。" % os.name)
        return 2

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print("SAFE RUN  %d tests；min_avail=%d MB；job=%d MB；cooldown=%ss"
          % (len(TESTS), args.min_avail_mb, args.job_mb, args.cooldown))

    passed = 0
    for i, test in enumerate(TESTS, 1):
        if not check_memory(args.min_avail_mb):
            print("STOP 在 %s 之前停止；已通过 %d/%d，未跑 %d。"
                  % (test.name, passed, len(TESTS), len(TESTS) - i + 1))
            return 3
        print("\n[%d/%d] RUN %s" % (i, len(TESTS), test.name))
        job = make_job(args.job_mb) if args.job_mb > 0 else None
        with log_path.open("a", encoding="utf-8", errors="replace") as lf:
            lf.write("\n===== %s =====\n" % test.name)
            proc = subprocess.Popen(
                [sys.executable, str(test)],
                cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            assigned = assign_job(job, proc)
            if not assigned:
                print("WARN Job Object 未挂上；本用例只靠提交额度闸，进程内存不设硬上限。")
            try:
                rc = proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                rc = -999
            finally:
                close_job(job)
        if rc == 0:
            passed += 1
            print("PASS %s" % test.name)
        else:
            print("FAIL %s rc=%s；日志 %s" % (test.name, rc, log_path))
            if rc in (0xC0000017, -1073741801, 3221225495):
                print("这通常是提交内存不足，不是断言失败。先重启/加大页面文件。")
            if not args.keep_going:
                print("STOP 首个失败即停；已通过 %d/%d。" % (passed, len(TESTS)))
                return 1
        time.sleep(max(0.0, args.cooldown))

    print("\nSAFE RUN PASS (%d/%d)" % (passed, len(TESTS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
