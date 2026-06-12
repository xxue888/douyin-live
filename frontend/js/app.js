// ==========================================================================
// APP STATE & CONFIGURATION
// ==========================================================================
let currentConfig = {
    live_url: "",
    ai_reply_enabled: true,
    llm_provider: "openai",
    openai_api_key: "",
    openai_api_base: "https://api.openai.com/v1",
    openai_model: "gpt-3.5-turbo",
    gemini_api_key: "",
    gemini_model: "gemini-1.5-flash",
    system_prompt: "",
    rules: [],
    scheduled_messages: [],
    smart_triggers: {
        enabled: true,
        silence_5m_content: "",
        silence_10m_content: "",
        like_100_content: ""
    }
};

let wsConn = null;
let reconnectTimer = null;
let currentStatus = "stopped";

// ==========================================================================
// DOM ELEMENTS
// ==========================================================================
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const liveUrlInput = document.getElementById("live-url-input");
const btnStart = document.getElementById("btn-start");
const btnStop = document.getElementById("btn-stop");
const aiReplyToggle = document.getElementById("ai-reply-toggle");
const smartTriggersToggle = document.getElementById("smart-triggers-toggle");
const logTerminal = document.getElementById("log-terminal");
const btnClearLogs = document.getElementById("btn-clear-logs");

// Tab content
const tabButtons = document.querySelectorAll(".tab-btn");
const tabContents = document.querySelectorAll(".tab-content");

// LLM settings
const llmProviderSelect = document.getElementById("llm-provider");
const openaiFields = document.getElementById("provider-openai-fields");
const geminiFields = document.getElementById("provider-gemini-fields");
const openaiApiBase = document.getElementById("openai-api-base");
const openaiModel = document.getElementById("openai-model");
const openaiApiKey = document.getElementById("openai-api-key");
const geminiModel = document.getElementById("gemini-model");
const geminiApiKey = document.getElementById("gemini-api-key");
const systemPromptInput = document.getElementById("system-prompt");
const btnSaveLlm = document.getElementById("btn-save-llm");

// Rules
const ruleKeywordInput = document.getElementById("rule-keyword-input");
const ruleReplyInput = document.getElementById("rule-reply-input");
const btnAddRule = document.getElementById("btn-add-rule");
const rulesListBody = document.getElementById("rules-list-body");

// Timers
const timerSecondsInput = document.getElementById("timer-seconds-input");
const timerContentInput = document.getElementById("timer-content-input");
const btnAddTimer = document.getElementById("btn-add-timer");
const timersListBody = document.getElementById("timers-list-body");

// Smart Triggers
const smartSilence5m = document.getElementById("smart-silence-5m");
const smartSilence10m = document.getElementById("smart-silence-10m");
const smartLike100 = document.getElementById("smart-like-100");
const btnSaveSmart = document.getElementById("btn-save-smart");

// ==========================================================================
// INITIALIZATION
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    initLlmFieldsToggle();
    loadSettings();
    connectWebSocket();
    initEventListeners();
});

// ==========================================================================
// EVENT HANDLERS & BINDINGS
// ==========================================================================
function initEventListeners() {
    // Start / Stop
    btnStart.addEventListener("click", startBot);
    btnStop.addEventListener("click", stopBot);
    
    // Clear logs
    btnClearLogs.addEventListener("click", () => {
        logTerminal.innerHTML = `<div class="log-line system-line">[${new Date().toLocaleTimeString()}] [SYSTEM] 日志控制台已清空。</div>`;
    });
    
    // Config toggles (immediate auto-save)
    aiReplyToggle.addEventListener("change", () => {
        currentConfig.ai_reply_enabled = aiReplyToggle.checked;
        saveSettings();
    });
    
    smartTriggersToggle.addEventListener("change", () => {
        currentConfig.smart_triggers.enabled = smartTriggersToggle.checked;
        saveSettings();
    });
    
    // Add custom keyword rule
    btnAddRule.addEventListener("click", addKeywordRule);
    
    // Add custom timer message
    btnAddTimer.addEventListener("click", addTimerAnnouncement);
    
    // Save LLM & Smart triggers forms
    btnSaveLlm.addEventListener("click", saveLlmConfig);
    btnSaveSmart.addEventListener("click", saveSmartConfig);
}

