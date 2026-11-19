"""用 MCP 客户端身份（stdio 子进程）从零画一张平面图，证明 Agent 直连链路可用。

与 test_mcp.py 的区别：这里不测协议细节，而是像 Agent 那样**只调工具、不碰内部函数**，
最后导出 PNG 作为可肉眼验收的成品。

用法：python tools/mcp_demo.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "tools" / "aa_mcp.py"
OUT = ROOT / "samples" / "mcp_demo.dxf"
PNG = ROOT / "samples" / "mcp_demo.png"
CLI = Path("C:/Users/19891/AppData/Local/Programs/ArtCraft/CADCraft/cadcraft-cli.exe")


class McpClient:
    """极简 MCP 客户端：一行一条 JSON-RPC，够用来验收服务端。"""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER), "--serve"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self._id = 0
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "mcp_demo", "version": "0.1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg: dict) -> None:
        self.proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read()
            raise SystemExit("MCP 服务端异常退出：%s" % err)
        resp = json.loads(line)
        if "error" in resp:
            raise SystemExit("协议错误：%s" % resp["error"])
        return resp["result"]

    def call(self, tool: str, **args) -> dict:
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        payload = json.loads(res["content"][0]["text"])
        flag = "FAIL" if res["isError"] else "ok  "
        print("%s %-14s %s" % (flag, tool, json.dumps(payload, ensure_ascii=False)[:170]))
        if res["isError"]:
            raise SystemExit("工具失败：%s" % payload["error"])
        return payload

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


def main() -> int:
    for f in (OUT, PNG):
        if f.exists():
            f.unlink()

    c = McpClient()
    c.call("aa_new", path=str(OUT))
    c.call("aa_axis", path=str(OUT), id="AX001", xcount=3, xspace=3000,
           ycount=2, yspace=4000, ext=800)

    walls = [("W001", [0, 0], [6000, 0], "EXTERNAL", 240),
             ("W002", [6000, 0], [6000, 4000], "EXTERNAL", 240),
             ("W003", [6000, 4000], [0, 4000], "EXTERNAL", 240),
             ("W004", [0, 4000], [0, 0], "EXTERNAL", 240),
             ("W005", [3000, 0], [3000, 4000], "PARTITION", 240)]
    for wid, p1, p2, kind, thick in walls:
        c.call("aa_wall", path=str(OUT), id=wid, p1=p1, p2=p2, thick=thick, kind=kind)

    c.call("aa_opening", path=str(OUT), id="D001", wall="W001", kind="DOOR",
           width=900, pos=1500)
    c.call("aa_opening", path=str(OUT), id="C001", wall="W002", kind="WINDOW",
           width=1200, pos=2000, sill=900, height=1500)
    c.call("aa_opening", path=str(OUT), id="D002", wall="W005", kind="DOOR",
           width=900, pos=2000)

    rooms = c.call("aa_room_auto", path=str(OUT), prefix="R")
    print("房间：", [(r["id"], r["area"], r["walls"]) for r in rooms["created"]])

    # 房间命名 + 面积表（CSV 落盘 + 图上表格）
    c.call("aa_set_room", path=str(OUT), id="R001", name="起居室")
    c.call("aa_set_room", path=str(OUT), id="R002", name="卧室")
    rep = c.call("aa_rooms", path=str(OUT), csv=str(OUT.with_name("mcp_demo_rooms.csv")),
                 table_at=[0.0, -2400.0])
    print("面积表：%d 间，合计 %.2f m² -> %s" % (rep["rooms"], rep["total_area_m2"], rep["csv"]))

    shown = c.call("aa_show", path=str(OUT))
    print("构件：墙 %d / 门窗 %d / 房间 %d" %
          (len(shown["walls"]), len(shown["openings"]), len(shown["rooms"])))
    c.close()

    if CLI.exists():
        subprocess.run([str(CLI), "run", str(OUT), "--export", str(PNG)], check=True,
                       stdout=subprocess.DEVNULL)
        print("导出：", PNG)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
