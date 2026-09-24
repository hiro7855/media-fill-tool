"use strict";

// 复核列顺序,必须与 src/fields.py flat_columns() 一致
const MEDIA = ["媒体名称", "姓名", "职位", "电话", "身份证号", "收款方式", "收款账号", "开户行"];
const LEG_FIELDS = ["方式", "日期", "出发城市", "到达城市", "航班车次", "出发时间", "到达时间", "航站楼"];
const LEGS = ["去程", "返程"];
const COLS = [...MEDIA, ...LEGS.flatMap(l => LEG_FIELDS.map(f => `${l}-${f}`))];

const state = { activity: null, records: [], applied: {}, step: 1, hasFiles: false, lastPreview: null };
let pollTimer = null;

const q = (sel, root = document) => root.querySelector(sel);
const qa = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const enc = encodeURIComponent;

// ---------------- fetch 封装 ----------------
async function api(method, url, body, isForm) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) { opts.body = body; }
    else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  }
  const r = await fetch(url, opts);
  let data = {};
  try { data = await r.json(); } catch (e) { /* 空响应 */ }
  if (!r.ok) { throw new Error(data.error || `请求失败(HTTP ${r.status})`); }
  return data;
}

// ---------------- 提示 ----------------
let toastTimer = null;
function toast(msg, kind = "") {
  const el = q("#toast");
  el.textContent = msg;
  el.className = "toast show " + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast " + kind; }, 2600);
}
function setStatus(sel, msg, kind = "muted") {
  const el = q(sel);
  if (!el) return;
  el.textContent = msg;
  el.className = "status " + kind;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ================= 步骤流程(① 选活动 · ② 资料识别 · ③ 回填飞书) =================
const STEP_NEEDS_ACTIVITY = { 1: false, 2: true, 3: true };
const GUARD_HTML = {
  2: '<div class="eg-title">还没选活动</div><div>请先在①「选活动」里选择或新建一个活动,再来上传和识别资料。</div>',
  3: '<div class="eg-title">还没选活动</div><div>请先在①「选活动」里选择活动,并完成资料识别。</div>',
};

function stepDone(n) {
  if (n === 1) return !!state.activity;
  if (n === 2) return state.records.length > 0;
  if (n === 3) return Object.keys(state.applied || {}).length > 0;
  return false;
}

function renderNav() {
  qa(".part-btn").forEach(b => {
    const n = +b.dataset.part;
    b.classList.toggle("active", n === state.step);
    b.classList.toggle("done", stepDone(n) && n !== state.step);
    b.classList.toggle("locked", STEP_NEEDS_ACTIVITY[n] && !state.activity);
  });
}

function goStep(n) {
  if (STEP_NEEDS_ACTIVITY[n] && !state.activity) {
    toast("请先在①「选活动」里选择活动", "err");
    n = 1;
  }
  state.step = n;
  qa(".step-panel").forEach(p => p.classList.toggle("active", p.id === "part-" + n));
  renderNav();

  // 空状态守卫:需要活动的步骤,没选活动时只显示引导
  const guard = q(`.empty-guard[data-guard="${n}"]`);
  const bodyEl = q(`.step-body[data-body="${n}"]`);
  if (guard && bodyEl) {
    const blocked = STEP_NEEDS_ACTIVITY[n] && !state.activity;
    guard.style.display = blocked ? "block" : "none";
    guard.innerHTML = blocked ? GUARD_HTML[n] : "";
    bodyEl.style.display = blocked ? "none" : "block";
  }

  if (n === 1) loadActivities();
  if (n === 2 && state.activity) { loadFiles(); loadRecords(true); }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// 步骤按钮 + 底部「下一步/上一步」按钮
qa(".part-btn").forEach(b => b.addEventListener("click", () => {
  const n = +b.dataset.part;
  if (b.classList.contains("locked")) { toast("请先在①「选活动」里选择活动", "err"); return; }
  goStep(n);
}));
qa("[data-goto]").forEach(b => b.addEventListener("click", () => goStep(+b.dataset.goto)));
q("#activity-badge").addEventListener("click", () => goStep(1));

function updateBadge() {
  const el = q("#activity-badge");
  el.innerHTML = state.activity ? `当前活动:<b>${escapeHtml(state.activity)}</b>` : "未选择活动";
  const b = q("#to-part-2");
  if (b) b.disabled = !state.activity;
}

// ================= 设置浮层 =================
function openSettings() { loadConfig().catch(e => toast(e.message, "err")); q("#settings-overlay").classList.add("show"); }
function closeSettings() { q("#settings-overlay").classList.remove("show"); }
q("#btn-gear").addEventListener("click", openSettings);
q("#btn-close-settings").addEventListener("click", closeSettings);
q("#btn-close-settings-2").addEventListener("click", closeSettings);
q("#settings-overlay").addEventListener("click", e => { if (e.target.id === "settings-overlay") closeSettings(); });

async function loadConfig() {
  const c = await api("GET", "/api/config");
  q("#relay-base").value = c.relay.base_url || "";
  q("#relay-model").value = c.relay.model || "";
  q("#relay-timeout").value = c.relay.timeout || 120;
  q("#relay-key").value = "";
  q("#relay-key").placeholder = c.relay.has_api_key ? c.relay.api_key_masked + "(留空则不改)" : "未设置";
  q("#fs-appid").value = c.feishu.app_id || "";
  q("#fs-secret").value = "";
  q("#fs-secret").placeholder = c.feishu.has_app_secret ? c.feishu.app_secret_masked + "(留空则不改)" : "未设置";
  q("#fs-target").value = c.feishu.target_url || "";
}

q("#btn-save-config").addEventListener("click", async () => {
  try {
    await api("POST", "/api/config", {
      relay: {
        base_url: q("#relay-base").value, model: q("#relay-model").value,
        timeout: q("#relay-timeout").value, api_key: q("#relay-key").value,
      },
      feishu: {
        app_id: q("#fs-appid").value, app_secret: q("#fs-secret").value,
        target_url: q("#fs-target").value,
      },
    });
    toast("设置已保存", "ok");
    loadConfig();
  } catch (e) { toast(e.message, "err"); }
});

q("#btn-test-relay").addEventListener("click", async () => {
  setStatus("#st-relay", "检查中…", "muted");
  try {
    const r = await api("POST", "/api/selfcheck/relay");
    setStatus("#st-relay", r.detail, r.ok ? "ok" : "err");
  } catch (e) { setStatus("#st-relay", e.message, "err"); }
});
q("#btn-test-feishu").addEventListener("click", async () => {
  setStatus("#st-feishu", "检查中…", "muted");
  try {
    const r = await api("POST", "/api/selfcheck/feishu");
    setStatus("#st-feishu", r.detail, r.ok ? "ok" : "err");
  } catch (e) { setStatus("#st-feishu", e.message, "err"); }
});

// ================= ① 活动 =================
async function loadActivities() {
  try {
    const { activities } = await api("GET", "/api/activities");
    const box = q("#act-table-wrap");
    if (!activities.length) {
      box.innerHTML = '<div class="empty">还没有活动。在上面新建一个,就会出现在这里。</div>';
      return;
    }
    const rows = activities.map(a => {
      const sel = a.name === state.activity;
      const applied = Object.keys(a.applied || {}).length;
      const statusPill = applied ? '<span class="pill green">已回填</span>'
        : a.has_records ? '<span class="pill blue">待回填</span>'
        : a.n_files ? '<span class="pill amber">待识别</span>'
        : '<span class="pill gray">待上传</span>';
      const rec = a.has_records ? `${a.n_records} 条` : "—";
      const upd = a.updated_at ? escapeHtml(String(a.updated_at).replace("T", " ").slice(0, 16)) : "—";
      return `<tr class="act-row${sel ? " selected" : ""}" data-name="${escapeHtml(a.name)}">
        <td class="an">${escapeHtml(a.name)}</td>
        <td>${a.n_units} 单元 / ${a.n_files} 文件</td>
        <td>${rec}</td>
        <td>${statusPill}</td>
        <td class="upd">${upd}</td>
        <td><button class="btn small ${sel ? "enter-cur" : "enter-act"}" data-name="${escapeHtml(a.name)}">${sel ? "当前" : "进入"}</button></td>
      </tr>`;
    }).join("");
    box.innerHTML = `<table class="act-table">
      <thead><tr><th>活动名称</th><th>资料</th><th>记录</th><th>状态</th><th>更新时间</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table>`;
    qa(".act-row").forEach(tr => tr.addEventListener("click", () => {
      if (tr.dataset.name === state.activity) { goStep(2); }        // 当前活动:点整行即进入
      else { selectActivity(tr.dataset.name); loadActivities(); }    // 非当前:只选中(显示上变化),不跳转
    }));
    qa(".enter-act").forEach(b => b.addEventListener("click", e => {
      e.stopPropagation();
      selectActivity(b.dataset.name);
      goStep(2);
    }));
    qa(".enter-cur").forEach(b => b.addEventListener("click", e => {
      e.stopPropagation();
      goStep(2);
    }));
  } catch (e) { toast(e.message, "err"); }
}

q("#btn-create-act").addEventListener("click", async () => {
  const name = q("#new-act-name").value.trim();
  if (!name) { toast("请输入活动名称", "err"); return; }
  try {
    await api("POST", "/api/activities", { name });
    q("#new-act-name").value = "";
    selectActivity(name);
    toast("已创建活动,来上传资料吧", "ok");
    goStep(2);
  } catch (e) { toast(e.message, "err"); }
});
q("#new-act-name").addEventListener("keydown", e => { if (e.key === "Enter") q("#btn-create-act").click(); });

function selectActivity(name) {
  state.activity = name;
  state.records = [];
  state.applied = {};
  state.hasFiles = false;
  state.lastPreview = null;
  updateBadge();
  renderNav();
  q("#review-card").style.display = "none";
  q("#preview-card").style.display = "none";
  const pw = q("#progress-wrap");
  if (pw) pw.style.display = "none";
  ["#st-upload", "#st-extract", "#st-records", "#st-apply", "#st-write"].forEach(s => setStatus(s, ""));
}

async function loadFiles() {
  if (!state.activity) return;
  try {
    const r = await api("GET", `/api/activities/${enc(state.activity)}/files`);
    const box = q("#file-units");
    const units = r.units || {};
    const names = Object.keys(units);
    state.hasFiles = names.some(u => (units[u] || []).length);
    renderNav();
    if (!names.length) { box.innerHTML = '<div class="hint" style="margin-top:12px">还没有文件。</div>'; return; }
    box.innerHTML = names.map(u =>
      `<div class="file-unit"><div class="u">${escapeHtml(u)}</div><div class="fs">${units[u].map(escapeHtml).join("、") || "(空)"}</div></div>`
    ).join("");
  } catch (e) { /* 忽略 */ }
}

// 上传:点击 + 拖拽
const dz = q("#dropzone");
const fileInput = q("#file-input");
dz.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => { if (fileInput.files.length) uploadFiles(fileInput.files); fileInput.value = ""; });
["dragover", "dragenter"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("drag"); }));
dz.addEventListener("drop", e => { if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files); });

