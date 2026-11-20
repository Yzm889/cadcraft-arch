"""MCP 服务器验收：工具表、初始化握手、真实工具调用、失败如实上报、stdio 通道。

覆盖两类：进程内直接调 handle()（快），以及真的拉起子进程走 stdio（证明客户端能接）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_mcp  # noqa: E402

OUT = ROOT / "samples"
MCP = ROOT / "tools" / "aa_mcp.py"


def rpc(method, params=None, mid=1):
    req = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        req["params"] = params
    return aa_mcp.handle(req)


def call(name, args):
    res = rpc("tools/call", {"name": name, "arguments": args})
    payload = json.loads(res["result"]["content"][0]["text"])
    return res["result"]["isError"], payload


def main() -> int:
    # 1) 初始化握手
    init = rpc("initialize", {})
    assert init["result"]["protocolVersion"] == aa_mcp.PROTOCOL_VERSION
    assert init["result"]["capabilities"]["tools"] == {"listChanged": False}
    assert init["result"]["serverInfo"]["name"] == "cadcraft-arch"

    # 2) 工具表完整、每项都有 inputSchema 与 description
    tools = rpc("tools/list")["result"]["tools"]
    names = [t["name"] for t in tools]
    assert len(names) == 32, names
    for n in ("aa_new", "aa_axis", "aa_wall", "aa_opening", "aa_room",
              "aa_room_auto", "aa_split", "aa_merge", "aa_set_wall",
              "aa_set_opening", "aa_openings", "aa_show", "aa_set_room", "aa_rooms"):
        assert n in names, n
    for t in tools:
        assert t["inputSchema"]["type"] == "object", t["name"]
        assert t["inputSchema"]["required"], t["name"]
        assert t["description"], t["name"]
    # 名字唯一
    assert len(names) == len(set(names))

    # 3) 未知方法 / 未知工具都要明确报错
    assert rpc("foo/bar")["error"]["code"] == -32601
    is_err, payload = call("aa_nothing", {"path": "x.dxf"})
    assert is_err and "未知工具" in payload["error"], payload

    # 4) 真跑一条链路：new -> axis -> 4 墙 -> 自动搜房间 -> 回读
    dxf = OUT / "test_mcp.dxf"
    if dxf.exists():
        dxf.unlink()

    is_err, p = call("aa_new", {"path": str(dxf)})
    assert not is_err and p["ok"], p
    is_err, p = call("aa_new", {"path": str(dxf)})
    assert is_err and "不覆盖" in p["error"], p

    is_err, p = call("aa_axis", {"path": str(dxf), "id": "AX001", "xcount": 2,
                                 "xspace": 3600, "ycount": 2, "yspace": 4800})
    assert not is_err and p["ok"] and len(p["geom_handles"]) >= 4, p

    rect = [("W001", [0, 0], [6000, 0]), ("W002", [6000, 0], [6000, 4000]),
            ("W003", [6000, 4000], [0, 4000]), ("W004", [0, 4000], [0, 0])]
    for wid, a, b in rect:
        is_err, p = call("aa_wall", {"path": str(dxf), "id": wid, "p1": a, "p2": b,
                                    "thick": 240, "kind": "EXTERNAL"})
        assert not is_err and p["ok"] and len(p["geom_handles"]) == 2, p
        assert "normalized" in p, p          # 画完自动规整邻墙

    is_err, p = call("aa_opening", {"path": str(dxf), "id": "D001", "wall": "W001",
                                    "kind": "DOOR", "width": 900, "pos": 2000})
    assert not is_err and p["ok"], p

    is_err, p = call("aa_room_auto", {"path": str(dxf)})
    assert not is_err and p["rooms"] == 1, p
    assert abs(p["created"][0]["area"] - 5760 * 3760) < 1.0, p

    is_err, p = call("aa_show", {"path": str(dxf)})
    assert not is_err and p["ok"]
    assert len(p["walls"]) == 4, p["walls"]
    assert len(p["openings"]) == 1, p["openings"]
    assert len(p["rooms"]) == 1, p["rooms"]
    assert p["rooms"][0]["walls"] and len(p["rooms"][0]["walls"]) == 4, p["rooms"]

    # 4b) 房间改名 + 汇总表（MCP 侧两条新工具）
    is_err, q = call("aa_set_room", {"path": str(dxf), "id": "R001", "name": "客厅"})
    assert not is_err and q["changed"] == 1, q
    is_err, q = call("aa_show", {"path": str(dxf)})
    assert q["rooms"][0]["name"] == "客厅", q["rooms"]
    is_err, q = call("aa_rooms", {"path": str(dxf)})
    assert not is_err and q["rooms"] == 1, q
    assert q["rows"][0]["房间名称"] == "客厅", q["rows"]

    # 5) 失败必须如实上报（越界开洞）：isError=true，且图纸不留半成品
    before = [(w["id"], w["block"], tuple(round(c, 3) for c in w["p1"])) for w in p["walls"]]
    is_err, q = call("aa_opening", {"path": str(dxf), "id": "D002", "wall": "W001",
                                    "kind": "DOOR", "width": 900, "pos": 5900})
    assert is_err and not q["ok"], q
    assert "越界" in q["error"] or "超出" in q["error"], q
    is_err, q = call("aa_show", {"path": str(dxf)})
    assert [(w["id"], w["block"], tuple(round(c, 3) for c in w["p1"])) for w in q["walls"]] == before
    assert len(q["openings"]) == 1, q["openings"]

    # 6) 真走 stdio：拉起子进程，发 initialize + tools/list，读回两行 JSON
    proc = subprocess.Popen([sys.executable, str(MCP), "--serve"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1,
                                     "method": "initialize", "params": {}}) + "\n")
        proc.stdin.write(json.dumps({"jsonrpc": "2.0",
                                     "method": "notifications/initialized"}) + "\n")
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
        proc.stdin.flush()
        lines = [proc.stdout.readline(), proc.stdout.readline()]
        r1, r2 = json.loads(lines[0]), json.loads(lines[1])
        assert r1["id"] == 1 and r1["result"]["serverInfo"]["name"] == "cadcraft-arch", r1
        assert r2["id"] == 2 and len(r2["result"]["tools"]) == 32, r2
        assert all(lines), lines             # 通知不产生响应，两行正好是 id=1 / id=2
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)

    print("PASS test_mcp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
