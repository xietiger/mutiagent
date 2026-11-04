const state = {
  agents: [],
  tasks: [],
  openId: null,
  source: null,
  timer: null,
  drawerOpen: false,
  agentFilter: "ready",
};

const labels = {
  ready: "就绪",
  needs_login: "需要登录",
  not_installed: "未安装",
  wrong_binary: "身份不匹配",
  version_unsupported: "版本不兼容",
  needs_attention: "待确认",
  unavailable: "不可用",
  error: "探测失败",
  unchecked: "未检查",
  queued: "排队",
  running: "运行中",
  succeeded: "成功",
  degraded: "降级",
  failed: "失败",
  timeout: "超时",
  cancelled: "已取消",
  pending: "等待",
  mixed: "部分完成",
  readonly: "只读评审",
  worktree: "独立 worktree",
  preparing: "准备",
  preparing_snapshot: "准备快照",
  creating_worktree: "创建 worktree",
  agent_running: "Agent 运行",
  parsing: "解析结果",
  done: "完成",
};

const drawer = document.querySelector("#context-drawer");
const drawerBackdrop = document.querySelector("#drawer-backdrop");
const drawerNotice = document.querySelector("#drawer-notice");
const composerOptions = document.querySelector("#composer-options");
const taskForm = document.querySelector("#task-form");
const promptInput = taskForm.elements.prompt;
const contextInput = taskForm.elements.context_path;
const taskDetail = document.querySelector("#task-detail");
const comparePanel = document.querySelector("#compare-panel");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function label(value) {
  return labels[value] || value || "";
}

function agentIcon(name) {
  const normalized = String(name || "").toLowerCase();
  if (normalized.includes("claude")) return "CL";
  if (normalized.includes("grok")) return "GR";
  if (normalized.includes("kimi")) return "KM";
  if (normalized.includes("codebuddy") || normalized.includes("code buddy")) return "CB";
  if (normalized.includes("codex")) return "CX";
  if (normalized.includes("cursor")) return "CU";
  if (normalized.includes("vscode") || normalized.includes("vs code")) return "VS";
  if (normalized.includes("本地")) return "LC";
  return String(name || "A").slice(0, 2).toUpperCase();
}

function notice(message) {
  const node = document.querySelector("#notice");
  if (node) node.textContent = message || "";
}

function drawerNoticeMessage(message) {
  drawerNotice.textContent = message || "";
}

async function api(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { detail: text };
  }
  if (!response.ok) throw new Error(body?.detail || response.statusText);
  return body;
}

function setDrawer(open) {
  state.drawerOpen = Boolean(open);
  drawer.classList.toggle("open", state.drawerOpen);
  drawerBackdrop.classList.toggle("open", state.drawerOpen);
  drawer.setAttribute("aria-hidden", String(!state.drawerOpen));
  document.querySelectorAll("#context-toggle, #agent-picker").forEach((button) => {
    button.setAttribute("aria-expanded", String(state.drawerOpen));
  });
  if (!state.drawerOpen) drawerNoticeMessage("");
}

function toggleComposerOptions(force) {
  const next = typeof force === "boolean" ? force : composerOptions.hidden;
  composerOptions.hidden = !next;
  document.querySelector("#composer-add").setAttribute("aria-expanded", String(next));
  if (next) {
    window.setTimeout(() => {
      (document.querySelector('input[name="title"]').value
        ? contextInput
        : document.querySelector('input[name="title"]')
      ).focus();
    }, 0);
  }
}