async function uploadFiles(fileList) {
  if (!state.activity) { toast("请先选择活动", "err"); return; }
  const fd = new FormData();
  fd.append("unit", q("#unit-name").value.trim());
  Array.from(fileList).forEach(f => fd.append("files", f));
  setStatus("#st-upload", "上传中…", "muted");
  try {
    const r = await api("POST", `/api/activities/${enc(state.activity)}/upload`, fd, true);
    const okN = r.saved.length, skN = r.skipped.length;
    let msg = `已上传 ${okN} 个到单元「${r.unit}」`;
    if (skN) msg += `,跳过 ${skN} 个:` + r.skipped.map(s => `${s.name}(${s.reason})`).join("、");
    setStatus("#st-upload", msg, skN ? "err" : "ok");
    loadFiles();
  } catch (e) { setStatus("#st-upload", e.message, "err"); }
}

// ================= ③ 识别 =================
q("#btn-extract").addEventListener("click", startExtract);
q("#btn-reload-records").addEventListener("click", () => loadRecords(false));

async function startExtract() {
  if (!state.activity) { toast("请先在①「选活动」里选择活动", "err"); return; }
  try {
    q("#progress-wrap").style.display = "block";
    q("#extract-log").textContent = "";
    setBar(0, "启动中…");
    setStatus("#st-extract", "识别进行中…", "muted");
    q("#btn-extract").disabled = true;
    const { job_id } = await api("POST", `/api/activities/${enc(state.activity)}/extract`);
    pollJob(job_id);
  } catch (e) {
    q("#btn-extract").disabled = false;
    setStatus("#st-extract", e.message, "err");
  }
}

