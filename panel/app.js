/* CADCraft 建筑 · AI 纠错/确认面板
 * 只读预览 + 构件树 + 问题清单 + 属性修改 + 快照回退。
 * 所有写操作都走 aa_lib 的 set_wall / set_opening / set_room，不在前端画线。
 */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const S = {
    config: null,
    path: "",
    data: null,
    selected: null,
    currentSrc: "",
    prevSrc: "",
    compare: false,
    zoom: 100,
    busy: false,
    tab: "components",
    showOther: false,
  };

  const esc = (v) => String(v == null ? "" : v)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");

  const fmt = (v, d = 0) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });
  };
  const areaText = (mm2) => {
    const n = Number(mm2);
    if (!Number.isFinite(n)) return "—";
    return n >= 1e6 ? `${fmt(n / 1e6, 2)} m²` : `${fmt(n)} mm²`;
  };
  const typeOf = (c) => {
    if (c.block.startsWith("AA_WALL_")) return "wall";
    if (c.block.startsWith("AA_OPENING_")) return "opening";
    if (c.block.startsWith("AA_ROOM_")) return "room";
    return "other";
  };
  const idOf = (c) => c.attrs.id || c.block.replace(/^AA_[A-Z_]+?_/, "");

  function log(msg, kind = "") {
    const list = $("#logList");
    const line = document.createElement("div");
    line.className = `log-line ${kind}`;
    const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    line.innerHTML = `<span class="t">${time}</span>${esc(msg)}`;
    list.appendChild(line);
    while (list.children.length > 80) list.firstChild.remove();
    list.scrollTop = list.scrollHeight;
  }

  let toastTimer = 0;
  function toast(msg, kind = "") {
    const el = $("#toast");
    el.textContent = msg;
    el.className = `toast ${kind}`;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 4200);
  }

  function error(msg) {
    const el = $("#errorBanner");
    el.textContent = msg;
    el.hidden = false;
    log(msg, "err");
  }
  function clearError() { $("#errorBanner").hidden = true; }

  function setBusy(on, text = "正在读取图纸…") {
    S.busy = on;
    $("#loading").hidden = !on;
    $("#loadingText").textContent = text;
    const dot = $("#liveDot");
    dot.className = `dot ${on ? "busy" : (S.data ? "on" : "")}`;
    $("#openBtn").disabled = on;
    $("#refreshBtn").disabled = on;
    $("#runAuditBtn").disabled = on;
    $("#runReconcileBtn").disabled = on;
    $("#fixReconcileBtn").disabled = on;
    $("#snapshotBtn").disabled = on;
  }

  async function apiGet(url) {
    const r = await fetch(url, { headers: { "Accept": "application/json" } });
    let j = null;
    try { j = await r.json(); } catch { /* ignore */ }
    if (!r.ok || !j || j.ok === false) {
      throw new Error((j && j.error) || `HTTP ${r.status}`);
    }
    return j;
  }

  async function apiPost(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body),
    });
    let j = null;
    try { j = await r.json(); } catch { /* ignore */ }
    if (!r.ok || !j || j.ok === false) {
      throw new Error((j && j.error) || `HTTP ${r.status}`);
    }
    return j;
  }

  // ---------- 载入 ----------
  async function loadConfig() {
    try {
      S.config = await apiGet("/api/config");
      $("#version").textContent = `v${S.config.version}`;
      $("#pathInput").value = S.config.default;
      if (S.config.default) await openDrawing(false);
    } catch (e) {
      error(`读取配置失败：${e.message}`);
    }
  }

  async function openDrawing(showLog = true) {
    if (S.busy) return;
    const raw = $("#pathInput").value.trim();
    if (!raw) { toast("请填写图纸路径", "err"); return; }
    if (showLog) log(`打开图纸：${raw}`);
    S.path = raw;
    S.selected = null;
    S.prevSrc = "";
    S.compare = false;
    $("#compareToggle").disabled = true;
    $("#compareToggle").classList.remove("primary");
    $("#compareBar").hidden = true;
    await refreshAll(true);
  }

  async function refreshAll(force = false) {
    if (!S.path || (S.busy && !force)) return;
    clearError();
    setBusy(true, "正在读取构件与问题…");
    $("#empty").hidden = true;
    try {
      const q = encodeURIComponent(S.path);
      const data = await apiGet(`/api/state?path=${q}`);
      S.data = data;
      S.path = data.drawing.path;
      $("#pathInput").value = data.drawing.path;
      renderAll();
      await loadPreview();
      log(`已读取 ${data.drawing.name}：${data.walls.length} 墙 / ${data.openings.length} 门窗 / ${data.rooms.length} 房间`);
    } catch (e) {
      error(e.message);
      $("#empty").hidden = false;
      $("#preview").hidden = true;
      $("#previewPrev").hidden = true;
    } finally {
      setBusy(false);
    }
  }

  async function loadPreview() {
    if (!S.data) return;
    const q = encodeURIComponent(S.data.drawing.path);
    const url = `/api/preview?path=${q}&v=${encodeURIComponent(S.data.drawing.mtime)}`;
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        $("#preview").src = url;
        $("#preview").hidden = false;
        $("#empty").hidden = true;
        S.currentSrc = url;
        $("#openPreviewBtn").disabled = false;
        applyCompare();
        resolve();
      };
      img.onerror = () => {
        error("预览导出失败，可先看构件与问题清单。");
        resolve();
      };
      img.src = url;
    });
  }

  // ---------- 渲染 ----------
  function renderAll() {
    renderMeta();
    renderComponents();
    renderIssues();
    renderSnapshots();
    renderInspector();
  }

  function renderMeta() {
    const d = S.data.drawing;
    const sc = d.scale ? `1:${fmt(d.scale)}` : "1:—";
    $("#drawingMeta").textContent = `${d.name} · ${sc} · ${(d.size / 1024).toFixed(0)} KB`;
    $("#statusText").textContent = `${S.data.walls.length} 墙 · ${S.data.openings.length} 门窗 · ${S.data.rooms.length} 房间`;
    const issues = S.data.issues || [];
    const badge = $("#issueBadge");
    badge.hidden = false;
    badge.textContent = `${issues.length} 问题`;
    badge.className = `badge ${issues.length ? "" : "clear"}`;
    $("#previewStat").textContent = `墙 ${S.data.walls.length} · 门窗 ${S.data.openings.length} · 房间 ${S.data.rooms.length} · 比例 ${sc}`;
    S.baseStat = $("#previewStat").textContent;
    updatePreviewStat();
  }

  function renderComponents() {
    if (!S.data) return;
    const filter = ($("#compSearch").value || "").trim().toLowerCase();
    const comps = S.data.components.filter((c) => {
      if (!filter) return true;
      const hay = `${c.block} ${Object.values(c.attrs).join(" ")} ${c.handle}`.toLowerCase();
      return hay.includes(filter);
    });
    $("#compCount").textContent = String(comps.length);

    const groups = { wall: [], opening: [], room: [], other: [] };
    for (const c of comps) groups[typeOf(c)].push(c);
    const names = { wall: "墙", opening: "门窗", room: "房间", other: "其他构件" };
    const chips = { wall: "WALL", opening: "OPEN", room: "ROOM", other: "OBJ" };
    const list = $("#compList");
    list.innerHTML = "";
    for (const kind of ["wall", "opening", "room", "other"]) {
      if (!groups[kind].length) continue;
      const h = document.createElement(kind === "other" ? "button" : "div");
      h.className = "comp-group" + (kind === "other" ? " toggle" : "");
      if (kind === "other") {
        h.type = "button";
        h.textContent = `${names[kind]} · ${groups[kind].length} ${S.showOther ? "收起" : "展开"}`;
        h.addEventListener("click", () => {
          S.showOther = !S.showOther;
          renderComponents();
        });
      } else {
        h.textContent = `${names[kind]} · ${groups[kind].length}`;
      }
      list.appendChild(h);
      if (kind === "other" && !S.showOther) continue;
      for (const c of groups[kind]) {
        const id = idOf(c);
        const b = document.createElement("button");
        b.type = "button";
        b.className = "comp-row" + (S.selected && S.selected.kind === kind && S.selected.id === id ? " selected" : "");
        b.dataset.kind = kind;
        b.dataset.id = id;
        const chipClass = kind === "wall" ? "" : kind === "opening" ? "open" : kind === "room" ? "room" : "other";
        b.innerHTML = `
          <span class="chip ${chipClass}">${chips[kind]}</span>
          <span class="comp-main">
            <span class="comp-id">${esc(id)}</span>
            <span class="comp-sub">${esc(summaryOf(kind, c))}</span>
          </span>
          <span class="comp-at">${fmt(c.at[0])},${fmt(c.at[1])}</span>`;
        b.addEventListener("click", () => selectComponent(kind, id));
        list.appendChild(b);
      }
    }
    if (!comps.length) {
      list.innerHTML = `<div class="placeholder">${filter ? "没有匹配的构件。" : "这张图没有可识别的 AA_ 构件。"}</div>`;
    }
  }

  function summaryOf(kind, c) {
    const a = c.attrs;
    if (kind === "wall") {
      return `${fmt(a.thick)} 厚 · ${fmt(a.len)} 长 · ${a.kind || "—"}${a.floor ? ` · ${a.floor} 层` : ""}`;
    }
    if (kind === "opening") {
      return `${fmt(a.width)}×${fmt(a.height)} · 墙 ${a.wallid || "—"} · 中心 ${fmt(a.pos)}`;
    }
    if (kind === "room") {
      return `${a.name || "未命名"} · ${areaText(a.area)} · 周长 ${fmt(a.perimeter)}`;
    }
    return c.block;
  }

  function findComponent(kind, id) {
    if (!S.data) return null;
    return S.data.components.find((c) => typeOf(c) === kind && idOf(c) === id) || null;
  }

  function selectById(id, preferredKind) {
    if (!S.data) return;
    const candidates = ["wall", "opening", "room"];
    const kinds = preferredKind ? [preferredKind, ...candidates.filter((k) => k !== preferredKind)] : candidates;
    for (const kind of kinds) {
      const c = findComponent(kind, id);
      if (c) return selectComponent(kind, id);
    }
    toast(`没找到构件 ${id}`, "err");
  }

  function selectComponent(kind, id) {
    S.selected = { kind, id };
    setTab("components");
    renderComponents();
    renderInspector();
    const row = Array.from(document.querySelectorAll(".comp-row"))
      .find((el) => el.dataset.kind === kind && el.dataset.id === id);
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  function renderInspector() {
    const box = $("#inspectorBody");
    const tag = $("#selectionTag");
    if (!S.selected || !S.data) {
      tag.textContent = "未选中构件";
      box.innerHTML = `<div class="placeholder">在构件列表点一条，这里显示可改属性。只改已有构件，不新建、不画线。</div>`;
      return;
    }
    const { kind, id } = S.selected;
    const c = findComponent(kind, id);
    if (!c) {
      tag.textContent = "构件已不存在";
      box.innerHTML = `<div class="placeholder">构件 ${esc(id)} 已不在当前图纸，刷新后重选。</div>`;
      return;
    }
    const a = c.attrs;
    tag.textContent = `${kind === "wall" ? "墙" : kind === "opening" ? "门窗" : "房间"} · ${id}`;
    const fields = [];
    if (kind === "wall") {
      fields.push(field("thick", "墙厚 mm", a.thick, "number"));
      fields.push(selectField("kind", "墙类型", a.kind, [
        ["EXTERNAL", "外墙"], ["INTERNAL", "内墙"], ["PARTITION", "隔墙"],
      ]));
      fields.push(field("mat", "材质", a.mat));
      fields.push(field("ax1", "轴号 1", a.ax1));
      fields.push(field("ax2", "轴号 2", a.ax2));
      fields.push(`<div class="field wide"><label>只读</label><input disabled value="长 ${esc(fmt(a.len))} mm · 层 ${esc(a.floor || "1")} · 根 ${esc(a.root || id)}"></div>`);
    } else if (kind === "opening") {
      fields.push(field("pos", "中心距墙起点 mm", a.pos, "number"));
      fields.push(field("width", "洞口宽 mm", a.width, "number"));
      fields.push(field("height", "洞口高 mm", a.height, "number"));
      fields.push(field("sill", "窗台高 mm", a.sill, "number"));
      fields.push(selectField("kind", "类型", a.kind, [
        ["DOOR", "门"], ["WINDOW", "窗"], ["DOORWIN", "门联窗"],
      ]));
      fields.push(field("frame", "框厚 mm", a.frame, "number"));
      fields.push(field("no", "门窗编号", a.no));
      fields.push(selectField("label_side", "编号侧", a.labelside, [
        ["in", "室内"], ["out", "室外"], ["auto", "自动"], ["leader", "引线"],
      ]));
      fields.push(`<div class="field wide"><label>只读</label><input disabled value="宿主墙 ${esc(a.wallid || "—")} · 属性 ${esc(a.width)}×${esc(a.height)}"></div>`);
    } else if (kind === "room") {
      fields.push(`<div class="field wide"><label>房间名称</label><input id="f-name" value="${esc(a.name)}"></div>`);
      fields.push(`<div class="field"><label>面积</label><input disabled value="${esc(areaText(a.area))}"></div>`);
      fields.push(`<div class="field"><label>周长 mm</label><input disabled value="${esc(fmt(a.perimeter))}"></div>`);
      fields.push(`<div class="field wide"><label>围合墙</label><input disabled value="${esc((a.walls || "").replaceAll(";", " / "))}"></div>`);
    }
    const attrs = Object.entries(a)
      .filter(([k]) => k !== "pts")
      .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
    box.innerHTML = `
      <div class="field-grid">${fields.join("")}</div>
      <div class="form-actions">
        <button id="applyEdit" class="btn primary">应用修改</button>
        <span class="hint">保存时由 CADCraft 重建，失败会回滚</span>
      </div>
      <details class="attrs">
        <summary>原始属性（${esc(c.handle)}）</summary>
        <table class="attr-table">${attrs}</table>
      </details>`;
    $("#applyEdit").addEventListener("click", () => applyEdit(kind, id, c));
  }

  function field(name, label, value, type = "text") {
    return `<div class="field"><label for="f-${name}">${esc(label)}</label>
      <input id="f-${name}" type="${type}" value="${esc(value)}" ${type === "number" ? 'step="any"' : ""}></div>`;
  }

  function selectField(name, label, value, opts) {
    const body = opts.map(([v, t]) => `<option value="${esc(v)}" ${v === value ? "selected" : ""}>${esc(t)}</option>`).join("");
    return `<div class="field"><label for="f-${name}">${esc(label)}</label>
      <select id="f-${name}">${body}</select></div>`;
  }

  function collectFields() {
    const out = {};
    for (const el of $$("#inspectorBody [id^='f-']")) {
      out[el.id.slice(2)] = el.value;
    }
    return out;
  }

  async function applyEdit(kind, id, c) {
    const fields = collectFields();
    const preview = kind === "wall" ? `墙厚 ${fields.thick} mm` :
      kind === "opening" ? `中心 ${fields.pos} / 宽 ${fields.width} / 高 ${fields.height}` :
      `名称「${fields.name}」`;
    if (!confirm(`确认修改 ${id}？\n${preview}\n\nCADCraft 会重建相关几何，失败自动回滚。`)) return;
    capturePrev();
    clearError();
    setBusy(true, "正在应用修改…");
    try {
      const res = await apiPost("/api/edit", { path: S.path, kind, id, fields });
      log(`修改 ${id} 成功：${JSON.stringify(res.result)}`, "ok");
      toast(`已修改 ${id}（已自动存快照）`, "ok");
      S.selected = { kind, id };
      await refreshAll(true);
    } catch (e) {
      error(`修改失败：${e.message}`);
      toast("修改失败，图纸未改", "err");
    } finally {
      setBusy(false);
    }
  }

  // ---------- 问题 ----------
  function renderIssues() {
    if (!S.data) return;
    const issues = S.data.issues || [];
    $("#issueCount").textContent = String(issues.length);
    const rec = S.data.reconcile || {};
    const aud = S.data.audit || {};
    $("#issueSummary").innerHTML =
      `<span>一致检查 <b>${esc(rec.count || 0)}</b></span>` +
      `<span>图面自检 <b>${esc(aud.count || 0)}</b></span>` +
      `<span>error <b>${esc(issues.filter((i) => i.level === "error").length)}</b></span>` +
      `<span>warn <b>${esc(issues.filter((i) => i.level === "warn").length)}</b></span>`;
    const list = $("#issuesList");
    list.innerHTML = "";
    if (!issues.length) {
      list.innerHTML = `<div class="placeholder">没有发现问题。改完构件后可再跑一次一致检查。</div>`;
      return;
    }
    for (const it of issues) {
      const row = document.createElement("div");
      row.className = `issue-row ${it.level === "warn" ? "warn" : "error"}`;
      const ref = String(it.ref || "").split("/")[0];
      row.innerHTML = `
        <span class="sev ${esc(it.level || "error")}"></span>
        <span>
          <span class="issue-kind">${esc(it.source || "")} · ${esc(it.kind || "")}${it.fixable ? '<span class="issue-fixable">可修</span>' : ""}</span>
          <span class="issue-msg">${esc(it.message || "")}</span>
          ${ref ? `<span class="issue-ref">${esc(ref)} →</span>` : ""}
        </span>`;
      if (ref) row.addEventListener("click", () => selectById(ref));
      list.appendChild(row);
    }
  }

  async function runAction(action, confirmText, busytText) {
    if (confirmText && !confirm(confirmText)) return;
    capturePrev();
    clearError();
    setBusy(true, busytText);
    try {
      const res = await apiPost("/api/action", { path: S.path, action });
      const r = res.result || res;
      log(`${action} 完成：${JSON.stringify(r).slice(0, 900)}`, "ok");
      if (r.fix_skipped) {
        toast(`已跳过：${r.fix_skipped}`, "err");
      } else if (action === "reconcile_fix" && (!r.fixed || !r.fixed.length)) {
        toast("没有可重建的房间面积（可能已一致）", "");
      } else {
        toast(`${action} 完成`, "ok");
      }
      await refreshAll(true);
    } catch (e) {
      error(`${action} 失败：${e.message}`);
      toast(`${action} 失败`, "err");
    } finally {
      setBusy(false);
    }
  }

  // ---------- 快照 ----------
  function renderSnapshots() {
    if (!S.data) return;
    const snaps = S.data.snapshots || [];
    $("#snapCount").textContent = String(snaps.length);
    const list = $("#snapshotList");
    list.innerHTML = "";
    if (!snaps.length) {
      list.innerHTML = `<div class="placeholder">还没有快照。改构件前先拍一张，回退是字节级还原。</div>`;
      return;
    }
    for (const s of snaps) {
      const row = document.createElement("div");
      row.className = "snapshot-row";
      const date = new Date(s.mtime * 1000).toLocaleString("zh-CN", { hour12: false });
      row.innerHTML = `
        <div>
          <div class="snapshot-name">${esc(s.id)}</div>
          <div class="snapshot-meta">${esc(date)} · ${(s.bytes / 1024).toFixed(0)} KB</div>
        </div>
        <button class="btn danger" type="button">回退</button>`;
      row.querySelector("button").addEventListener("click", () => restoreSnapshot(s));
      list.appendChild(row);
    }
  }

  async function snapshotNow() {
    const label = ($("#snapLabel").value || "manual").trim();
    capturePrev();
    clearError();
    setBusy(true, "正在拍快照…");
    try {
      const res = await apiPost("/api/action", { path: S.path, action: "checkpoint", label });
      const r = res.result || res;
      log(`快照：${r.id}`, "ok");
      toast(`快照已保存：${r.id}`, "ok");
      await refreshAll(true);
    } catch (e) {
      error(`快照失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function restoreSnapshot(s) {
    if (!confirm(`回退到快照？\n${s.id}\n\n当前图纸会被字节级覆盖，未保存的改动会丢失。`)) return;
    capturePrev();
    clearError();
    setBusy(true, "正在回退快照…");
    try {
      await apiPost("/api/action", { path: S.path, action: "restore", snapshot: s.id });
      log(`已回退：${s.id}`, "ok");
      toast("已回退到快照", "ok");
      S.selected = null;
      await refreshAll(true);
    } catch (e) {
      error(`回退失败：${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  // ---------- 对比 / 缩放 ----------
  function capturePrev() {
    if (!S.currentSrc) return;
    S.prevSrc = S.currentSrc;
    $("#compareToggle").disabled = false;
  }

  function applyCompare() {
    const split = Number($("#compareRange").value || 50);
    const prev = $("#previewPrev");
    const cur = $("#preview");
    if (S.compare && S.prevSrc && S.currentSrc) {
      prev.src = S.prevSrc;
      prev.hidden = false;
      cur.classList.remove("no-split");
      $("#previewStack").style.setProperty("--split", `${split}%`);
      $("#compareBar").hidden = false;
    } else {
      prev.hidden = true;
      cur.classList.add("no-split");
      $("#compareBar").hidden = true;
    }
  }

  function setZoom(pct) {
    S.zoom = Math.max(25, Math.min(320, pct));
    $("#previewStack").style.setProperty("--zoom", `${S.zoom}%`);
    updatePreviewStat();
  }

  function updatePreviewStat() {
    const base = S.baseStat || $("#previewStat").textContent;
    $("#previewStat").textContent = S.zoom === 100 ? base : `${base} · 缩放 ${S.zoom}%`;
  }

  // ---------- 标签 ----------
  function setTab(tab) {
    S.tab = tab;
    for (const b of $$(".tab")) b.classList.toggle("active", b.dataset.tab === tab);
    for (const pane of $$(".tab-pane")) pane.hidden = pane.id !== `pane-${tab}`;
  }

  // ---------- 绑定 ----------
  function bind() {
    $("#openBtn").addEventListener("click", () => openDrawing(true));
    $("#pathInput").addEventListener("keydown", (e) => { if (e.key === "Enter") openDrawing(true); });
    $("#refreshBtn").addEventListener("click", () => refreshAll());
    $("#runReconcileBtn").addEventListener("click", () => runAction("reconcile", "", "正在做一致检查…"));
    $("#runAuditBtn").addEventListener("click", () => runAction("audit", "", "正在做图面自检…"));
    $("#fixReconcileBtn").addEventListener("click", () => runAction(
      "reconcile_fix",
      "只重建房间面积；门窗/墙体本身有错时会跳过（fix_skipped），不会硬改。继续？",
      "正在修复房间面积…"
    ));
    $("#snapshotBtn").addEventListener("click", snapshotNow);
    $("#snapLabel").addEventListener("keydown", (e) => { if (e.key === "Enter") snapshotNow(); });
    $("#compSearch").addEventListener("input", () => renderComponents());
    $("#compareToggle").addEventListener("click", () => {
      S.compare = !S.compare;
      $("#compareToggle").classList.toggle("primary", S.compare);
      applyCompare();
    });
    $("#compareRange").addEventListener("input", applyCompare);
    $("#zoomIn").addEventListener("click", () => setZoom(S.zoom + 15));
    $("#zoomOut").addEventListener("click", () => setZoom(S.zoom - 15));
    $("#zoomFit").addEventListener("click", () => setZoom(100));
    $("#openPreviewBtn").addEventListener("click", () => {
      if (S.currentSrc) window.open(S.currentSrc, "_blank", "noopener");
    });
    $("#clearLog").addEventListener("click", () => { $("#logList").innerHTML = ""; });
    for (const b of $$(".tab")) b.addEventListener("click", () => setTab(b.dataset.tab));
    window.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "r") {
        e.preventDefault();
        refreshAll();
      }
    });
  }

  bind();
  log("面板就绪：只读预览 / 构件属性 / 问题 / 快照");
  loadConfig();
})();