function emptyThreadMarkup() {
  return `
    <div class="empty-thread">
      <span class="empty-mark">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6.5h14v9H9l-4 3v-3H5z"/><path d="M8.5 10h7M8.5 13h4.5"/></svg>
      </span>
      <p class="eyebrow">PARALLEL WORKSPACE</p>
      <h1>今天想让哪些 Agent<br>一起工作？</h1>
      <p class="empty-copy">写下一个问题，选择一个或多个 Agent。它们会独立运行，结果会在这里汇总。</p>
      <div class="quick-prompts">
        <button type="button" data-prompt="评审当前项目，优先检查安全风险、边界条件和测试缺口。">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5 16 5v4.6c0 3.8-2.4 6.4-6 7.9-3.6-1.5-6-4.1-6-7.9V5z"/><path d="m7.3 9.8 1.8 1.8 3.8-3.9"/></svg>
          安全评审
        </button>
        <button type="button" data-prompt="阅读当前项目并给出最重要的结构改进建议，说明理由和影响范围。">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 4h14v11H3z"/><path d="M6 7h8M6 10h5"/></svg>
          架构建议
        </button>
        <button type="button" data-prompt="检查现有实现与需求是否有偏差，并列出最需要补充的测试。">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m6 3 2 2-4 4-2-2M9 5l8 8-3 3-8-8"/><path d="m3 14 3 3"/></svg>
          测试检查
        </button>
      </div>
    </div>`;
}

function bindQuickPrompts() {
  taskDetail.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      promptInput.value = button.dataset.prompt || "";
      promptInput.focus();
    });
  });
}

function resetThread() {
  state.openId = null;
  if (state.source) {
    state.source.close();
    state.source = null;
  }
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  taskForm.reset();
  document.querySelectorAll("input[name=agent]").forEach((input) => { input.checked = false; });
  composerOptions.hidden = true;
  document.querySelector("#composer-add").setAttribute("aria-expanded", "false");
  updateCount();
  taskDetail.innerHTML = emptyThreadMarkup();
  bindQuickPrompts();
  comparePanel.hidden = true;
  document.querySelector("#thread-title").textContent = "新任务";
  document.querySelector("#thread-meta").textContent = "选择一个任务，或开始新的并行评审";
  document.querySelector("#drawer-output-title").textContent = "尚无运行结果";
  document.querySelector("#drawer-output-meta").textContent = "开始任务后会出现在这里";
  document.querySelector("#drawer-source span").textContent = "选择项目目录";
  document.querySelector(".thread-scroll").scrollTop = 0;
  setDrawer(false);
  loadTasks();
  window.setTimeout(() => promptInput.focus(), 0);
}

