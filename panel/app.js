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
    proposalId: "",
    showAllChanges: true,
    filesDir: "",
    recent: [],
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
    $("#browseBtn").disabled = on;
    $("#refreshBtn").disabled = on;
    $("#runAuditBtn").disabled = on;
    $("#runReconcileBtn").disabled = on;
    $("#runVerifyBtn").disabled = on;
    $("#fixReconcileBtn").disabled = on;
    $("#snapshotBtn").disabled = on;
    for (const id of ["#acceptProposal", "#discardProposal"]) {
      const el = $(id);
      if (el) el.disabled = on || (id === "#acceptProposal" && S.data?.proposal?.stale);
    }
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
      S.recent = S.config.recent || [];
      $("#version").textContent = `v${S.config.version}`;
      $("#pathInput").value = S.config.default;
      if (S.config.default) await openDrawing(false);
    } catch (e) {
      error(`读取配置失败：${e.message}`);
    }
  }

  function renderRecent(rows = S.recent) {
    const list = $("#recentList");
    if (!rows || !rows.length) {
      list.innerHTML = '<div class="placeholder">还没有最近记录</div>';
      return;
    }
    list.innerHTML = rows.map((r) => `
      <button class="recent-item" data-path="${esc(r.path)}" title="${esc(r.rel || r.path)}">
        <strong>${esc(r.name)}</strong>
        <span>${esc(r.rel || r.path)}</span>
      </button>`).join("");
  }

  async function loadFiles(dir = "") {
    const q = dir ? `?dir=${encodeURIComponent(dir)}` : "";
    const list = $("#fileList");
    list.innerHTML = '<div class="placeholder">正在读取…</div>';
    try {
      const r = await apiGet(`/api/files${q}`);
      S.filesDir = r.dir;
      $("#pickerRoot").textContent = `根目录：${r.root}`;
      $("#pickerCwd").textContent = r.dir;
      $("#pickerUp").disabled = !r.parent;
      $("#pickerUp").dataset.dir = r.parent || "";
      const rows = [
        ...r.dirs.map((d) => `<button class="file-item dir" data-dir="${esc(d.path)}">
          <span class="ico">▸</span><span class="nm">${esc(d.name)}</span></button>`),
        ...r.files.map((f) => `<button class="file-item" data-path="${esc(f.path)}">
          <span class="ico">DXF</span><span class="nm">${esc(f.name)}</span>
          <span class="meta">${fmt(f.bytes / 1024)} KB</span></button>`),
      ];
      list.innerHTML = rows.length ? rows.join("") :
        '<div class="placeholder">这个文件夹里没有子文件夹或 .dxf 图纸</div>';
    } catch (e) {
      list.innerHTML = `<div class="placeholder">${esc(e.message)}</div>`;
    }
  }

  function openPicker() {
    if (S.busy) return;
    renderRecent();
    $("#pickerModal").hidden = false;
    loadFiles(S.filesDir || (S.config && S.config.root) || "");
  }

  function closePicker() {
    $("#pickerModal").hidden = true;
  }

  async function openDrawing(showLog = true, requested = "") {
    if (S.busy) return;
    if (requested) $("#pathInput").value = requested;
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
      const pid = data.proposal ? data.proposal.id : "";
      const newProposal = !!(pid && pid !== S.proposalId);
      S.proposalId = pid || "";
      S.data = data;
      S.path = data.drawing.path;
      S.filesDir = String(data.drawing.path || "").replace(/[\\/][^\\/]+$/, "");
      S.recent = data.recent || S.recent;
      $("#pathInput").value = data.drawing.path;
      renderAll();
      if (!$("#pickerModal").hidden) closePicker();
      if (newProposal) setTab("proposal");
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

  function loadImg(src) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve(true);
      img.onerror = () => resolve(false);
      img.src = src;
    });
  }

  function previewUrl(path, mtime = 0) {
    return `/api/preview?path=${encodeURIComponent(path)}&v=${encodeURIComponent(mtime)}`;
  }

  async function loadPreview() {
    if (!S.data) return;
    const d = S.data.drawing;
    const mainUrl = previewUrl(d.path, d.mtime);
    const p = S.data.proposal;
    if (p && p.id) {
      const afterUrl = `/api/proposal/preview?path=${encodeURIComponent(d.path)}&v=${encodeURIComponent(p.id)}`;
      const [afterOk, beforeOk] = await Promise.all([loadImg(afterUrl), loadImg(mainUrl)]);
      if (afterOk) {
        $("#preview").src = afterUrl;
        $("#preview").hidden = false;
        $("#empty").hidden = true;
        S.currentSrc = afterUrl;
        $("#openPreviewBtn").disabled = false;
        if (beforeOk) {
          S.prevSrc = mainUrl;
          $("#previewPrev").src = mainUrl;
          $("#compareToggle").disabled = false;
          $("#compareToggle").classList.add("primary");
          S.compare = true;
        } else {
          S.compare = false;
          $("#compareToggle").disabled = true;
          $("#compareToggle").classList.remove("primary");
        }
        applyCompare();
        renderOverlay();
        return;
      }
    }
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        $("#preview").src = mainUrl;
        $("#preview").hidden = false;
        $("#empty").hidden = true;
        S.currentSrc = mainUrl;
        $("#openPreviewBtn").disabled = false;
        applyCompare();
        renderOverlay();
        resolve();
      };
      img.onerror = () => {
        error("预览导出失败，可先看构件与问题清单。");
        resolve();
      };
      img.src = mainUrl;
    });
  }

  // ---------- 渲染 ----------
  function renderAll() {
    renderMeta();
    renderComponents();
    renderIssues();
    renderProposal();
    renderOverlay();
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

  function focusComponent(kind, id) {
    S.selected = { kind, id };
    renderComponents();
    renderInspector();
    renderOverlay();
  }

  function selectComponent(kind, id) {
    focusComponent(kind, id);
    setTab("components");
    const row = Array.from(document.querySelectorAll(".comp-row"))
      .find((el) => el.dataset.kind === kind && el.dataset.id === id);
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  const KIND_LABEL = { wall: "墙", opening: "门窗", room: "房间", other: "其他" };

  function overlaySource() {
    const p = S.data && S.data.proposal;
    return (p && p.geometry) ? p.geometry : (S.data || {});
  }

  function overlayView() {
    const p = S.data && S.data.proposal;
    if (p && p.view && p.view.window) return p.view;
    return S.data && S.data.view;
  }

  function worldBox(kind, id, src) {
    if (!src) return null;
    if (kind === "wall") {
      const w = (src.walls || []).find((x) => x.id === id);
      if (!w) return null;
      const half = (Number(w.thick) || 0) / 2;
      const xs = [w.p1[0], w.p2[0]].sort((a, b) => a - b);
      const ys = [w.p1[1], w.p2[1]].sort((a, b) => a - b);
      return [xs[0] - half, ys[0] - half, xs[1] + half, ys[1] + half];
    }
    if (kind === "opening") {
      const o = (src.openings || []).find((x) => x.id === id);
      if (!o) return null;
      const w = (src.walls || []).find((x) => x.id === o.wallid);
      if (!w) return null;
      const dx0 = w.p2[0] - w.p1[0], dy0 = w.p2[1] - w.p1[1];
      const len = Math.hypot(dx0, dy0) || Number(w.len) || 1;
      const dx = dx0 / len, dy = dy0 / len;
      const hw = Number(o.width) / 2, ht = (Number(w.thick) || 120) / 2;
      const cx = w.p1[0] + dx * Number(o.pos);
      const cy = w.p1[1] + dy * Number(o.pos);
      const pts = [
        [cx + dx * hw - dy * ht, cy + dy * hw + dx * ht],
        [cx + dx * hw + dy * ht, cy + dy * hw - dx * ht],
        [cx - dx * hw + dy * ht, cy - dy * hw - dx * ht],
        [cx - dx * hw - dy * ht, cy - dy * hw + dx * ht],
      ];
      const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
      return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    }
    if (kind === "room") {
      const r = (src.rooms || []).find((x) => x.id === id);
      if (!r || !r.pts || !r.pts.length) return null;
      const xs = r.pts.map((p) => p[0]), ys = r.pts.map((p) => p[1]);
      return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    }
    const c = (S.data && S.data.components || []).find((x) => typeOf(x) === "other" && idOf(x) === id);
    const v = overlayView();
    if (!c || !v) return null;
    const [x0, , x1] = v.window;
    const half = Math.max(30, (x1 - x0) * 0.012);
    return [c.at[0] - half, c.at[1] - half, c.at[0] + half, c.at[1] + half];
  }

  function kindOfBlock(block) {
    if (String(block || "").startsWith("AA_WALL_")) return "wall";
    if (String(block || "").startsWith("AA_OPENING_")) return "opening";
    if (String(block || "").startsWith("AA_ROOM_")) return "room";
    return "other";
  }

  function renderOverlay() {
    const layer = $("#hlLayer");
    if (!layer) return;
    const img = $("#preview");
    const sel = S.selected;
    const p = S.data && S.data.proposal;
    const view = overlayView();
    if (!view || !view.window || !S.data || img.hidden) {
      layer.hidden = true;
      layer.innerHTML = "";
      return;
    }

    const items = [];
    const pushBox = (kind, id, phase, cls, label) => {
      if (!kind || !id) return;
      const src = phase === "before" ? S.data : overlaySource();
      const box = worldBox(kind, id, src);
      if (!box) return;
      items.push({ kind, id, phase, cls, label, box, selected: false });
    };

    if (p && p.id && S.showAllChanges) {
      for (const c of (p.changes || [])) {
        const kind = kindOfBlock(c.block);
        if (kind === "other") continue;
        if (c.change === "added") {
          pushBox(kind, c.id, "after", "added", `新增 ${c.id}`);
        } else if (c.change === "removed") {
          pushBox(kind, c.id, "before", "removed", `删除 ${c.id}`);
        } else {
          pushBox(kind, c.id, "before", "before", `改前 ${c.id}`);
          pushBox(kind, c.id, "after", "after", `改后 ${c.id}`);
        }
      }
    }

    if (sel) {
      const hits = items.filter((it) => it.kind === sel.kind && it.id === sel.id);
      if (hits.length) {
        for (const it of hits) it.selected = true;
      } else {
        pushBox(sel.kind, sel.id, "after", "after", sel.id);
        if (items.length) items[items.length - 1].selected = true;
      }
    }

    if (!items.length) {
      layer.hidden = true;
      layer.innerHTML = "";
      return;
    }

    const [x0, y0, x1, y1] = view.window;
    items.sort((a, b) => Number(a.selected) - Number(b.selected));
    layer.innerHTML = items.map((it) => {
      const [bx0, by0, bx1, by1] = it.box;
      const left = Math.max(0, Math.min(100, (bx0 - x0) / (x1 - x0) * 100));
      const right = Math.max(0, Math.min(100, (bx1 - x0) / (x1 - x0) * 100));
      const top = Math.max(0, Math.min(100, (y1 - by1) / (y1 - y0) * 100));
      const bottom = Math.max(0, Math.min(100, (y1 - by0) / (y1 - y0) * 100));
      const w = Math.max(0.8, right - left);
      const h = Math.max(0.8, bottom - top);
      const cls = `hl-box ${it.cls}${it.selected ? " selected" : ""}`;
      const tagCls = `hl-tag ${it.cls}${it.selected ? " selected" : ""}`;
      const tag = it.selected ? `${it.label} · ${KIND_LABEL[it.kind] || it.kind}` : it.label;
      return `<div class="${cls}" style="left:${left}%;top:${top}%;width:${w}%;height:${h}%">
        <span class="${tagCls}">${esc(tag)}</span>
      </div>`;
    }).join("");
    layer.hidden = false;
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
      const p = S.data && S.data.proposal;
      const ch = p && p.changes ? p.changes.find((x) => x.id === id) : null;
      if (ch && ch.change === "added") {
        tag.textContent = "新增构件（预演）";
        box.innerHTML = `<div class="placeholder">构件 ${esc(id)} 只存在于这次 AI 变更集里，接受后才写进图纸。预览图上的金框就是它的落点。</div>`;
        return;
      }
      if (ch && ch.change === "removed") {
        tag.textContent = "待删除构件";
        box.innerHTML = `<div class="placeholder">构件 ${esc(id)} 将在接受变更集后被删除；金框标的是它现在的原位置。</div>`;
        return;
      }
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
    const ver = S.data.verify || {};
    $("#issueSummary").innerHTML =
      `<span>一致检查 <b>${esc(rec.count || 0)}</b></span>` +
      `<span>图面自检 <b>${esc(aud.count || 0)}</b></span>` +
      `<span>全图复核 <b>${esc(ver.count || 0)}</b></span>` +
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
          ${it.suggestion ? `<span class="issue-suggestion">建议：${esc(it.suggestion)}</span>` : ""}
          ${ref ? `<span class="issue-ref">${esc(ref)} →</span>` : ""}
        </span>`;
      if (ref) row.addEventListener("click", () => selectById(ref));
      list.appendChild(row);
    }
  }

  // ---------- AI 变更 ----------
  const FIELD_LABEL = {
    thick: "墙厚", kind: "类型", mat: "材质", ax1: "轴号1", ax2: "轴号2",
    name: "名称", pos: "中心距", width: "宽", height: "高", sill: "窗台",
    frame: "框厚", no: "编号", labelside: "编号侧", len: "长", area: "面积",
    perimeter: "周长", walls: "围合墙", floor: "层", at: "位置", rotation: "转角",
  };
  const proposalValue = (v) => {
    if (v === null || v === undefined || v === "") return "—";
    if (Array.isArray(v)) return v.join(", ");
    return String(v);
  };

  function renderProposal() {
    const box = $("#proposalPane");
    const p = S.data && S.data.proposal;
    $("#proposalCount").textContent = String(p ? (p.ops_count || 0) : 0);
    if (!p || !p.id) {
      box.innerHTML = `<div class="placeholder">当前没有待确认的 AI 变更。AI 通过 <code>/api/proposal</code> 提交后，这里会列出改前/改后和影响的问题。</div>`;
      return;
    }
    const sum = p.summary || {};
    const changed = (sum.changed || 0) + (sum.added || 0) + (sum.removed || 0);
    const created = p.created ? new Date(p.created * 1000).toLocaleString("zh-CN", { hour12: false }) : "";
    const rows = (p.changes || []).slice(0, 40);
    const stale = !!p.stale;
    const changesHtml = rows.map((c) => {
      const tag = c.change === "added" ? "新增" : c.change === "removed" ? "删除" : "修改";
      const cls = c.change === "added" || c.change === "removed" ? c.change : "";
      const kindKey = c.block.startsWith("AA_WALL_") ? "wall" :
        c.block.startsWith("AA_OPENING_") ? "opening" :
        c.block.startsWith("AA_ROOM_") ? "room" : "other";
      const fields = (c.fields || []).slice(0, c.change === "changed" ? 8 : 5).map((f) => `
        <div class="diff-field">
          <span class="diff-key">${esc(FIELD_LABEL[f.name] || f.name)}</span>
          <span class="diff-old">${esc(proposalValue(f.before))}</span>
          <span class="diff-arrow">→</span>
          <span class="diff-new">${esc(proposalValue(f.after))}</span>
        </div>`).join("");
      const more = (c.fields || []).length > (c.change === "changed" ? 8 : 5)
        ? `<div class="proposal-more">另有 ${(c.fields || []).length - (c.change === "changed" ? 8 : 5)} 个属性</div>` : "";
      return `
        <div class="diff-row ${cls}" data-kind="${kindKey}" data-id="${esc(c.id)}" title="点击在预览图上定位">
          <div class="diff-line">
            <span class="diff-tag ${cls}">${tag}</span>
            <span class="diff-id">${esc(c.id)}</span>
            <span class="diff-kind">${esc(c.kind)}</span>
          </div>
          <div class="diff-fields">${fields}${more}</div>
        </div>`;
    }).join("");
    const newIssues = (p.new_issues || []).slice(0, 2).map((it) =>
      `<div>· ${esc(it.kind || "")} ${esc(it.ref || "")}：${esc(it.message || "")}</div>`).join("");
    const fixedIssues = (p.fixed_issues || []).slice(0, 2).map((it) =>
      `<div>· ${esc(it.kind || "")} ${esc(it.ref || "")}：${esc(it.message || "")}</div>`).join("");
    box.innerHTML = `
      <div class="proposal-card">
        <div class="proposal-head">
          <div>
            <div class="proposal-title">${esc(p.title || "AI 变更集")}</div>
            <div class="proposal-kicker">${esc(p.id)}${created ? ` · ${esc(created)}` : ""}</div>
          </div>
          <div class="proposal-head-right">
            <label class="proposal-toggle" title="在预览图上同时框出这次变更的全部构件">
              <input id="showAllChanges" type="checkbox" ${S.showAllChanges ? "checked" : ""}>
              <span>全部改动</span>
            </label>
            <span class="proposal-badge ${stale ? "stale" : ""}">${stale ? "已失效" : "待确认"}</span>
          </div>
        </div>
        ${stale ? `<div class="proposal-alert stale">原图在预演之后变过，这份变更集不能直接写入。让 AI 按当前图纸重新提交。</div>` : ""}
        <div class="proposal-sum">
          <div><b>${esc(sum.changed || 0)}</b>修改</div>
          <div><b>${esc(sum.added || 0)}</b>新增</div>
          <div><b>${esc(sum.removed || 0)}</b>删除</div>
        </div>
        <div class="overlay-legend">
          <span class="before">改前</span>
          <span class="after">改后</span>
          <span class="added">新增</span>
          <span class="removed">删除</span>
          <em>预览图上同时标出</em>
        </div>
        <div class="proposal-kicker">${p.ops_count || 0} 项 AI 操作 · 共 ${changed} 个构件变化</div>
        ${newIssues ? `<div class="proposal-alert new">新增问题 ${p.new_issues.length} 条${newIssues}</div>` : ""}
        ${fixedIssues ? `<div class="proposal-alert fixed">消除问题 ${p.fixed_issues.length} 条${fixedIssues}</div>` : ""}
        <div class="diff-head"><span>构件差异</span><span>改前 → 改后</span></div>
        ${changesHtml || `<div class="placeholder">变更集执行成功，但没有识别到构件属性差异（可能操作是幂等的）。</div>`}
        <div class="proposal-actions">
          <button id="acceptProposal" class="btn primary" type="button" ${stale ? "disabled" : ""}>接受并写入</button>
          <button id="discardProposal" class="btn danger" type="button">整批放弃</button>
        </div>
      </div>`;
    const accept = $("#acceptProposal");
    const discard = $("#discardProposal");
    const allChanges = $("#showAllChanges");
    if (accept) accept.addEventListener("click", commitProposal);
    if (discard) discard.addEventListener("click", discardProposal);
    if (allChanges) allChanges.addEventListener("change", () => {
      S.showAllChanges = allChanges.checked;
      renderOverlay();
    });
    for (const row of box.querySelectorAll(".diff-row")) {
      row.addEventListener("click", () => focusComponent(row.dataset.kind, row.dataset.id));
    }
  }

  async function commitProposal() {
    const p = S.data && S.data.proposal;
    if (!p || !p.id) return;
    const sum = p.summary || {};
    if (!confirm(`接受 AI 变更集？\n${p.title || p.id}\n修改 ${sum.changed || 0} / 新增 ${sum.added || 0} / 删除 ${sum.removed || 0}\n\n会先存 before-batch 快照，再整图写入。`)) return;
    clearError();
    setBusy(true, "正在写入变更集…");
    try {
      const res = await apiPost("/api/proposal/commit", { path: S.path });
      const r = res.result || res;
      log(`接受变更集 ${p.id}，快照 ${r.checkpoint}`, "ok");
      toast("AI 变更集已写入", "ok");
      S.selected = null;
      await refreshAll(true);
      setTab("components");
    } catch (e) {
      error(`写入变更集失败：${e.message}`);
      toast("变更集未写入，图纸未改", "err");
    } finally {
      setBusy(false);
    }
  }

  async function discardProposal() {
    const p = S.data && S.data.proposal;
    if (!p || !p.id) return;
    if (!confirm(`整批放弃 AI 变更集？\n${p.title || p.id}\n原图不会被修改。`)) return;
    clearError();
    setBusy(true, "正在放弃变更集…");
    try {
      await apiPost("/api/proposal/discard", { path: S.path });
      log(`已放弃变更集 ${p.id}`, "ok");
      toast("已放弃 AI 变更集", "ok");
      S.compare = false;
      S.prevSrc = "";
      $("#compareToggle").classList.remove("primary");
      $("#compareToggle").disabled = true;
      $("#compareBar").hidden = true;
      S.selected = null;
      await refreshAll(true);
      setTab("components");
    } catch (e) {
      error(`放弃变更集失败：${e.message}`);
    } finally {
      setBusy(false);
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
        const done = r.fixed && r.fixed.length ? `已修 ${r.fixed.length} 项；` : "";
        toast(`${done}${r.fix_skipped}`, "err");
      } else if (action === "reconcile_fix" && (!r.fixed || !r.fixed.length)) {
        toast("没有可自动修复的问题；有歧义的项请看建议", "");
      } else if (action === "reconcile_fix") {
        toast(`已自动修复 ${r.fixed.length} 项`, "ok");
      } else if (action === "verify") {
        toast(`全图复核：${r.errors || 0} error / ${r.warnings || 0} warn`,
              r.errors ? "err" : "ok");
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
    $("#browseBtn").addEventListener("click", openPicker);
    $("#pickerClose").addEventListener("click", closePicker);
    $("#pickerUp").addEventListener("click", () => loadFiles($("#pickerUp").dataset.dir || ""));
    $("#pickerOpenPath").addEventListener("click", () => {
      const p = $("#pickerPath").value.trim();
      if (p) openDrawing(true, p);
    });
    $("#pickerPath").addEventListener("keydown", (e) => {
      if (e.key === "Enter") $("#pickerOpenPath").click();
    });
    $("#recentList").addEventListener("click", (e) => {
      const b = e.target.closest(".recent-item");
      if (b) openDrawing(true, b.dataset.path || "");
    });
    $("#fileList").addEventListener("click", (e) => {
      const b = e.target.closest(".file-item");
      if (!b) return;
      if (b.dataset.dir) loadFiles(b.dataset.dir);
      else if (b.dataset.path) openDrawing(true, b.dataset.path);
    });
    $("#pickerModal").addEventListener("click", (e) => {
      if (e.target === $("#pickerModal")) closePicker();
    });
    $("#pathInput").addEventListener("keydown", (e) => { if (e.key === "Enter") openDrawing(true); });
    $("#refreshBtn").addEventListener("click", () => refreshAll());
    $("#runReconcileBtn").addEventListener("click", () => runAction("reconcile", "", "正在做一致检查…"));
    $("#runAuditBtn").addEventListener("click", () => runAction("audit", "", "正在做图面自检…"));
    $("#runVerifyBtn").addEventListener("click", () => runAction("verify", "", "正在做全图复核…"));
    $("#fixReconcileBtn").addEventListener("click", () => runAction(
      "reconcile_fix",
      "自动收尾只做意图明确的事：删除无门窗/房间引用的零长墙、重挂唯一可匹配的悬空门窗、夹回放得下的越界洞口、重建房间面积；有歧义的只列建议，不硬改。继续？",
      "正在自动收尾…"
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
      if (e.key === "Escape" && !$("#pickerModal").hidden) {
        closePicker();
        return;
      }
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
