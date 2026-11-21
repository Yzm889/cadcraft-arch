"""面板服务验收：静态页、状态接口、预览 PNG、快照与属性修改。

只在 127.0.0.1 起一个临时端口，测完删掉临时图纸目录。
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import panel_server  # noqa: E402

WORK = ROOT / "samples" / "_panel_test"
CASE = WORK / "case.dxf"


def request(base: str, path: str, body: dict | None = None, raw: bool = False):
    url = base + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            payload = r.read()
            if raw:
                return r.status, payload
            return r.status, json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        raise AssertionError("HTTP %s %s: %s" % (e.code, path, text)) from None


def main() -> int:
    src = ROOT / "samples" / "demo_building.dxf"
    assert src.exists(), src
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    shutil.copy2(src, CASE)

    srv = panel_server.make_server("127.0.0.1", 0, ROOT, CASE)
    port = srv.server_address[1]
    base = "http://127.0.0.1:%d" % port
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        # 1) 静态页
        status, html = request(base, "/", raw=True)
        assert status == 200 and b"AI" in html and b"app.js" in html, status

        # 2) 状态：构件 + 一致检查 + 自检
        q = urllib.parse.quote(str(CASE))
        status, st = request(base, "/api/state?path=" + q)
        assert st["ok"] and st["drawing"]["name"] == "case.dxf", st["drawing"]
        assert len(st["walls"]) >= 1 and st["components"], st
        assert "reconcile" in st and "audit" in st, st.keys()

        # 3) 预览 PNG
        status, png = request(base, "/api/preview?path=" + q, raw=True)
        assert status == 200 and png.startswith(b"\x89PNG") and len(png) > 2048, (status, len(png))

        # 4) 快照
        status, ck = request(base, "/api/action",
                             {"path": str(CASE), "action": "checkpoint", "label": "panel"})
        assert ck["ok"] and ck["id"].endswith(".dxf"), ck
        status, snaps = request(base, "/api/snapshots?path=" + q)
        assert any(s["id"] == ck["id"] for s in snaps["snapshots"]), snaps

        # 5) 改房间名（只在临时图上）
        assert st["rooms"], "示例图没有房间，无法测属性修改"
        room = st["rooms"][0]
        orig = room["name"]
        status, res = request(base, "/api/edit", {"path": str(CASE), "kind": "room",
                                                  "id": room["id"], "fields": {"name": "面板测试"}})
        assert res["ok"] and res["result"]["name"] == "面板测试", res
        auto_ck = res["result"].get("checkpoint")
        assert auto_ck and auto_ck.endswith(".dxf"), res
        status, st2 = request(base, "/api/state?path=" + q)
        got = [r for r in st2["rooms"] if r["id"] == room["id"]][0]
        assert got["name"] == "面板测试", got

        # 6) 回退到改前自动快照
        status, rs = request(base, "/api/action",
                             {"path": str(CASE), "action": "restore", "snapshot": auto_ck})
        assert rs["ok"], rs
        status, st3 = request(base, "/api/state?path=" + q)
        got3 = [r for r in st3["rooms"] if r["id"] == room["id"]][0]
        assert got3["name"] == orig, got3

        print("PASS test_panel")
        return 0
    finally:
        srv.shutdown()
        srv.server_close()
        th.join(timeout=10)
        shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