async function loadAgents() {
  state.agents = await api("/agents");
  const box = document.querySelector("#agents");
  const readyCount = state.agents.filter((agent) => agent.health_status === "ready" && agent.enabled).length;
  box.innerHTML = state.agents.map((agent) => {
    const selectable = agent.health_status === "ready" && agent.enabled;
    return `<article class="agent" data-selectable="${selectable ? "1" : "0"}">
      <span class="agent-icon" aria-hidden="true">${esc(agentIcon(agent.name))}</span>
      <span class="agent-main">
        <span class="agent-name-row">
          <strong>${esc(agent.name)}</strong>
          <span class="agent-status ${esc(agent.health_status)}">${esc(label(agent.health_status))}${agent.enabled ? "" : " · 已停用"}</span>
        </span>
        <span class="agent-version">${esc(agent.version || "无版本")} · ${esc(agent.review_profile)}</span>
        <span class="agent-path" title="${esc(agent.executable_path)}">${esc(agent.executable_path)}</span>
      </span>
      <label class="agent-select-area" title="${selectable ? "选择此 Agent" : "当前不可选择"}">
        <input type="checkbox" name="agent" value="${esc(agent.id)}" ${selectable ? "" : "disabled"} aria-label="选择 ${esc(agent.name)}">
        <span class="custom-check"><svg viewBox="0 0 12 12" aria-hidden="true"><path d="m2.4 6.1 2.2 2.2 5-5"/></svg></span>
      </label>
      <button class="agent-menu" type="button" data-agent-menu aria-label="更多 Agent 操作" aria-expanded="false">
        <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="5" cy="10" r="1"/><circle cx="10" cy="10" r="1"/><circle cx="15" cy="10" r="1"/></svg>
      </button>
      <span class="agent-actions" hidden>
        <button type="button" data-probe="${esc(agent.id)}">探测</button>
        <button type="button" data-enable="${esc(agent.id)}" data-enabled="${agent.enabled ? "1" : "0"}">${agent.enabled ? "停用" : "启用"}</button>
        ${agent.install_hint && agent.health_status !== "ready" ? `<button type="button" data-show-hint>安装说明</button>` : ""}
      </span>
      ${agent.install_hint && agent.health_status !== "ready" ? `<pre class="hint" hidden>${esc(agent.install_hint)}</pre>` : ""}
    </article>`;
  }).join("");

  box.querySelectorAll("[data-agent-menu]").forEach((button) => {
    button.addEventListener("click", () => {
      const actions = button.closest(".agent").querySelector(".agent-actions");
      actions.hidden = !actions.hidden;
      button.setAttribute("aria-expanded", String(!actions.hidden));
    });
  });
  box.querySelectorAll("[data-show-hint]").forEach((button) => {
    button.addEventListener("click", () => {
      const hint = button.closest(".agent").querySelector(".hint");
      hint.hidden = !hint.hidden;
    });
  });
  box.querySelectorAll("[data-probe]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/agents/${button.dataset.probe}/probe`, { method: "POST" });
        await loadAgents();
      } catch (error) {
        drawerNoticeMessage(error.message);
      }
    });
  });
  box.querySelectorAll("[data-enable]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/agents/${button.dataset.enable}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled: button.dataset.enabled !== "1" }),
        });
        await loadAgents();
      } catch (error) {
        drawerNoticeMessage(error.message);
      }
    });
  });
  box.querySelectorAll("input[name=agent]").forEach((input) => input.addEventListener("change", updateCount));
  document.querySelector("#ready-count").textContent = readyCount;
  document.querySelector("#rail-agent-count").textContent = readyCount;
  document.querySelector("#agent-total").textContent = `${readyCount} / ${state.agents.length}`;
  document.querySelector("#connection-copy").textContent = readyCount
    ? `${readyCount} 就绪`
    : "无可用 Agent";
  updateAgentFilter();
  updateCount();
}

function updateAgentFilter() {
  document.querySelectorAll("#agents .agent").forEach((agent) => {
    agent.hidden = state.agentFilter === "ready" && agent.dataset.selectable !== "1";
  });
  document.querySelectorAll("[data-agent-filter]").forEach((button) => {
    button.classList.toggle("active", button.dataset.agentFilter === state.agentFilter);
    const isReady = button.dataset.agentFilter === "ready";
    const count = isReady
      ? state.agents.filter((agent) => agent.health_status === "ready" && agent.enabled).length
      : state.agents.length;
    button.textContent = `${isReady ? "可用" : "全部"} ${count}`;
  });
}

function selectedIds() {
  return [...document.querySelectorAll("input[name=agent]:checked")].map((item) => item.value);
}

function updateCount() {
  const fanout = document.querySelector("input[name=fanout]").checked;
  const count = fanout
    ? state.agents.filter((agent) => agent.health_status === "ready" && agent.enabled).length
    : selectedIds().length;
  document.querySelector("#call-count").textContent = `将调用 ${count} 个 Agent`;
  document.querySelector("#agent-picker-copy").textContent = count ? `${count} 个 Agent` : "选择 Agent";
  document.querySelector("#agent-picker").classList.toggle("has-selection", count > 0);
  document.querySelector("#drawer-selection-count").textContent = count;
}

async function loadTasks() {
  state.tasks = await api("/tasks");
  const box = document.querySelector("#task-list");
  document.querySelector("#task-count").textContent = state.tasks.length;
  box.innerHTML = state.tasks.length
    ? state.tasks.map((task) => `
      <button type="button" class="task-button ${task.id === state.openId ? "active" : ""}" data-task="${esc(task.id)}" title="${esc(label(task.status))} · ${esc(label(task.execution_mode))}">
        <strong>${esc(task.title)}</strong>
        <span class="meta">${esc(label(task.status))} · ${esc(label(task.execution_mode))}</span>
      </button>`).join("")
    : `<p class="sidebar-empty">还没有任务</p>`;
  box.querySelectorAll("[data-task]").forEach((button) => {
    button.addEventListener("click", () => openTask(button.dataset.task));
  });
}