// Tab navigation controller
function initTabs() {
    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const tabId = btn.getAttribute("data-tab");
            
            // Remove active status
            tabButtons.forEach(b => b.classList.remove("active"));
            tabContents.forEach(c => c.classList.remove("active"));
            
            // Set current active
            btn.classList.add("active");
            document.getElementById(tabId).classList.add("active");
        });
    });
}

// Show/hide fields based on provider dropdown
function initLlmFieldsToggle() {
    llmProviderSelect.addEventListener("change", () => {
        const val = llmProviderSelect.value;
        if (val === "openai") {
            openaiFields.style.display = "flex";
            geminiFields.style.display = "none";
        } else {
            openaiFields.style.display = "none";
            geminiFields.style.display = "flex";
        }
    });
}

// ==========================================================================
// API CLIENT - REST FETCH & SAVE
// ==========================================================================
async function loadSettings() {
    try {
        const res = await fetch("/api/config");
        if (!res.ok) throw new Error("获取配置失败");
        currentConfig = await res.json();
        
        // Populate inputs
        liveUrlInput.value = currentConfig.live_url || "";
        aiReplyToggle.checked = currentConfig.ai_reply_enabled;
        smartTriggersToggle.checked = currentConfig.smart_triggers.enabled;
        
        // Populate LLM Settings
        llmProviderSelect.value = currentConfig.llm_provider || "openai";
        llmProviderSelect.dispatchEvent(new Event("change")); // trigger display update
        
        openaiApiBase.value = currentConfig.openai_api_base || "https://api.openai.com/v1";
        openaiModel.value = currentConfig.openai_model || "gpt-3.5-turbo";
        openaiApiKey.value = currentConfig.openai_api_key || "";
        
        geminiModel.value = currentConfig.gemini_model || "gemini-1.5-flash";
        geminiApiKey.value = currentConfig.gemini_api_key || "";
        
        systemPromptInput.value = currentConfig.system_prompt || "";
        
        // Populate Smart Triggers
        const triggers = currentConfig.smart_triggers;
        smartSilence5m.value = triggers.silence_5m_content || "";
        smartSilence10m.value = triggers.silence_10m_content || "";
        smartLike100.value = triggers.like_100_content || "";
        
        // Render Tables
        renderRulesTable();
        renderTimersTable();
        
        appendLog("system", "INFO", "配置已成功加载");
    } catch (err) {
        console.error("Failed to load settings:", err);
        appendLog("system", "ERROR", `加载配置发生错误: ${err.message}`);
    }
}

async function saveSettings(silent = true) {
    try {
        const res = await fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(currentConfig)
        });
        if (!res.ok) throw new Error("保存配置失败");
        if (!silent) {
            appendLog("system", "INFO", "设置保存成功");
        }
    } catch (err) {
        console.error("Failed to save settings:", err);
        appendLog("system", "ERROR", `保存配置发生错误: ${err.message}`);
    }
}

// ==========================================================================
// SUB-FORM ACTIONS
// ==========================================================================
function saveLlmConfig() {
    currentConfig.llm_provider = llmProviderSelect.value;
    currentConfig.openai_api_base = openaiApiBase.value.trim();
    currentConfig.openai_model = openaiModel.value.trim();
    currentConfig.openai_api_key = openaiApiKey.value.trim();
    currentConfig.gemini_model = geminiModel.value.trim();
    currentConfig.gemini_api_key = geminiApiKey.value.trim();
    currentConfig.system_prompt = systemPromptInput.value.trim();
    
    saveSettings(false);
}

function saveSmartConfig() {
    currentConfig.smart_triggers.silence_5m_content = smartSilence5m.value.trim();
    currentConfig.smart_triggers.silence_10m_content = smartSilence10m.value.trim();
    currentConfig.smart_triggers.like_100_content = smartLike100.value.trim();
    
    saveSettings(false);
}

// Rules Manager
function addKeywordRule() {
    const kw = ruleKeywordInput.value.trim();
    const rep = ruleReplyInput.value.trim();
    
    if (!kw || !rep) {
        alert("请输入完整的关键词和回复内容！");
        return;
    }
    
    // Avoid duplicate keywords
    if (currentConfig.rules.some(r => r.keyword.toLowerCase() === kw.toLowerCase())) {
        alert("该关键词已存在！");
        return;
    }
    
    currentConfig.rules.push({ keyword: kw, reply: rep });
    ruleKeywordInput.value = "";
    ruleReplyInput.value = "";
    
    renderRulesTable();
    saveSettings();
}

