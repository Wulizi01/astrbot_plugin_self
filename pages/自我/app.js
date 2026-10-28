const el = (id) => document.getElementById(id);
const state = {
  people: [],
  log: [],
  peopleSort: "msg_count",
  logFilter: "all",
  formBuilt: false,
  dirty: false,
  settings: null,
};

const ADVISOR_FIELDS = [
  ["advisor_enabled", "启用", "bool"],
  ["advisor_mode", "模式", "select", ["current_provider", "api"]],
  ["advisor_scope", "生效范围", "select", ["both", "private", "group"]],
  ["advisor_trigger_policy", "触发策略", "select",
    ["keywords", "explicit", "hostile_only", "probabilistic", "always", "off"]],
  ["advisor_trigger_probability", "概率", "float"],
  ["api_base", "API 地址", "text"],
  ["api_model", "API 模型", "text"],
  ["api_key", "API Key", "password"],
  ["advisor_provider_id", "指定 Provider", "text"],
  ["advisor_temperature", "温度", "float"],
  ["advisor_max_tokens", "最大输出 token", "int"],
  ["advisor_timeout", "顾问超时（秒）", "int"],
  ["advisor_cooldown", "冷却（秒）", "int"],
  ["advisor_per_hour", "每小时上限", "int"],
  ["advisor_per_day", "每天上限（0=不限）", "int"],
  ["advisor_route_timeout", "回复前最多等（秒）", "int"],
  ["advisor_max_chars", "注入上限（字）", "int"],
  ["advisor_prompt", "顾问提示词", "textarea"],
];

document.addEventListener("DOMContentLoaded", () => {
  applyThemeFallback();
  el("refreshBtn")?.addEventListener("click", loadAll);
  el("testBtn")?.addEventListener("click", testAdvisor);
  el("resetBtn")?.addEventListener("click", resetNarrative);
  el("narrativeToggle")?.addEventListener("click", toggleNarrative);
  el("advisorForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    saveAdvisorSettings();
  });
  el("peopleSort")?.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip) return;
    state.peopleSort = chip.dataset.sort;
    setPressed(el("peopleSort"), chip);
    renderPeople(state.people);
  });
  el("logFilter")?.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (!chip) return;
    state.logFilter = chip.dataset.filter;
    setPressed(el("logFilter"), chip);
    renderLog(state.log);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") cancelReset();
  });
  loadAll();
});

function setPressed(group, active) {
  group?.querySelectorAll(".chip").forEach((chip) => {
    chip.setAttribute("aria-pressed", chip === active ? "true" : "false");
  });
}

function applyThemeFallback() {
  const root = document.documentElement;
  if (root.dataset.theme) return;
  // `?theme=light|dark` is for local preview screenshots only.
  const forced = new URLSearchParams(window.location.search).get("theme");
  if (forced === "light" || forced === "dark") {
    root.dataset.theme = forced;
    return;
  }
  if (window.matchMedia?.("(prefers-color-scheme: light)").matches) {
    root.dataset.theme = "light";
  } else {
    root.dataset.theme = "dark";
  }
}

async function loadAll() {
  setConn("连接中…", false);
  clearErrors();
  const results = await Promise.allSettled([
    SelfPageApi.get("/overview"),
    SelfPageApi.get("/people"),
    SelfPageApi.get("/advisor/log"),
    SelfPageApi.get("/advisor/settings"),
  ]);
  const [overview, people, log, settings] = results;
  let failed = 0;

  if (overview.status === "fulfilled") {
    renderOverview(overview.value);
  } else {
    failed += 1;
    markError("stats", overview.reason);
  }
  if (people.status === "fulfilled") {
    state.people = people.value.items || [];
    renderPeople(state.people);
  } else {
    failed += 1;
    markError("peopleTable", people.reason);
  }
  if (log.status === "fulfilled") {
    state.log = log.value.items || [];
    renderLog(state.log);
  } else {
    failed += 1;
    markError("advisorLog", log.reason);
  }
  if (settings.status === "fulfilled") {
    state.settings = settings.value;
    renderAdvisorForm(settings.value);
  } else {
    failed += 1;
    markError("advisorForm", settings.reason);
  }

  el("stats")?.setAttribute("aria-busy", "false");
  if (failed === 0) {
    setConn("已连接", true);
  } else if (failed === results.length) {
    setConn("连接失败", false);
  } else {
    setConn(`部分失败（${failed}/${results.length}）`, false);
  }
}

function clearErrors() {
  document.querySelectorAll(".card-err").forEach((node) => node.remove());
}

function markError(anchorId, reason) {
  const anchor = el(anchorId);
  if (!anchor) return;
  const note = document.createElement("p");
  note.className = "card-err";
  note.textContent = `加载失败：${reason?.message || reason || "未知错误"}`;
  anchor.after(note);
}

function renderAdvisorForm(settings) {
  const host = el("advisorForm");
  if (!host) return;
  if (!state.formBuilt) {
    host.innerHTML = ADVISOR_FIELDS.map(([key, label, type, options]) =>
      fieldMarkup(key, label, type, options, settings)
    ).join("");
    host.querySelectorAll("input, select, textarea").forEach((node) => {
      node.addEventListener("input", markDirty);
      node.addEventListener("change", markDirty);
    });
    state.formBuilt = true;
  }
  if (state.dirty) return; // never overwrite what the user is typing
  setFormValues(settings);
}