function elapsed(start, end) {
  if (!start) return "";
  const from = Date.parse(start);
  const to = end ? Date.parse(end) : Date.now();
  return `${Math.max(0, Math.round((to - from) / 1000))} 秒`;
}

function renderFindings(findings) {
  if (!findings?.length) return `<p class="muted">没有结构化发现。</p>`;
  return findings.map((item) => `<article class="finding">
    <strong>${esc(item.severity)} · ${esc(item.title)}</strong>
    <p class="meta">${esc(item.file || "无文件")}${item.line ? ":" + esc(item.line) : ""}</p>
    <p>${esc(item.evidence || "")}</p>
    <p>${esc(item.recommendation || "")}</p>
  </article>`).join("");
}

function renderDetail(task) {
  const running = ["pending", "running"].includes(task.status);
  document.querySelector("#thread-title").textContent = task.title;
  document.querySelector("#thread-meta").textContent =
    `${label(task.status)} · ${label(task.execution_mode)} · ${task.subtasks.length} 个 Agent`;
  document.querySelector("#drawer-output-title").textContent = task.title;
  document.querySelector("#drawer-output-meta").textContent =
    `${label(task.status)} · ${task.subtasks.length} 份输出`;
  document.querySelector("#drawer-source span").textContent = task.context_path;

  taskDetail.innerHTML = `
    <article class="thread-run">
      <div class="user-message">
        <div>
          <div class="user-bubble">${esc(task.prompt)}</div>
          <div class="user-caption">${esc(label(task.execution_mode))} · ${esc(label(task.strategy))}</div>
        </div>
      </div>

      <section class="response">
        <header class="response-head">
          <div>
            <div class="response-title-row">
              <span class="response-icon">
                <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="7" cy="7" r="2.8"/><circle cx="14" cy="8" r="2"/><path d="M2.5 16c.4-3 1.9-4.4 4.5-4.4s4.1 1.4 4.5 4.4M11.8 13c2.4-.5 4.2.4 5 2.5"/></svg>
              </span>
              <h2>并行结果</h2>
            </div>
            <p class="response-meta">${esc(task.context_path)} · 基线 ${esc(task.base_commit || "非 Git")}</p>
          </div>
          <button type="button" id="cancel" class="btn" ${running ? "" : "disabled"}>${running ? "停止运行" : "已完成"}</button>
        </header>

        ${task.summary ? `<p class="response-summary">${esc(task.summary)}</p><p class="response-note">总述来源：${esc(task.summary_source || "rule")}</p>` : ""}
        ${task.baseline_dirty ? `<p class="response-note">基线不包含当前未提交改动</p>` : ""}

        <div class="subtasks">${task.subtasks.map((sub) => `
          <article class="subtask">
            <header><strong>${esc(sub.agent_name)}</strong><span class="status ${esc(sub.status)}">${esc(label(sub.status))}</span></header>
            <p class="meta">${esc(sub.version || "无版本")} · ${esc(label(sub.phase))} · ${esc(sub.review_profile)} · ${esc(elapsed(sub.started_at, sub.finished_at))}</p>
            ${sub.input_drift ? `<p class="status degraded">输入已变化，比较可信度降低</p>` : ""}
            ${sub.error ? `<p>${esc(sub.error)}</p>` : ""}
            <p>${esc(sub.normalized?.summary || "")}</p>
            ${sub.normalized?.notes ? `<p class="meta">${esc(sub.normalized.notes)}</p>` : ""}
            ${renderFindings(sub.normalized?.findings)}
            ${sub.patch ? `<p class="meta">patch ${esc(sub.patch.bytes)} 字节 / ${esc(sub.patch.files)} 个文件。${esc(sub.patch.note || "不会自动合并")}</p>` : ""}
            <div class="actions">
              <button type="button" data-tail="${esc(sub.id)}:stdout">标准输出</button>
              <button type="button" data-tail="${esc(sub.id)}:stderr">错误输出</button>
              <button type="button" data-retry="${esc(sub.id)}" ${["queued", "running"].includes(sub.status) ? "disabled" : ""}>重试</button>
              ${sub.has_patch ? `<a href="/artifacts/${esc(task.id)}/${esc(sub.id)}/patch.diff">下载 patch</a>` : ""}
            </div>
            <pre id="log-${esc(sub.id)}" hidden></pre>
          </article>`).join("")}</div>
      </section>
    </article>`;

  document.querySelector("#cancel").addEventListener("click", async () => {
    await api(`/tasks/${task.id}/cancel`, { method: "POST" });
    await openTask(task.id, false);
  });
  document.querySelectorAll("[data-tail]").forEach((button) => {
    button.addEventListener("click", async () => {
      const [id, stream] = button.dataset.tail.split(":");
      const text = await fetch(`/tasks/${task.id}/subtasks/${id}/tail?stream=${stream}`).then((response) => response.text());
      const node = document.querySelector(`#log-${id}`);
      node.hidden = false;
      node.textContent = text || "（空）";
    });
  });
  document.querySelectorAll("[data-retry]").forEach((button) => {
    button.addEventListener("click", async () => {
      await api(`/subtasks/${button.dataset.retry}/retry`, { method: "POST" });
      await openTask(task.id, false);
      await loadTasks();
    });
  });
  comparePanel.hidden = false;
  renderCompare(task);
  if (state.timer) clearInterval(state.timer);
  state.timer = running ? setInterval(() => openTask(task.id, false), 3000) : null;
}

