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
import os
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
    verify,
    wall_data,
)
from aa_mcp import aa_batch, aa_checkpoint, aa_restore  # noqa: E402

PANEL_DIR = ROOT / "panel"
CACHE_DIR = ROOT / ".panel_cache"
PROPOSAL_DIR = CACHE_DIR / "proposals"
PROPOSAL_TOOLS = frozenset({"aa_set_wall", "aa_set_opening", "aa_set_room"})
MAX_PROPOSAL_OPS = 100
PREVIEW_ASPECT = 1.5
LOCK = threading.Lock()
VERSION = "1.0.50"
RECENT_FILE = CACHE_DIR / "recent.json"
MAX_RECENT = 8


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


def issues_from(rec: dict[str, Any], aud: dict[str, Any],
                ver: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [{**it, "source": "reconcile"} for it in rec["issues"]]
    rows += [{**it, "source": "audit"} for it in aud["issues"]]
    rows += [{**it, "source": "verify"} for it in ver["issues"]]
    return rows


def issue_rows(session: Session) -> list[dict[str, Any]]:
    return issues_from(reconcile(session), audit(session), verify(session))


def _kind_of(block: str) -> str:
    if block.startswith("AA_WALL_"):
        return "墙"
    if block.startswith("AA_OPENING_"):
        return "门窗"
    if block.startswith("AA_ROOM_"):
        return "房间"
    return "其他"


def _same(a: Any, b: Any) -> bool:
    if a == b:
        return True
    try:
        return abs(float(a) - float(b)) <= 1e-6
    except (TypeError, ValueError):
        return str(a) == str(b)


def _component_changes(before: list[dict[str, Any]],
                       after: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    old = {c["block"]: c for c in before}
    new = {c["block"]: c for c in after}
    changes: list[dict[str, Any]] = []
    counts = {"added": 0, "removed": 0, "changed": 0}
    for block in sorted(set(old) | set(new)):
        a, b = old.get(block), new.get(block)
        if a is None:
            counts["added"] += 1
            fields = [{"name": k, "before": None, "after": v} for k, v in sorted(b["attrs"].items())]
            changes.append({"block": block, "id": b["attrs"].get("id") or block,
                            "kind": _kind_of(block), "change": "added", "fields": fields})
            continue
        if b is None:
            counts["removed"] += 1
            fields = [{"name": k, "before": v, "after": None} for k, v in sorted(a["attrs"].items())]
            changes.append({"block": block, "id": a["attrs"].get("id") or block,
                            "kind": _kind_of(block), "change": "removed", "fields": fields})
            continue
        fields = []
        for k in sorted(set(a["attrs"]) | set(b["attrs"])):
            av, bv = a["attrs"].get(k), b["attrs"].get(k)
            if not _same(av, bv):
                fields.append({"name": k, "before": av, "after": bv})
        if not _same(a["at"], b["at"]):
            fields.append({"name": "at", "before": a["at"], "after": b["at"]})
        if not _same(a["rotation_deg"], b["rotation_deg"]):
            fields.append({"name": "rotation", "before": a["rotation_deg"], "after": b["rotation_deg"]})
        if fields:
            counts["changed"] += 1
            changes.append({"block": block, "id": b["attrs"].get("id") or block,
                            "kind": _kind_of(block), "change": "changed", "fields": fields})
    return changes, counts


def _issue_key(it: dict[str, Any]) -> tuple[str, str, str, str]:
    return (str(it.get("source") or ""), str(it.get("kind") or ""),
            str(it.get("ref") or ""), str(it.get("message") or ""))


def _issue_changes(before: list[dict[str, Any]],
                   after: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    old = {_issue_key(it): it for it in before}
    new = {_issue_key(it): it for it in after}
    added = [new[k] for k in sorted(set(new) - set(old))]
    fixed = [old[k] for k in sorted(set(old) - set(new))]
    return added[:40], fixed[:40]


def _proposal_dir(path: Path) -> Path:
    tag = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]
    return PROPOSAL_DIR / tag


def _proposal_file(path: Path) -> Path:
    return _proposal_dir(path) / "proposal.json"


def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def load_proposal(path: Path) -> dict[str, Any] | None:
    f = _proposal_file(path)
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    data["stale"] = data.get("base_sha1") != _sha1(path)
    return data


def public_proposal(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "created": data.get("created"),
        "ops_count": len(data.get("ops") or []),
        "summary": data.get("summary") or {},
        "changes": (data.get("changes") or [])[:120],
        "new_issues": data.get("new_issues") or [],
        "fixed_issues": data.get("fixed_issues") or [],
        "stale": bool(data.get("stale")),
        "view": data.get("view"),
        "geometry": data.get("geometry") or {},
    }


def _clean_ops(ops: Any) -> list[dict[str, Any]]:
    if not isinstance(ops, list) or not ops:
        raise CadError("变更集需要非空的 ops 列表")
    if len(ops) > MAX_PROPOSAL_OPS:
        raise CadError("变更集最多 %d 项操作" % MAX_PROPOSAL_OPS)
    clean = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise CadError("变更集第 %d 项格式错误：需要 {tool, args}" % i)
        tool = str(op.get("tool") or "")
        if tool not in PROPOSAL_TOOLS:
            raise CadError("变更集第 %d 项工具不允许：%s（当前只接受 %s）"
                           % (i, tool, " / ".join(sorted(PROPOSAL_TOOLS))))
        args = op.get("args") or {}
        if not isinstance(args, dict):
            raise CadError("变更集第 %d 项 args 必须是对象" % i)
        args = {k: v for k, v in args.items() if k != "path"}
        if not args.get("id"):
            raise CadError("变更集第 %d 项缺少构件编号 id" % i)
        clean.append({"tool": tool, "args": args})
    return clean


def create_proposal(path: Path, title: str, ops: list[dict[str, Any]]) -> dict[str, Any]:
    clean = _clean_ops(ops)
    base_sha1 = _sha1(path)
    d = _proposal_dir(path)
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    case = d / "case.dxf"
    shutil.copy2(path, case)
    try:
        before = components_report(Session(path))
        before_issues = issue_rows(Session(path))
        batch = aa_batch(str(case), clean, rollback=True)
        if not batch.get("ok"):
            raise CadError("变更集第 %d 项 %s 失败：%s"
                           % (int(batch.get("failed_index", 0)), batch.get("failed_tool"),
                              batch.get("error", "未知错误")))
        s_after = Session(case)
        after = components_report(s_after)
        after_issues = issue_rows(s_after)
        changes, counts = _component_changes(before, after)
        new_issues, fixed_issues = _issue_changes(before_issues, after_issues)
        data = {
            "id": time.strftime("%Y%m%d-%H%M%S"),
            "title": (title or "AI 变更集").strip()[:80],
            "created": time.time(),
            "path": str(path),
            "base_sha1": base_sha1,
            "ops": clean,
            "summary": counts,
            "changes": changes[:200],
            "new_issues": new_issues,
            "fixed_issues": fixed_issues,
            "preview_path": str(case),
            "preview_mtime": case.stat().st_mtime,
            "view": {"window": preview_window(s_after), "aspect": PREVIEW_ASPECT},
            "geometry": {
                "walls": wall_data(s_after),
                "openings": opening_data(s_after),
                "rooms": room_data(s_after),
            },
        }
        _proposal_file(path).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        return data
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise


def commit_proposal(path: Path) -> dict[str, Any]:
    data = load_proposal(path)
    if not data:
        raise CadError("没有待确认的 AI 变更集")
    if data["stale"]:
        raise CadError("原图已变化，变更集预演失效，请让 AI 重新提交")
    case = Path(data["preview_path"])
    if not case.exists():
        raise CadError("变更集临时图纸不存在，请重新提交")
    ck = aa_checkpoint(str(path), "before-batch")
    tmp = path.with_name(path.name + ".panel.tmp")
    try:
        shutil.copy2(case, tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    shutil.rmtree(_proposal_dir(path), ignore_errors=True)
    return {"ok": True, "checkpoint": ck["id"], "bytes": path.stat().st_size}


def discard_proposal(path: Path) -> dict[str, Any]:
    d = _proposal_dir(path)
    existed = d.exists()
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True, "discarded": existed}


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


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _all_recent() -> list[Path]:
    try:
        rows = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for raw in rows if isinstance(rows, list) else []:
        try:
            p = Path(str(raw)).resolve()
        except (OSError, ValueError):
            continue
        if p.suffix.lower() == ".dxf":
            out.append(p)
    return out


def _recent_paths(root: Path) -> list[Path]:
    return [p for p in _all_recent()
            if _inside(p, root) and p.is_file()][:MAX_RECENT]


def _remember_recent(path: Path) -> None:
    p = path.resolve()
    keep = [p] + [x for x in _all_recent() if x != p and x.is_file()]
    keep = keep[:MAX_RECENT]
    CACHE_DIR.mkdir(exist_ok=True)
    tmp = RECENT_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps([str(x) for x in keep], ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(RECENT_FILE)
    except OSError:
        tmp.unlink(missing_ok=True)


def _recent_rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for p in _recent_paths(root):
        try:
            st = p.stat()
        except OSError:
            continue
        rel = str(p.relative_to(root)) if _inside(p, root) else str(p)
        rows.append({"name": p.name, "path": str(p), "rel": rel,
                     "mtime": st.st_mtime, "bytes": st.st_size})
    return rows


def _file_rows(root: Path, raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    p = Path(text) if text else root
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if not _inside(p, root):
        raise CadError("拒绝访问：目录必须在 %s 之内（需要外部目录请用 --root 指定）" % root)
    if not p.is_dir():
        raise CadError("不是文件夹：%s" % p)
    dirs, files = [], []
    try:
        for f in p.iterdir():
            if f.name.startswith("."):
                continue
            try:
                if f.is_dir():
                    dirs.append({"name": f.name, "path": str(f)})
                elif f.suffix.lower() == ".dxf" and f.is_file():
                    st = f.stat()
                    files.append({"name": f.name, "path": str(f),
                                  "rel": str(f.relative_to(root)),
                                  "mtime": st.st_mtime, "bytes": st.st_size})
            except OSError:
                continue
    except OSError as exc:
        raise CadError("读不了文件夹：%s（%s）" % (p, exc))
    dirs.sort(key=lambda x: x["name"].casefold())
    files.sort(key=lambda x: x["name"].casefold())
    parent = str(p.parent) if p != root else ""
    return {"ok": True, "root": str(root), "dir": str(p), "parent": parent,
            "dirs": dirs[:80], "files": files[:160]}


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
    ver = verify(s)
    issues = issues_from(rec, aud, ver)
    prop = load_proposal(path)
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
        "verify": {k: v for k, v in ver.items() if k != "issues"},
        "issues": issues,
        "snapshots": _snapshots(path),
        "view": {"window": preview_window(s), "aspect": PREVIEW_ASPECT},
        "proposal": public_proposal(prop) if prop else None,
    }


def preview_window(session: Session) -> list[float]:
    """预览统一取“构件范围外扩 + 补到 1.5:1”的窗口，保证 PNG 不留黑边、坐标可线性映射。

    只按墙/房间的真实几何取范围，避免图纸里的图框、轴号符号等远端对象把主楼压成一小块；
    外扩 30% 也把基础、尺寸线等贴近主体的内容带进画面。
    """
    pts: list[tuple[float, float]] = []
    try:
        for w in wall_data(session):
            pts.append((float(w["p1"][0]), float(w["p1"][1])))
            pts.append((float(w["p2"][0]), float(w["p2"][1])))
        for r in room_data(session):
            for p in r.get("pts") or []:
                pts.append((float(p[0]), float(p[1])))
    except (KeyError, TypeError, ValueError):
        pts = []
    if pts:
        x0 = min(p[0] for p in pts)
        x1 = max(p[0] for p in pts)
        y0 = min(p[1] for p in pts)
        y1 = max(p[1] for p in pts)
    else:
        try:
            ext = session.info()["extents"]
            x0, y0 = float(ext[0][0]), float(ext[0][1])
            x1, y1 = float(ext[1][0]), float(ext[1][1])
        except (KeyError, IndexError, TypeError, ValueError):
            x0, y0, x1, y1 = 0.0, 0.0, 1000.0, 1000.0
    w, h = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    pad = max(0.30 * max(w, h), 500.0)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    w, h = x1 - x0, y1 - y0
    if w / h > PREVIEW_ASPECT:
        nh = w / PREVIEW_ASPECT
        cy = (y0 + y1) / 2.0
        y0, y1 = cy - nh / 2.0, cy + nh / 2.0
    else:
        nw = h * PREVIEW_ASPECT
        cx = (x0 + x1) / 2.0
        x0, x1 = cx - nw / 2.0, cx + nw / 2.0
    return [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]


def preview_png(path: Path) -> bytes:
    CACHE_DIR.mkdir(exist_ok=True)
    tag = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    out = CACHE_DIR / ("%s-%s-%s.png" % (path.stem, tag, path.stat().st_mtime_ns))
    if not out.exists() or out.stat().st_size < 2048:
        s = Session(path)
        export(s, out, preview_window(s), lineweights=False)
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
                    data = state_payload(path)
                    _remember_recent(path)
                    data["recent"] = _recent_rows(self.server.root)  # type: ignore[attr-defined]
                    return self._json(data)
            if u.path == "/api/files":
                raw = (q.get("dir") or [""])[0]
                with LOCK:
                    return self._json(_file_rows(self.server.root, unquote(raw)))  # type: ignore[attr-defined]
            if u.path == "/api/preview":
                path = self._path(q)
                with LOCK:
                    png = preview_png(path)
                return self._send(png, "image/png")
            if u.path == "/api/proposal/preview":
                path = self._path(q)
                with LOCK:
                    prop = load_proposal(path)
                    if not prop:
                        raise CadError("没有待确认的 AI 变更集")
                    case = Path(prop.get("preview_path") or "")
                    if not case.exists():
                        raise CadError("变更集临时图纸不存在，请重新提交")
                    png = preview_png(case)
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
            if u.path == "/api/proposal":
                path = self._path({"path": [body.get("path", "")]})
                with LOCK:
                    data = create_proposal(path, str(body.get("title", "")), body.get("ops"))
                return self._json({"ok": True, "proposal": public_proposal(data)})
            if u.path == "/api/proposal/commit":
                path = self._path({"path": [body.get("path", "")]})
                with LOCK:
                    res = commit_proposal(path)
                return self._json({"ok": True, "result": res})
            if u.path == "/api/proposal/discard":
                path = self._path({"path": [body.get("path", "")]})
                with LOCK:
                    res = discard_proposal(path)
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
                "default_abs": str(default), "version": VERSION,
                "recent": _recent_rows(root)}

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
        if action == "verify":
            return {"ok": True, **verify(Session(path))}
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