function fieldMarkup(key, label, type, options, settings) {
  const id = `cfg_${key}`;
  const typeName = settings?.types?.[key] || type;
  const range = settings?.ranges?.[key];
  let control = "";
  if (type === "bool") {
    control = `<select id="${id}"><option value="true">开</option><option value="false">关</option></select>`;
  } else if (type === "select") {
    control = `<select id="${id}">${options
      .map((opt) => `<option value="${opt}">${opt}</option>`)
      .join("")}</select>`;
  } else if (type === "textarea") {
    control = `<textarea id="${id}"></textarea>`;
  } else {
    const inputType = type === "password" ? "password" : type === "text" ? "text" : "number";
    const attrs = [];
    if (range && inputType === "number") {
      attrs.push(`min="${range[0]}"`, `max="${range[1]}"`);
      attrs.push(`step="${typeName === "int" ? 1 : 0.1}"`);
    }
    control = `<input id="${id}" type="${inputType}" ${attrs.join(" ")} />`;
  }
  const hint = ["int", "float"].includes(typeName)
    ? `<small>留空=不改${range ? `，范围 ${range[0]}–${range[1]}` : ""}</small>`
    : "";
  const wide = type === "textarea" ? " wide" : "";
  return `<label class="field${wide}"><span>${label}</span>${control}${hint}</label>`;
}

function setFormValues(settings) {
  const values = settings.values || {};
  ADVISOR_FIELDS.forEach(([key, , type]) => {
    const node = el(`cfg_${key}`);
    if (!node) return;
    const value = values[key];
    if (type === "bool") {
      node.value = String(Boolean(value));
    } else {
      node.value = key === "api_key" ? "" : (value ?? "");
    }
    if (key === "api_key" && settings.has_key) node.placeholder = "已配置，留空不改";
  });
  el("advisorSaveResult").textContent = settings.has_key
    ? "当前已配置 API Key。"
    : "当前未配置 API Key（current_provider 模式不需要）。";
}

function markDirty() {
  state.dirty = true;
  const badge = el("dirtyBadge");
  if (badge) badge.hidden = false;
}

async function saveAdvisorSettings() {
  const button = el("saveAdvisorBtn");
  button.disabled = true;
  el("advisorSaveResult").textContent = "保存中…";
  try {
    const values = SelfForm.collect(ADVISOR_FIELDS, (key) => {
      const node = el(`cfg_${key}`);
      return node ? node.value : null;
    });
    const result = await SelfPageApi.post("/advisor/settings/save", { values });
    const applied = result.applied || {};
    const clamped = Object.keys(applied).filter((key) => {
      if (typeof applied[key] !== "number" || values[key] === undefined) return false;
      return Number(values[key]) !== applied[key];
    });
    state.dirty = false;
    el("dirtyBadge").hidden = true;
    const settings = await SelfPageApi.get("/advisor/settings");
    state.settings = settings;
    setFormValues(settings);
    if (!result.saved) {
      el("advisorSaveResult").textContent = "已应用，但写盘失败（重启后会回退），请查看日志。";
    } else if (clamped.length) {
      el("advisorSaveResult").textContent =
        `已保存；${clamped.join("、")} 超出允许范围，已钳制。`;
    } else {
      el("advisorSaveResult").textContent = "已保存并生效。";
    }
    const overview = await SelfPageApi.get("/overview");
    renderOverview(overview);
  } catch (error) {
    el("advisorSaveResult").textContent = `保存失败：${error.message || error}`;
  } finally {
    button.disabled = false;
  }
}

function renderOverview(data) {
  el("statDays").textContent = data.days ?? "–";
  el("statSamples").textContent = data.samples ?? "–";
  el("statEpisodes").textContent = data.episodes ?? "–";
  el("statMemories").textContent = data.memories ?? "–";
  el("statPeople").textContent = data.people ?? "–";
  const advisor = data.advisor || {};
  el("statAdvisor").textContent = advisor.calls ?? "–";

  const narrative = data.narrative || "（还没有形成叙事）";
  el("narrative").textContent = narrative;
  const toggle = el("narrativeToggle");
  const wrap = el("narrativeWrap");
  if (toggle && wrap) {
    const long = narrative.length > 120;
    toggle.hidden = !long;
    wrap.classList.toggle("collapsed", long && state.narrativeCollapsed !== false);
    toggle.textContent = wrap.classList.contains("collapsed") ? "展开" : "收起";
    if (!long) state.narrativeCollapsed = false;
  }

  const traits = data.traits || {};
  const rows = [
    ["话多", traits.verbosity],
    ["温度", traits.warmth],
    ["表情", traits.emoji],
    ["主动", traits.initiative],
  ];
  el("traits").innerHTML = rows
    .map(([label, value]) => {
      const pct = Math.round(Math.max(0, Math.min(1, Number(value) || 0)) * 100);
      return `<div class="trait"><span>${label}</span>
        <div class="bar"><i style="width:${pct}%"></i></div>
        <b>${pct}%</b></div>`;
    })
    .join("");

  el("advisorMeta").textContent = advisor.enabled
    ? `模式 ${advisor.mode || "–"}｜范围 ${advisor.scope || "–"}｜失败 ${advisor.errors ?? 0} 次｜平均 ${advisor.avg_ms ?? 0} ms`
    : "顾问已停用";
}