function renderCompare(task) {
  const comparison = task.comparison || { by_category: {}, alignment: {} };
  const alignment = comparison.alignment || {};
  const categories = Object.entries(comparison.by_category || {});
  const block = (title, items, render) => `<section><h3>${title}</h3>${items?.length ? items.map(render).join("") : `<p class="muted">无</p>`}</section>`;
  const count = (value) => value || 0;
  document.querySelector("#compare-summary").textContent =
    `共识 ${count(alignment.consensus?.length)} · 独有 ${count(alignment.single?.length)} · 冲突 ${count(alignment.conflicts?.length)}`;
  document.querySelector("#compare").innerHTML = `
    <div class="columns">${categories.map(([category, cards]) => `<section><h3>${esc(category)}</h3>${cards.map((card) => `<article class="finding"><strong>${esc(card.agent_name)}</strong><p>${esc(card.summary || "")}</p></article>`).join("")}</section>`).join("") || `<p class="muted">还没有可并排的结果。</p>`}</div>
    <div class="align">
      ${block("共识", alignment.consensus, (item) => `<article class="finding"><strong>${esc(item.file)}:${esc(item.line ?? "")}</strong><p class="meta">${esc((item.agents || []).join("、"))}</p><p>${esc(item.findings?.[0]?.title || "")}</p></article>`)}
      ${block("单独发现", alignment.single, (item) => `<article class="finding"><strong>${esc(item.agent_name)}</strong><p>${esc(item.title)}</p><p class="meta">${esc(item.file)}:${esc(item.line ?? "")}</p></article>`)}
      ${block("冲突", alignment.conflicts, (item) => `<article class="finding"><strong>${esc(item.file)}</strong>${(item.findings || []).map((finding) => `<p>${esc(finding.agent_name)}：${esc(finding.title)}</p>`).join("")}</article>`)}
      ${block("未能对齐", alignment.unaligned, (item) => `<article class="finding"><strong>${esc(item.agent_name)}</strong><p>${esc(item.title)}</p></article>`)}
    </div>`;
}

