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
    assert len(names) == 54, names
    for n in ("aa_new", "aa_axis", "aa_wall", "aa_opening", "aa_room",
              "aa_room_auto", "aa_split", "aa_merge", "aa_set_wall",
              "aa_set_opening", "aa_openings", "aa_opening_table", "aa_wall_node",
              "aa_stair_detail", "aa_wc_detail", "aa_elev_balcony", "aa_foundation", "aa_text", "aa_leader", "aa_detail_mark", "aa_opening_detail", "aa_copy_floor", "aa_sheet_set", "aa_sheet_index", "aa_show", "aa_set_room", "aa_rooms"):
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

    # 5b) 门窗表：建表 + 回读（MCP 侧 aa_opening_table）
    is_err, q = call("aa_opening_table", {"path": str(dxf), "id": "MC1",
                                          "at": [8000, 4000],
                                          "note": "注：门窗详见建施-04 门窗表"})
    assert not is_err and q["ok"], q
    assert q["count"] == 1 and q["total"] == 1, q
    assert q["items"][0]["no"] == "M0921" and q["items"][0]["level_text"] == "1", q["items"]
    is_err, q = call("aa_opening_table", {"path": str(dxf), "show": "MC1"})
    assert not is_err and q["rows"][0]["no"] == "M0921", q
    is_err, q = call("aa_opening_table", {"path": str(dxf), "show": "MC9"})
    assert is_err and "没找到" in q["error"], q

    # 5c) 图纸集 + 图纸目录（MCP 侧两条新工具）
    is_err, q = call("aa_sheet", {"path": str(dxf), "id": "S001", "size": "A4",
                                  "scale": 100, "at": [0, 18000]})
    assert not is_err and q["ok"] and q["size"] == "A4", q
    is_err, q = call("aa_sheet_set", {"path": str(dxf), "id": "SS1", "items": [
        {"no": "建施-01", "name": "一层平面图", "sheet": "S001"}]})
    assert not is_err and q["ok"] and q["count"] == 1, q
    assert q["items"][0]["size"] == "A4", q["items"]
    is_err, q = call("aa_sheet_set", {"path": str(dxf), "show": "SS1"})
    assert not is_err and q["count"] == 1, q
    is_err, q = call("aa_sheet_index", {"path": str(dxf), "id": "SS1",
                                        "table": "ML1", "at": [-3000, 24000]})
    assert not is_err and q["ok"] and q["count"] == 1, q
    is_err, q = call("aa_sheet_index", {"path": str(dxf), "show": "ML1"})
    assert not is_err and q["rows"][0]["no"] == "建施-01", q

    # 5d) 楼层复制：1 层 → 2 层（4 墙 1 门 1 房间）
    is_err, q = call("aa_copy_floor", {"path": str(dxf), "from": 1, "to": 2,
                                       "offset": [0, 6000], "prefix": "2"})
    assert not is_err and q["ok"], q
    assert q["counts"] == {"walls": 4, "openings": 1, "rooms": 1}, q
    is_err, q = call("aa_copy_floor", {"path": str(dxf), "from": 1, "to": 2,
                                       "offset": [0, 6000], "prefix": "2"})
    assert is_err and "已有墙" in q["error"], q

    # 5e) 详图：详图符号 14mm + 门窗大样（D001 门 → 1:20 放大 5 倍）
    is_err, q = call("aa_detail_mark", {"path": str(dxf), "id": "DM1",
                                        "at": [3000, 900], "detail": "1"})
    assert not is_err and q["diameter"] == 1400.0 and len(q["geom_handles"]) == 4, q
    is_err, q = call("aa_opening_detail", {"path": str(dxf), "id": "OD1",
                                           "at": [0, -9000], "opening": "D001",
                                           "ratio": 20})
    assert not is_err and q["kind"] == "DOOR" and q["factor"] == 5.0 and q["dims"] == 2, q
    is_err, q = call("aa_opening_detail", {"path": str(dxf), "id": "OD1",
                                           "at": [0, -9000], "opening": "D001"})
    assert is_err and "已存在" in q["error"], q

    # 5f) 墙身节点：窗台 + 女儿墙
    is_err, q = call("aa_wall_node", {"path": str(dxf), "id": "WN1",
                                      "at": [0, -20000], "kind": "SILL"})
    assert not is_err and q["kind"] == "SILL" and q["factor"] == 5.0 and q["dims"] == 2, q
    is_err, q = call("aa_wall_node", {"path": str(dxf), "id": "WN2",
                                      "at": [9000, -20000], "kind": "PARAPET",
                                      "parapet": 1200})
    assert not is_err and q["parapet"] == 1200.0, q
    is_err, q = call("aa_wall_node", {"path": str(dxf), "id": "WN1",
                                      "at": [0, -20000]})
    assert is_err and "已存在" in q["error"], q

    # 5g) 楼梯间大样：先在图纸里放一部双跑楼梯，再放大
    from aa_lib import Session, create_stair  # noqa: E402
    s = Session(dxf)
    create_stair(s, "ST1", (0, -3000), kind="DOGLEG", width=1200, steps=10,
                 tread=280, well=120, landing=1200, level="MIDDLE", side="LEFT")
    is_err, q = call("aa_stair_detail", {"path": str(dxf), "id": "SD1",
                                        "at": [0, -24000], "stair": "ST1"})
    assert not is_err and q["kind"] == "DOGLEG" and q["dims"] == 3, q
    is_err, q = call("aa_stair_detail", {"path": str(dxf), "id": "SD1", "at": [0, -24000]})
    assert is_err and "已存在" in q["error"], q

    # 5h) 卫生间大样：默认 2400×1800 + 自定义地漏
    is_err, q = call("aa_wc_detail", {"path": str(dxf), "id": "WC1", "at": [8000, -6000]})
    assert not is_err and q["dims"] == 3 and q["width"] == 2400.0, q
    is_err, q = call("aa_wc_detail", {"path": str(dxf), "id": "WC1", "at": [8000, -6000]})
    assert is_err and "已存在" in q["error"], q
    is_err, q = call("aa_wc_detail", {"path": str(dxf), "id": "WC2", "at": [20000, -6000],
                                     "w": 1800, "h": 2100, "drain": [1500, 300]})
    assert not is_err and q["width"] == 1800.0 and q["drain"] == [1500.0, 300.0], q

    # 5i) 立面阳台 / 雨篷
    is_err, q = call("aa_elev_balcony", {"path": str(dxf), "id": "EB1",
                                        "at": [0, 3600], "width": 2400})
    assert not is_err and q["kind"] == "BALCONY" and q["dims"] == 2, q
    is_err, q = call("aa_elev_balcony", {"path": str(dxf), "id": "EB2",
                                        "at": [3200, 2100], "kind": "AWNING", "slab": 120})
    assert not is_err and q["kind"] == "AWNING" and q["slab"] == 120.0, q
    is_err, q = call("aa_elev_balcony", {"path": str(dxf), "id": "EB1", "at": [0, 3600]})
    assert is_err and "已存在" in q["error"], q

    # 5j) 基础大放脚
    is_err, q = call("aa_foundation", {"path": str(dxf), "id": "FD1", "at": [0, -10000]})
    assert not is_err and q["steps"] == 2 and q["base_width"] == 500.0, q
    is_err, q = call("aa_foundation", {"path": str(dxf), "id": "FD1", "at": [0, -10000]})
    assert is_err and "已存在" in q["error"], q

    # 5k) 注字 / 引注
    is_err, q = call("aa_text", {"path": str(dxf), "id": "T1", "at": [0, 12000],
                                 "text": "外墙 240", "height": 3.5})
    assert not is_err and q["text"] == "外墙 240" and q["height"] == 350.0, q
    is_err, q = call("aa_leader", {"path": str(dxf), "id": "L1", "at": [3000, 2400],
                                   "text": "C1515", "to": [5000, 3200]})
    assert not is_err and q["shelf"] == 500.0 and q["to"] == [5000.0, 3200.0], q
    is_err, q = call("aa_text", {"path": str(dxf), "id": "T1", "at": [0, 12000],
                                 "text": "重号"})
    assert is_err and "已存在" in q["error"], q

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
        assert r2["id"] == 2 and len(r2["result"]["tools"]) == 54, r2
        assert all(lines), lines             # 通知不产生响应，两行正好是 id=1 / id=2
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)

    print("PASS test_mcp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