function setBar(pct, label) {
  q("#progress-bar").style.width = pct + "%";
  if (label !== undefined) q("#progress-label").textContent = label;
}

function pollJob(jobId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const j = await api("GET", `/api/jobs/${jobId}`);
      const pct = j.total ? Math.round((j.done / j.total) * 100) : (j.status === "done" ? 100 : 5);
      const cur = j.current ? `:${j.current}` : "";
      setBar(pct, j.total ? `正在识别 ${j.done}/${j.total}${cur}` : "正在识别…");
      q("#extract-log").textContent = (j.logs || []).join("\n");
      q("#extract-log").scrollTop = q("#extract-log").scrollHeight;
      if (j.status === "done" || j.status === "error") {
        clearInterval(pollTimer);
        q("#btn-extract").disabled = false;
        if (j.status === "done") {
          setBar(100, `识别完成:共 ${j.n_records} 条记录`);
          setStatus("#st-extract", "识别完成,请在下方核对", "ok");
          loadRecords(false);
        } else {
          setStatus("#st-extract", "识别失败:" + (j.error || ""), "err");
        }
      }
    } catch (e) {
      clearInterval(pollTimer);
      q("#btn-extract").disabled = false;
      setStatus("#st-extract", e.message, "err");
    }
  }, 1000);
}