function deleteKeywordRule(index) {
    currentConfig.rules.splice(index, 1);
    renderRulesTable();
    saveSettings();
}

function renderRulesTable() {
    rulesListBody.innerHTML = "";
    if (currentConfig.rules.length === 0) {
        rulesListBody.innerHTML = '<tr><td colspan="3" style="text-align: center; color: var(--text-muted);">暂无规则，请在上方添加</td></tr>';
        return;
    }
    
    currentConfig.rules.forEach((rule, idx) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td class="cell-keyword">${escapeHtml(rule.keyword)}</td>
            <td>${escapeHtml(rule.reply)}</td>
            <td class="action-cell">
                <button class="btn-delete" onclick="deleteKeywordRule(${idx})">🗑️</button>
            </td>
        `;
        rulesListBody.appendChild(tr);
    });
}

// Scheduled Timer Manager
function addTimerAnnouncement() {
    const secs = parseInt(timerSecondsInput.value.trim());
    const content = timerContentInput.value.trim();
    
    if (isNaN(secs) || secs < 10 || !content) {
        alert("时间间隔必须是数字且不小于10秒，且内容不能为空！");
        return;
    }
    
    currentConfig.scheduled_messages.push({
        interval: secs,
        content: content,
        enabled: true
    });
    
    timerSecondsInput.value = "";
    timerContentInput.value = "";
    
    renderTimersTable();
    saveSettings();
}

function deleteTimerAnnouncement(index) {
    currentConfig.scheduled_messages.splice(index, 1);
    renderTimersTable();
    saveSettings();
}

function toggleTimerAnnouncement(index) {
    currentConfig.scheduled_messages[index].enabled = !currentConfig.scheduled_messages[index].enabled;
    renderTimersTable();
    saveSettings();
}

function renderTimersTable() {
    timersListBody.innerHTML = "";
    if (currentConfig.scheduled_messages.length === 0) {
        timersListBody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">暂无定时计划，请在上方添加</td></tr>';
        return;
    }
    
    currentConfig.scheduled_messages.forEach((timer, idx) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td class="cell-time">${timer.interval} 秒</td>
            <td>${escapeHtml(timer.content)}</td>
            <td style="text-align: center;">
                <label class="switch" style="transform: scale(0.85);">
                    <input type="checkbox" ${timer.enabled ? 'checked' : ''} onchange="toggleTimerAnnouncement(${idx})">
                    <span class="slider round"></span>
                </label>
            </td>
            <td class="action-cell">
                <button class="btn-delete" onclick="deleteTimerAnnouncement(${idx})">🗑️</button>
            </td>
        `;
        timersListBody.appendChild(tr);
    });
}

// ==========================================================================
// CONTROL SYSTEM (START / STOP)
// ==========================================================================
async function startBot() {
    const url = liveUrlInput.value.trim();
    if (!url) {
        alert("请输入合法的抖音直播间地址！");
        return;
    }
    
    btnStart.classList.add("btn-disabled");
    btnStart.disabled = true;
    
    try {
        const res = await fetch("/api/control/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ live_url: url })
        });
        if (!res.ok) throw new Error("启动机器人请求被拒绝");
        
        appendLog("system", "INFO", "正在初始化浏览器引擎，请查看打开的浏览器窗口...");
    } catch (err) {
        appendLog("system", "ERROR", `启动失败: ${err.message}`);
        btnStart.classList.remove("btn-disabled");
        btnStart.disabled = false;
    }
}

async function stopBot() {
    btnStop.classList.add("btn-disabled");
    btnStop.disabled = true;
    
    try {
        const res = await fetch("/api/control/stop", { method: "POST" });
        if (!res.ok) throw new Error("停止机器人请求被拒绝");
        appendLog("system", "INFO", "正在关闭直播助手...");
    } catch (err) {
        appendLog("system", "ERROR", `停止操作失败: ${err.message}`);
        btnStop.classList.remove("btn-disabled");
        btnStop.disabled = false;
    }
}