function toggleNarrative() {
  const wrap = el("narrativeWrap");
  if (!wrap) return;
  state.narrativeCollapsed = !wrap.classList.contains("collapsed");
  wrap.classList.toggle("collapsed", state.narrativeCollapsed);
  el("narrativeToggle").textContent = state.narrativeCollapsed ? "展开" : "收起";
}

function renderPeople(items) {
  const host = el("peopleTable");
  if (!host) return;
  const sorted = SelfForm.sortPeople(items, state.peopleSort);
  if (!sorted.length) {
    host.innerHTML = '<p class="empty">还没有记录到群成员。</p>';
    el("peopleHint").textContent = "";
    return;
  }
  host.innerHTML = sorted
    .map((item) => {
      const affinity = Math.round(
        Math.max(0, Math.min(1, Number(item.affinity) || 0)) * 100
      );
      return `<div class="row-item">
        <span class="name">${SelfForm.escapeHtml(item.name || item.user_id)}</span>
        <span class="muted">${item.msg_count ?? 0} 句</span>
        <span class="affinity"><span class="bar"><i style="width:${affinity}%"></i></span>
          <span class="muted">${affinity}%</span></span>
        <span class="muted">${SelfForm.relTime(item.last_seen)}</span>
      </div>`;
    })
    .join("");
  el("peopleHint").textContent = `共 ${sorted.length} 人`;
}

function renderLog(items) {
  const host = el("advisorLog");
  if (!host) return;
  const filtered = SelfForm.filterLog(items, state.logFilter);
  if (!filtered.length) {
    host.innerHTML = '<p class="empty">没有符合条件的记录。</p>';
    return;
  }
  host.innerHTML = filtered
    .map((item) => {
      const ok = Number(item.ok) === 1;
      const tag = ok ? (item.injected ? "已注入" : "已返回") : "失败";
      const answer = String(item.answer || "");
      const body =
        answer.length > 140
          ? `<details class="a"><summary>答：${SelfForm.escapeHtml(answer.slice(0, 60))}…</summary>
             <p>${SelfForm.escapeHtml(answer)}</p></details>`
          : `<p class="a">答：${SelfForm.escapeHtml(answer)}</p>`;
      return `<div class="log-item ${ok ? "" : "bad"}">
        <div class="log-head"><span>${SelfForm.escapeHtml(item.source || "")}</span>
          <span>${SelfForm.relTime(item.at)}</span><b>${tag}</b>
          <span>${item.latency_ms ?? 0} ms</span></div>
        <p class="q">问：${SelfForm.escapeHtml(item.question || "")}</p>
        ${body}
      </div>`;
    })
    .join("");
}

async function testAdvisor() {
  const question = (el("testInput")?.value || "").trim();
  const button = el("testBtn");
  const started = Date.now();
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  const timer = setInterval(() => {
    const seconds = Math.round((Date.now() - started) / 1000);
    el("testResult").textContent = `询问中… ${seconds}s（超过 60 秒会超时）`;
  }, 500);
  el("testResult").textContent = "询问中… 0s（超过 60 秒会超时）";
  try {
    const data = await SelfPageApi.post("/advisor/test", { question });
    el("testResult").textContent = `${data.answer}（${data.elapsed_ms} ms）`;
    const log = await SelfPageApi.get("/advisor/log");
    state.log = log.items || [];
    renderLog(state.log);
    const overview = await SelfPageApi.get("/overview");
    renderOverview(overview);
  } catch (error) {
    el("testResult").textContent = `失败：${error.message || error}`;
  } finally {
    clearInterval(timer);
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

let resetArmed = false;
let resetTimer = null;

async function resetNarrative() {
  const button = el("resetBtn");
  // Two-step confirm: window.confirm is blocked inside the dashboard iframe.
  if (!resetArmed) {
    resetArmed = true;
    button.textContent = "确认重置？";
    resetTimer = setTimeout(cancelReset, 5000);
    return;
  }
  cancelReset();
  try {
    await SelfPageApi.post("/reset", {});
    toast("已重置");
    loadAll();
  } catch (error) {
    toast(error.message || String(error), true);
  }
}

function cancelReset() {
  clearTimeout(resetTimer);
  if (!resetArmed) return;
  resetArmed = false;
  const button = el("resetBtn");
  if (button) button.textContent = "重置叙事";
}

function setConn(text, ok) {
  el("connText").textContent = text;
  el("statusDot").className = `dot ${ok ? "ok" : "bad"}`;
}

let toastTimer = null;
function toast(text, bad = false) {
  const node = el("toast");
  node.textContent = text;
  node.className = `toast show ${bad ? "bad" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.className = "toast";
  }, 2600);
}