async function loadRecords(silent) {
  if (!state.activity) return;
  try {
    const data = await api("GET", `/api/activities/${enc(state.activity)}/records`);
    state.records = data.records || [];
    state.applied = data.applied || {};
    renderNav();
    if (!state.records.length) {
      q("#review-card").style.display = silent ? "none" : "block";
      if (!silent) renderReview();
      return;
    }
    q("#review-card").style.display = "block";
    renderReview();
  } catch (e) { if (!silent) toast(e.message, "err"); }
}

// ---- 核对区渲染 ----
function personName(rec, i) {
  const nm = (rec.row && rec.row["姓名"]) ? rec.row["姓名"].trim() : "";
  return nm || (rec.source ? `(${rec.source})` : `第 ${i + 1} 位`);
}

function computeIssues() {
  const persons = state.records.filter(r => r.kind !== "trip");
  const trips = state.records.filter(r => r.kind === "trip");
  let errCells = 0, uncCells = 0;
  state.records.forEach(r => {
    const errs = r.errors || {};
    errCells += Object.keys(errs).length;
    // 同一格若既是硬错误(红)又被 AI 标不确定,按红处理,不重复计入「待核对」
    uncCells += (r.uncertain || []).filter(c => !errs[c]).length;
  });
  const unassigned = trips.filter(t => !(t.row && (t.row["姓名"] || "").trim())).length;
  return { nPersons: persons.length, errCells, uncCells, nTrips: trips.length, unassigned };
}

function renderIssueBar() {
  const it = computeIssues();
  const bar = q("#issue-bar");
  let html = `<span class="stat">共 <b>${it.nPersons}</b> 人</span>`;
  if (it.errCells) html += `<span class="stat red">待修正 <b>${it.errCells}</b> 处</span>`;
  if (it.uncCells) html += `<span class="stat yellow">待核对 <b>${it.uncCells}</b> 处</span>`;
  if (it.unassigned) html += `<span class="stat">行程待认领 <b>${it.unassigned}</b> 段</span>`;
  if (!it.errCells && !it.uncCells && !it.unassigned) {
    html += `<span class="all-good">✓ 全部就绪,可以去回填</span>`;
  } else if (it.errCells) {
    html += `<button class="jump" id="jump-err">跳到第一处待修正 →</button>`;
  }
  bar.innerHTML = html;
  const jb = q("#jump-err");
  if (jb) jb.addEventListener("click", () => {
    const card = q(".person-card.has-err") || q(".trip-card");
    if (card) { card.scrollIntoView({ behavior: "smooth", block: "start" }); card.classList.add("flash"); }
  });
}