// ==========================================================================
// WEBSOCKET LOG STREAM & STATE SYNC
// ==========================================================================
function connectWebSocket() {
    if (wsConn) {
        wsConn.close();
    }
    
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/logs`;
    
    wsConn = new WebSocket(wsUrl);
    
    wsConn.onopen = () => {
        console.log("WebSocket connected.");
        if (reconnectTimer) {
            clearInterval(reconnectTimer);
            reconnectTimer = null;
        }
    };
    
    wsConn.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleWsMessage(data);
        } catch (err) {
            console.error("Error parsing WebSocket message:", err);
        }
    };
    
    wsConn.onclose = () => {
        console.log("WebSocket disconnected. Retrying in 3s...");
        updateUiStatus("stopped");
        // Try to reconnect
        if (!reconnectTimer) {
            reconnectTimer = setInterval(connectWebSocket, 3000);
        }
    };
    
    wsConn.onerror = (err) => {
        console.error("WebSocket error:", err);
    };
}

function handleWsMessage(data) {
    if (data.type === "status") {
        updateUiStatus(data.status);
    } else if (data.type === "system") {
        appendLog("system", data.level, data.text, data.timestamp);
    } else if (data.type === "chat") {
        appendLog("chat", "", `${data.username}: ${data.content}`, data.timestamp, data.username);
    } else if (data.type === "reply") {
        appendLog("reply", data.source, `回复给 [${data.username}]: ${data.reply}`, data.timestamp, data.comment);
    }
}

function updateUiStatus(status) {
    currentStatus = status;
    statusDot.className = "status-dot";
    
    if (status === "running") {
        statusDot.classList.add("status-running");
        statusText.innerText = "正在运行";
        
        btnStart.classList.add("btn-disabled");
        btnStart.disabled = true;
        btnStop.classList.remove("btn-disabled");
        btnStop.disabled = false;
        
        liveUrlInput.disabled = true;
    } else if (status === "logging_in") {
        statusDot.classList.add("status-logging_in");
        statusText.innerText = "等待登录中...";
        
        btnStart.classList.add("btn-disabled");
        btnStart.disabled = true;
        btnStop.classList.remove("btn-disabled");
        btnStop.disabled = false;
        
        liveUrlInput.disabled = true;
    } else {
        statusDot.classList.add("status-stopped");
        statusText.innerText = "已停止";
        
        btnStart.classList.remove("btn-disabled");
        btnStart.disabled = false;
        btnStop.classList.add("btn-disabled");
        btnStop.disabled = true;
        
        liveUrlInput.disabled = false;
    }
}

// ==========================================================================
// UTILS & DISPLAY LOG GENERATOR
// ==========================================================================
function appendLog(type, subType, text, timestamp = null, meta = "") {
    if (!timestamp) {
        timestamp = new Date().toLocaleTimeString();
    }
    
    const line = document.createElement("div");
    
    if (type === "system") {
        line.className = "log-line system-line";
        let levelLabel = subType;
        let levelClass = `level-${subType.toLowerCase()}`;
        line.innerHTML = `[${timestamp}] [<span class="${levelClass}">${levelLabel}</span>] ${escapeHtml(text)}`;
    } else if (type === "chat") {
        line.className = "log-line chat-line";
        // meta holds username, text holds "Username: comment"
        const username = meta;
        const msg = text.substring(username.length + 2);
        line.innerHTML = `[${timestamp}] <span class="chat-user">${escapeHtml(username)}</span>: <span class="chat-text">${escapeHtml(msg)}</span>`;
    } else if (type === "reply") {
        line.className = "log-line reply-line";
        // subType is 'rule' or 'ai'
        // text is "回复给 [user]: reply"
        const sourceLabel = subType === "rule" ? "规则匹配" : "AI回答";
        const sourceClass = `reply-source-${subType}`;
        line.innerHTML = `[${timestamp}] [<span class="${sourceClass}">${sourceLabel}</span>] ${escapeHtml(text)}`;
    }
    
    logTerminal.appendChild(line);
    
    // Auto Scroll to Bottom
    logTerminal.scrollTop = logTerminal.scrollHeight;
}

function escapeHtml(str) {
    if (!str) return "";
    return str
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Expose table modifiers to window scope for inline calls
window.deleteKeywordRule = deleteKeywordRule;
window.deleteTimerAnnouncement = deleteTimerAnnouncement;
window.toggleTimerAnnouncement = toggleTimerAnnouncement;
