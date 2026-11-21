"""CADCraft 建筑 · 本地 AI 纠错 / 确认面板。

只做"看 + 确认 + 改属性 + 回退"，不提供第二套手动画图工具：
  - 只读预览（PNG，由 CADCraft 导出）
  - 构件树 / 属性（墙、门窗、房间）
  - reconcile / audit 问题清单
  - 改墙厚、门窗位置、房间名（复用 set_wall / set_opening / set_room）
  - checkpoint / restore

启动：
    python tools/panel_server.py --dxf samples/demo_building.dxf
默认只监听 127.0.0.1，图纸路径限制在仓库目录内；需要打开外部项目加 --root。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import shutil
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    audit,
    drawing_scale,
    export,
    opening_data,
    reconcile,
    room_data,
    set_opening,
    set_room,
    set_wall,
    wall_data,
)
from aa_mcp import aa_checkpoint, aa_restore  # noqa: E402

PANEL_DIR = ROOT / "panel"
CACHE_DIR = ROOT / ".panel_cache"
LOCK = threading.Lock()
VERSION = "1.0.44"


def _attrs(geometry: dict[str, Any]) -> dict[str, str]:
    return {
        a["tag"].replace("AA_", "").lower(): a.get("text", {}).get("value", "")
        for a in geometry.get("attribs", [])
    }


def components_report(session: Session) -> list[dict[str, Any]]:
    out = []
    for e in session.references():
        g = e["geometry"]
        name = g.get("block", "")
        if not name.startswith("AA_"):
            continue
        out.append({
            "block": name,
            "handle": e["handle"],
            "at": [round(g["insert"]["x"], 3), round(g["insert"]["y"], 3)],
            "rotation_deg": round(g.get("rotation", 0.0) * 57.29577951308232, 4),
            "attrs": _attrs(g),
        })
    return out


def _resolve_dxf(raw: str, root: Path, default: Path) -> Path:
    text = (raw or "").strip()
    p = Path(text) if text else default
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if root not in p.parents and p != root:
        raise CadError("拒绝访问：图纸必须在 %s 之内（需要外部目录请用 --root 指定）" % root)
    if p.suffix.lower() != ".dxf":
        raise CadError("只接受 .dxf 图纸：%s" % p)
    if not p.exists():
        raise CadError("图纸不存在：%s" % p)
    return p


def _snapshots(path: Path) -> list[dict[str, Any]]:
    d = path.parent / ".aa_snap"
    if not d.exists():
        return []
    rows = []
    for f in d.glob("*.dxf"):
        try:
            st = f.stat()
        except OSError:
            continue
        rows.append({"id": f.name, "path": str(f), "mtime": st.st_mtime,
                     "bytes": st.st_size})
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows[:16]


def state_payload(path: Path) -> dict[str, Any]:
    s = Session(path)
    comps = components_report(s)
    walls = wall_data(s)
    openings = opening_data(s)
    rooms = room_data(s)
    rec = reconcile(s)
    aud = audit(s)
    issues = []
    for it in rec["issues"]:
        issues.append({**it, "source": "reconcile"})
    for it in aud["issues"]:
        issues.append({**it, "source": "audit"})
    return {
        "ok": True,
        "drawing": {
            "path": str(path),
            "name": path.name,
            "mtime": path.stat().st_mtime,
            "size": path.stat().st_size,
            "scale": drawing_scale(s),
        },
        "components": comps,
        "walls": walls,
        "openings": openings,
        "rooms": rooms,
        "reconcile": {k: v for k, v in rec.items() if k != "issues"},
        "audit": {k: v for k, v in aud.items() if k != "issues"},
        "issues": issues,
        "snapshots": _snapshots(path),
    }


def preview_png(path: Path) -> bytes:
    CACHE_DIR.mkdir(exist_ok=True)
    tag = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    out = CACHE_DIR / ("%s-%s-%s.png" % (path.stem, tag, path.stat().st_mtime_ns))
    if not out.exists() or out.stat().st_size < 2048:
        export(Session(path), out, None)
    return out.read_bytes()


def _num(fields: dict[str, Any], key: str) -> float | None:
    v = fields.get(key)
    if v is None or str(v).strip() == "":
        return None
    return float(v)


def _str(fields: dict[str, Any], key: str) -> str | None:
    v = fields.get(key)
    if v is None:
        return None
    return str(v)


def edit_component(path: Path, kind: str, cid: str, fields: dict[str, Any]) -> dict[str, Any]:
    s = Session(path)
    # 每次改属性前自动存一张快照，失败也能从这里回退
    ck = aa_checkpoint(str(path), "before-edit")
    res: dict[str, Any]
    if kind == "wall":
        res = set_wall(
            s, cid,
            thick=_num(fields, "thick"),
            kind=_str(fields, "kind") or None,
            mat=_str(fields, "mat"),
            ax1=_str(fields, "ax1"),
            ax2=_str(fields, "ax2"),
        )
    elif kind == "opening":
        res = set_opening(
            s, cid,
            pos=_num(fields, "pos"),
            width=_num(fields, "width"),
            height=_num(fields, "height"),
            sill=_num(fields, "sill"),
            kind=_str(fields, "kind") or None,
            frame=_num(fields, "frame"),
            no=_str(fields, "no"),
            label_side=_str(fields, "label_side") or None,
        )
    elif kind == "room":
        res = set_room(s, cid, name=_str(fields, "name"))
    else:
        raise CadError("未知构件类型：%s" % kind)
    res["checkpoint"] = ck.get("id")
    return res


class PanelHandler(BaseHTTPRequestHandler):
    server_version = "CADCraftPanel/1.0"
    protocol_version = "HTTP/1.1"

    # ---------- 响应 ----------
    def _send(self, body: bytes, ctype: str, status: int = 200,
              cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: Any, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", status)

    def _err(self, exc: Exception, status: int = 400) -> None:
        if isinstance(exc, CadError):
            self._json({"ok": False, "error": str(exc)}, status)
        else:
            self._json({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}, 500)

    # ---------- GET ----------
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        try:
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                return self._static("index.html")
            if u.path == "/app.js":
                return self._static("app.js")
            if u.path == "/style.css":
                return self._static("style.css")
            if u.path == "/favicon.ico":
                return self._send(b"", "image/x-icon", 204)
            if u.path == "/api/config":
                return self._json(self._config())
            if u.path == "/api/state":
                path = self._path(q)
                with LOCK:
                    return self._json(state_payload(path))
            if u.path == "/api/preview":
                path = self._path(q)
                with LOCK:
                    png = preview_png(path)
                return self._send(png, "image/png")
            if u.path == "/api/snapshots":
                path = self._path(q)
                return self._json({"ok": True, "snapshots": _snapshots(path)})
            self._json({"ok": False, "error": "未知接口：%s" % u.path}, 404)
        except Exception as exc:  # noqa: BLE001
            self._err(exc)

    # ---------- POST ----------
    def do_POST(self) -> None:
        try:
            u = urlparse(self.path)
            body = self._body()
            if u.path == "/api/action":
                path = self._path({"path": [body.get("path", "")]})
                action = str(body.get("action", ""))
                with LOCK:
                    return self._json(self._action(path, action, body))
            if u.path == "/api/edit":
                path = self._path({"path": [body.get("path", "")]})
                kind = str(body.get("kind", ""))
                cid = str(body.get("id", ""))
                fields = body.get("fields") or {}
                if not cid:
                    raise CadError("缺少构件编号")
                with LOCK:
                    res = edit_component(path, kind, cid, fields)
                return self._json({"ok": True, "result": res})
            self._json({"ok": False, "error": "未知接口：%s" % u.path}, 404)
        except Exception as exc:  # noqa: BLE001
            self._err(exc)

    # ---------- 工具 ----------
    def _body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CadError("请求不是合法 JSON") from exc
        if not isinstance(obj, dict):
            raise CadError("请求体必须是 JSON 对象")
        return obj

    def _config(self) -> dict[str, Any]:
        root = self.server.root  # type: ignore[attr-defined]
        default = self.server.default_dxf  # type: ignore[attr-defined]
        rel = default.relative_to(root) if root in default.parents else default
        return {"ok": True, "root": str(root), "default": str(rel),
                "default_abs": str(default), "version": VERSION}

    def _path(self, q: dict[str, list[str]]) -> Path:
        raw = (q.get("path") or [""])[0]
        return _resolve_dxf(unquote(raw), self.server.root,  # type: ignore[attr-defined]
                            self.server.default_dxf)  # type: ignore[attr-defined]

    def _static(self, name: str) -> None:
        f = PANEL_DIR / name
        if not f.exists():
            return self._send(b"not found", "text/plain; charset=utf-8", 404)
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(f.read_bytes(), ctype, cache="no-cache")

    def _action(self, path: Path, action: str, body: dict[str, Any]) -> dict[str, Any]:
        if action == "checkpoint":
            return {"ok": True, **aa_checkpoint(str(path), str(body.get("label", "") or ""))}
        if action == "restore":
            snap = str(body.get("snapshot", "") or "")
            if not snap:
                raise CadError("回退需要 snapshot（快照 id 或路径）")
            return {"ok": True, **aa_restore(str(path), snap)}
        if action == "reconcile":
            return {"ok": True, **reconcile(Session(path), fix=False)}
        if action == "reconcile_fix":
            return {"ok": True, **reconcile(Session(path), fix=True)}
        if action == "audit":
            return {"ok": True, **audit(Session(path))}
        raise CadError("未知动作：%s" % action)

    def log_message(self, fmt: str, *args: Any) -> None:
        # 面板只服务本机，不把每次请求刷到控制台；错误由 API 返回。
        return


def make_server(host: str, port: int, root: Path, default_dxf: Path) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), PanelHandler)
    srv.root = root  # type: ignore[attr-defined]
    srv.default_dxf = default_dxf  # type: ignore[attr-defined]
    return srv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CADCraft 建筑 · 本地 AI 纠错/确认面板")
    ap.add_argument("--dxf", default="samples/demo_building.dxf",
                    help="默认打开的图纸（相对仓库根）")
    ap.add_argument("--root", default=str(ROOT),
                    help="允许访问的图纸根目录（默认仓库根）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    default = _resolve_dxf(args.dxf, root, root / "samples" / "demo_building.dxf")
    try:
        srv = make_server(args.host, args.port, root, default)
    except OSError as exc:
        print("启动失败：%s（端口 %s 可能被占用）" % (exc, args.port), file=sys.stderr)
        return 2
    url = "http://%s:%s/" % (args.host, srv.server_address[1])
    print("CADCraft 面板已启动：%s" % url, flush=True)
    print("默认图纸：%s" % default, flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