function fieldHtml(rec, idx, col, label) {
  const val = (rec.row && rec.row[col] != null) ? rec.row[col] : "";
  let cls = "", why = "";
  if (rec.errors && rec.errors[col]) { cls = "err"; why = rec.errors[col]; }
  else if (rec.uncertain && rec.uncertain.includes(col)) { cls = "unc"; why = "AI 不确定,请核对"; }
  return `<div class="fld ${cls}">
    <label>${escapeHtml(label)}</label>
    <input data-idx="${idx}" data-col="${escapeHtml(col)}" value="${escapeHtml(val)}">
    <div class="why">${escapeHtml(why)}</div>
  </div>`;
}

function renderPersonCards() {
  const persons = state.records.filter(r => r.kind !== "trip");
  const box = q("#person-cards");
  if (!persons.length) { box.innerHTML = '<div class="empty">没有出席人记录。</div>'; return; }
  box.innerHTML = persons.map((rec, i) => {
    const idx = state.records.indexOf(rec);
    const nErr = Object.keys(rec.errors || {}).length;
    const nUnc = (rec.uncertain || []).filter(c => !(rec.errors || {})[c]).length;
    let chip = '<span class="chip green">✓ 无问题</span>';
    if (nErr) chip = `<span class="chip red">待修正 ${nErr}</span>`;
    else if (nUnc) chip = `<span class="chip yellow">待核对 ${nUnc}</span>`;

    const idBlock = MEDIA.map(c => fieldHtml(rec, idx, c, c)).join("");
    const legBlocks = LEGS.map(leg => {
      const fields = LEG_FIELDS.map(f => fieldHtml(rec, idx, `${leg}-${f}`, f)).join("");
      return `<div class="pc-block leg"><div class="blk-title">${leg}</div><div class="pc-fields">${fields}</div></div>`;
    }).join("");

    return `<div class="person-card${nErr ? " has-err" : ""}">
      <div class="pc-head">
        <span class="pc-name">${escapeHtml(personName(rec, i))}</span>
        ${rec.source ? `<span class="pc-src">来源:${escapeHtml(rec.source)}</span>` : ""}
        ${chip}
      </div>
      <div class="pc-block"><div class="blk-title">身份信息</div><div class="pc-fields">${idBlock}</div></div>
      ${legBlocks}
    </div>`;
  }).join("");
  qa("#person-cards input").forEach(inp => inp.addEventListener("input", onCellEdit));
}

function renderTripCards() {
  const trips = state.records.filter(r => r.kind === "trip");
  const block = q("#trips-block");
  if (!trips.length) { block.style.display = "none"; return; }
  block.style.display = "block";
  const names = [...new Set(state.records.filter(r => r.kind !== "trip")
    .map(r => (r.row && r.row["姓名"] || "").trim()).filter(Boolean))];

  const box = q("#trip-cards");
  box.innerHTML = trips.map(rec => {
    const idx = state.records.indexOf(rec);
    const cur = (rec.row && rec.row["姓名"] || "").trim();
    const known = cur && names.includes(cur);
    const isOther = cur && !known;
    const summary = LEGS.map(leg => {
      const way = rec.row[`${leg}-方式`] || "", date = rec.row[`${leg}-日期`] || "";
      const from = rec.row[`${leg}-出发城市`] || "", to = rec.row[`${leg}-到达城市`] || "";
      const no = rec.row[`${leg}-航班车次`] || "";
      if (!(way || date || from || to || no)) return "";
      return `<b>${escapeHtml(leg)}</b> ${escapeHtml([way, date, (from || to) ? from + "→" + to : "", no].filter(Boolean).join(" "))}`;
    }).filter(Boolean).join(" &nbsp;·&nbsp; ") || "(空行程)";

    const opts = ['<option value="">暂不认领</option>']
      .concat(names.map(n => `<option value="${escapeHtml(n)}"${n === cur ? " selected" : ""}>${escapeHtml(n)}</option>`))
      .concat([`<option value="__other__"${isOther ? " selected" : ""}>其他(手动填写)…</option>`])
      .join("");

    return `<div class="trip-card">
      <div class="tc-head">
        <span class="lab">认领给:</span>
        <span class="assign">
          <select data-idx="${idx}" data-trip-assign>${opts}</select>
          <input data-idx="${idx}" data-trip-manual placeholder="手动填写姓名"
            value="${isOther ? escapeHtml(cur) : ""}" style="display:${isOther ? "inline-block" : "none"}">
        </span>
      </div>
      <div class="tc-summary">${summary}</div>
    </div>`;
  }).join("");

  qa("#trip-cards select[data-trip-assign]").forEach(sel => sel.addEventListener("change", onTripAssign));
  qa("#trip-cards input[data-trip-manual]").forEach(inp => inp.addEventListener("input", onTripManual));
}