async function openTask(id, rebind = true) {
  state.openId = id;
  const task = await api(`/tasks/${id}`);
  renderDetail(task);
  await loadTasks();
  if (!rebind) return;
  if (state.source) state.source.close();
  const source = new EventSource(`/tasks/${id}/events`);
  source.addEventListener("subtask_update", () => openTask(id, false));
  source.addEventListener("task_update", () => openTask(id, false));
  state.source = source;
  document.querySelector(".thread-scroll").scrollTop = 0;
  setDrawer(false);
}

taskForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const fanout = Boolean(form.get("fanout"));
  const prompt = String(form.get("prompt") || "").trim();
  const contextPath = String(form.get("context_path") || "").trim();
  const title = String(form.get("title") || "").trim()
    || `${prompt.replace(/\s+/g, " ").slice(0, 38)}${prompt.length > 38 ? "…" : ""}`;
  const agentIds = selectedIds();

  if (!contextPath) {
    toggleComposerOptions(true);
    notice("请先填写任务的上下文目录");
    contextInput.focus();
    return;
  }
  if (!fanout && !agentIds.length) {
    setDrawer(true);
    notice("请至少选择一个 Agent，或开启全量分发");
    return;
  }

  const submitButton = taskForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  try {
    const task = await api("/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        prompt,
        context_path: contextPath,
        execution_mode: form.get("execution_mode"),
        strategy: fanout ? "fanout" : "selected",
        agent_ids: fanout ? [] : agentIds,
      }),
    });
    notice("");
    await loadTasks();
    await openTask(task.id);
  } catch (error) {
    notice(error.message);
  } finally {
    submitButton.disabled = false;
  }
});

document.querySelector("#custom-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const driver = form.get("driver");
  const target = String(form.get("executable") || "");
  const body = driver === "http"
    ? { name: form.get("name"), driver, http_url: target }
    : { name: form.get("name"), driver, executable: target };
  try {
    await api("/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    formElement.reset();
    drawerNoticeMessage("");
    await loadAgents();
  } catch (error) {
    drawerNoticeMessage(error.message);
  }
});

document.querySelector("#probe-all").addEventListener("click", async () => {
  try {
    await Promise.all(state.agents.map((agent) => api(`/agents/${agent.id}/probe`, { method: "POST" })));
    await loadAgents();
  } catch (error) {
    drawerNoticeMessage(error.message);
  }
});

document.querySelector("input[name=fanout]").addEventListener("change", updateCount);
document.querySelector("#composer-add").addEventListener("click", () => toggleComposerOptions());
document.querySelector("#new-task").addEventListener("click", resetThread);

document.querySelectorAll("#context-toggle, #rail-agents, #rail-settings, #agent-picker, #open-config").forEach((button) => {
  button.addEventListener("click", () => setDrawer(true));
});
document.querySelector("#drawer-close").addEventListener("click", () => setDrawer(false));
document.querySelector("#drawer-done").addEventListener("click", () => setDrawer(false));
drawerBackdrop.addEventListener("click", () => setDrawer(false));
document.querySelectorAll("[data-agent-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    state.agentFilter = button.dataset.agentFilter;
    updateAgentFilter();
  });
});

document.querySelector("#rail-history").addEventListener("click", () => {
  document.querySelector(".task-history").scrollIntoView({ behavior: "smooth", block: "start" });
});

function editSource() {
  setDrawer(false);
  toggleComposerOptions(true);
  contextInput.focus();
}

document.querySelector("#drawer-edit-source").addEventListener("click", editSource);
document.querySelector("#drawer-source").addEventListener("click", editSource);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.drawerOpen) {
    setDrawer(false);
    return;
  }
  if (event.key.toLowerCase() !== "n" || event.metaKey || event.ctrlKey || event.altKey) return;
  const target = event.target;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return;
  event.preventDefault();
  resetThread();
});

bindQuickPrompts();
loadAgents().then(loadTasks).catch((error) => notice(error.message));