function onTripAssign(e) {
  const sel = e.target;
  const idx = +sel.dataset.idx;
  const rec = state.records[idx];
  if (!rec) return;
  const manual = q(`#trip-cards input[data-trip-manual][data-idx="${idx}"]`);
  if (sel.value === "__other__") {
    manual.style.display = "inline-block";
    manual.focus();
    rec.row["姓名"] = manual.value.trim();
  } else {
    manual.style.display = "none";
    rec.row["姓名"] = sel.value;
  }
}
function onTripManual(e) {
  const idx = +e.target.dataset.idx;
  const rec = state.records[idx];
  if (rec) rec.row["姓名"] = e.target.value.trim();
}

function renderReview() {
  if (!state.records.length) {
    q("#issue-bar").innerHTML = "";
    q("#person-cards").innerHTML = '<div class="empty">还没有记录,点上面「开始识别」。</div>';
    q("#trips-block").style.display = "none";
    return;
  }
  renderIssueBar();
  renderPersonCards();
  renderTripCards();
}

function onCellEdit(e) {
  const inp = e.target;
  const idx = +inp.dataset.idx;
  const col = inp.dataset.col;
  const rec = state.records[idx];
  if (!rec) return;
  rec.row[col] = inp.value;
  // 编辑即清掉这个格的黄标(存疑),红标等保存后服务端重算
  if (rec.uncertain) rec.uncertain = rec.uncertain.filter(c => c !== col);
  const fld = inp.closest(".fld");
  if (fld && !fld.classList.contains("err")) {
    fld.classList.remove("unc");
    const why = fld.querySelector(".why");
    if (why) why.textContent = "";
  }
}

q("#btn-save-records").addEventListener("click", async () => {
  if (!state.activity) return;
  setStatus("#st-records", "保存中…", "muted");
  try {
    const data = await api("PUT", `/api/activities/${enc(state.activity)}/records`, { records: state.records });
    state.records = data.records || [];
    renderReview();
    const it = computeIssues();
    if (it.errCells) setStatus("#st-records", `已保存,还有 ${it.errCells} 处待修正`, "err");
    else setStatus("#st-records", "已保存,红黄标记已刷新", "ok");
    toast("已保存", "ok");
  } catch (e) { setStatus("#st-records", e.message, "err"); }
});

// ================= ④ 回填 =================
q("#btn-preview").addEventListener("click", async () => {
  if (!state.activity) { toast("请先选择活动", "err"); return; }
  const target = "prod";
  setStatus("#st-apply", "试算中…", "muted");
  try {
    const pv = await api("POST", `/api/activities/${enc(state.activity)}/apply/preview`, { target });
    state.lastPreview = pv;
    renderPreview(pv);
    q("#preview-card").style.display = "block";
    setStatus("#st-apply", "试算完成,请核对下方落点", "ok");
  } catch (e) { setStatus("#st-apply", e.message, "err"); q("#preview-card").style.display = "none"; }
});

function renderPreview(pv) {
  const body = q("#preview-body");
  let html = "";
  html += `<div class="banner ${pv.header_ok ? "ok" : "err"}">目标:工作表「${escapeHtml(pv.sheet_title || "")}」<br>
    <span style="font-size:12px;word-break:break-all">${escapeHtml(pv.target_url || "")}</span></div>`;
  if (!pv.header_ok) {
    html += `<div class="banner err">列结构与预期不符,为防写错列已禁止写入:<br>` +
      pv.mismatches.map(m => `第${m[0]}列 期望含「${escapeHtml(m[1])}」,实际「${escapeHtml(m[2])}」`).join("<br>") + `</div>`;
  }
  if (pv.applied && pv.applied[pv.target]) {
    html += `<div class="banner warn">这批已于 ${escapeHtml(pv.applied[pv.target])} 写入过该目标。再次写入需勾选「强制写入」。</div>`;
  }
  if (pv.n_unassigned) {
    html += `<div class="banner warn">有 ${pv.n_unassigned} 段行程还没配上出行人,本次不会写入。请回②「资料识别」在「待认领行程」用下拉认领。</div>`;
  }
  html += `<p class="sub">将写入 <b>${pv.n_persons}</b> 位出席人。每位落点如下:</p>`;
  if (!pv.persons.length) {
    html += '<div class="empty">没有可写入的出席人。</div>';
  } else {
    pv.persons.forEach(p => {
      html += `<div class="preview-person"><div class="who">${escapeHtml(p.who)}</div><div class="cellmap">` +
        (p.cells.length ? p.cells.map(c => `<span class="c"><b>${c.letter}</b> ${escapeHtml(c.header)} = ${escapeHtml(c.value)}</span>`).join("")
          : '<span class="hint">无可写入字段</span>') +
        `</div></div>`;
    });
  }
  body.innerHTML = html;
  q("#btn-write").disabled = !pv.header_ok || !pv.n_persons;
}

// ---- 自定义确认弹层 ----
function confirmModal({ title, bodyHtml, okLabel = "确认", danger = false }) {
  return new Promise(resolve => {
    q("#confirm-title").textContent = title;
    q("#confirm-body").innerHTML = bodyHtml;
    const ok = q("#confirm-ok"), cancel = q("#confirm-cancel"), ov = q("#confirm-overlay");
    ok.textContent = okLabel;
    ok.className = "btn " + (danger ? "danger" : "primary");
    ov.classList.add("show");
    const cleanup = () => {
      ov.classList.remove("show");
      ok.removeEventListener("click", onOk);
      cancel.removeEventListener("click", onCancel);
      ov.removeEventListener("click", onBackdrop);
    };
    const onOk = () => { cleanup(); resolve(true); };
    const onCancel = () => { cleanup(); resolve(false); };
    const onBackdrop = e => { if (e.target === ov) onCancel(); };
    ok.addEventListener("click", onOk);
    cancel.addEventListener("click", onCancel);
    ov.addEventListener("click", onBackdrop);
  });
}

q("#btn-write").addEventListener("click", async () => {
  const target = "prod";
  const force = q("#apply-force").checked;
  const pv = state.lastPreview || {};
  const bodyHtml = `将向飞书目标表的工作表「${escapeHtml(pv.sheet_title || "")}」` +
    `<b>追加 ${pv.n_persons || 0} 行</b>。` +
    `<div class="cf-note">此操作会真正写入飞书,无法自动撤销。请确认目标表无误。</div>`;
  const ok = await confirmModal({ title: "确认写入飞书", bodyHtml, okLabel: "确认写入", danger: false });
  if (!ok) return;

  setStatus("#st-write", "写入中…", "muted");
  q("#btn-write").disabled = true;
  try {
    const res = await api("POST", `/api/activities/${enc(state.activity)}/apply/write`, { target, confirm: true, force });
    if (res.ok) {
      setStatus("#st-write", `已追加 ${res.appended_rows} 行到「${res.sheet_title || ""}」,请到飞书核对`, "ok");
      toast("写入成功", "ok");
      state.applied[target] = new Date().toLocaleString();
      renderNav();
    } else if (res.reason === "already_applied") {
      setStatus("#st-write", `这批已于 ${res.applied_at} 写入过。如需重写请勾选「强制写入」。`, "err");
    } else {
      setStatus("#st-write", "未写入:" + (res.reason || "未知原因"), "err");
    }
  } catch (e) { setStatus("#st-write", e.message, "err"); }
  finally { q("#btn-write").disabled = false; }
});

// ================= 启动 =================
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { closeSettings(); q("#confirm-overlay").classList.remove("show"); }
});
updateBadge();
goStep(1);
