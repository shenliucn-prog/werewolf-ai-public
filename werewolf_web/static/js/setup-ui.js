// First-run connection guidance and authored public character selection.
let setupToken = null;
let knownConnections = [];
let characterCatalog = [];

function setupText(zh, en) { return uiLocale === "en" ? en : zh; }
function feedback(text, failed=false) {
  $("#connectionFeedback").textContent = text;
  $("#connectionFeedback").classList.toggle("error-message", failed);
}

function connectionSummary() {
  const mode = $("#driverMode").value;
  const connection = knownConnections.find(c => c.name === $("#agentConnection").value);
  let text;
  if (mode === "agent" && connection) {
    text = `${connection.name} · ${connection.model || "—"} · ${connection.effort || "default"} · ${connection.max_calls || 240} ${setupText("次/局", "calls/game")}`;
  } else if (mode === "agent") {
    text = setupText("还没有连接。展开下方“添加本机 Agent 连接”。", "No connection yet. Open Add local Agent connection below.");
  } else if (mode === "api") {
    text = setupText("按当前填写的 API 设置检查；更改后需重新检查。", "Check the API settings entered above; changes require a new check.");
  } else if (mode === "offline") {
    text = setupText("离线程序策略，不调用模型、不计闯关成绩。", "Offline rules: no model calls or campaign score.");
  } else {
    text = setupText("使用本地已保存配置。点击检查查看实际模型；不会自动选择离线。", "Use saved local settings. Check to see the actual model; offline is never selected automatically.");
  }
  $("#connectionSummary").textContent = text;
  $("#registerConnection").hidden = mode !== "agent";
  $("#checkConnection").hidden = mode === "offline";
}

async function refreshConnectionSetup() {
  try {
    const response = await fetch("/api/connection/setup");
    if (!response.ok) throw new Error();
    const info = await response.json();
    setupToken = info.token;
    $("#registerCodex").disabled = !info.codex_installed;
    $("#codexAvailability").textContent = info.codex_installed
      ? setupText("检测到 Codex。安装不等于已登录；登记后请检查连接。", "Codex detected. Installation does not prove login; check after registering.")
      : setupText("未检测到 Codex CLI。先在本机安装并登录，再刷新本页。", "Codex CLI was not found. Install and log in locally, then reload this page.");
    const entries = await fetch("/api/agent_connections");
    if (!entries.ok) throw new Error();
    knownConnections = (await entries.json()).connections || [];
    await loadAgentConnections();
    connectionSummary();
  } catch (_) {
    feedback(setupText("无法读取连接设置，请刷新重试。", "Cannot load connection settings. Reload and retry."), true);
  }
}

async function setupRequest(path, payload) {
  if (!setupToken) throw new Error(setupText("请刷新本页后重试。", "Reload this page and retry."));
  const response = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json", "X-Setup-Token":setupToken}, body:JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Connection request failed");
  return data;
}

$("#registerCodex").onclick = async () => {
  const button = $("#registerCodex"); button.disabled = true;
  try {
    const name = $("#connectionName").value.trim();
    if (knownConnections.some(c => c.name === name) && !window.confirm(setupText("更新这个已有连接？不会改变正在进行的对局。", "Update this existing connection? A running game is unchanged."))) return;
    await setupRequest("/api/connection/register", {name, model:$("#connectionModel").value.trim(), effort:$("#connectionEffort").value, max_calls:Number($("#connectionBudget").value)});
    await refreshConnectionSetup();
    $("#agentConnection").value = name;
    connectionSummary();
    feedback(setupText("已登记，尚未验证。点击“检查连接”；这一步没有调用模型。", "Registered, not yet verified. Choose Check connection; registration made no model call."));
    $("#checkConnection").focus();
  } catch (error) { feedback(error.message, true); }
  finally { button.disabled = false; }
};

$("#checkConnection").onclick = async () => {
  const button = $("#checkConnection"); button.disabled = true;
  feedback(setupText("正在检查连接，不会发牌…", "Checking connection; no cards will be dealt…"));
  try {
    const data = await setupRequest("/api/connection/check", {...driverSelection(), llm:configuredLlmOptions()});
    const s = data.summary;
    feedback(setupText("连接通过", "Connection passed") + ` · ${s.driver}${s.adapter ? "/" + s.adapter : ""} · ${s.model || "default"} · ${s.effort || "default"} · ${s.max_calls} ` + setupText("次/局。开局会再次预检。", "calls/game. Starting a game checks again."));
  } catch (error) { feedback(error.message, true); }
  finally { button.disabled = false; }
};

function renderCharacterPreview() {
  const choice = $("#characterChoice").value;
  const character = characterCatalog.find(c => c.id === choice);
  document.querySelector(".cast-settings").hidden = choice !== "custom";
  $("#characterPreview").innerHTML = character
    ? `<img src="${character.portrait}" alt="${escapeHtml(character.name)}"><div><h3>${escapeHtml(character.name)} · ${escapeHtml(character.title)}</h3><p>${escapeHtml(character.story)}</p><blockquote>${escapeHtml(character.phrase)}</blockquote><details><summary>${setupText("说话方式", "Speaking style")}</summary><p>${escapeHtml(character.voice || character.description)}</p></details></div>`
    : `<p>${choice === "custom" ? setupText("在下方分别设置名字和人格。", "Customize names and personalities below.") : setupText(`从 ${characterCatalog.length} 位人物中随机成为一位，每局再抽取 11 位不同的同桌。名字、肖像与性格绑定，秘密身份独立。`, `Become one of ${characterCatalog.length} characters; draw 11 distinct tablemates each game. Names, portraits and personalities stay together, independently of secret roles.`)}</p>`;
  document.querySelectorAll("#characterCards button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.character === choice)));
  if (choice !== "custom") $("#offlineCharacter").value = choice;
}

function filterCharacterCards() {
  const query = $("#characterSearch").value.trim().toLocaleLowerCase();
  let count = 0;
  document.querySelectorAll("#characterCards button").forEach(button => {
    const c = characterCatalog.find(item => item.id === button.dataset.character);
    button.hidden = !`${c.name} ${c.title} ${c.story} ${c.description}`.toLocaleLowerCase().includes(query);
    if (!button.hidden) count++;
  });
  $("#characterCount").textContent = count
    ? setupText(`${count} / ${characterCatalog.length} 位人物 · 每局 12 位`, `${count} / ${characterCatalog.length} characters · 12 per game`)
    : setupText("没有匹配人物，换个词或清空搜索。", "No matching characters. Try another term or clear the search.");
}

async function loadCharacterCards() {
  try {
    const response = await fetch(`/api/offline/cast?locale=${encodeURIComponent(uiLocale)}`);
    if (!response.ok) throw new Error();
    const data = await response.json();
    const previous = $("#characterChoice").value;
    characterCatalog = data.characters;
    if (!Array.isArray(characterCatalog)) throw new Error();
    $("#characterChoice").innerHTML = `<option value="random">${tr("随机人物（名字、头像、人格绑定）")}</option><option value="custom">${tr("自定义名字与人格")}</option>`;
    $("#characterCards").innerHTML = "";
    for (const c of characterCatalog) {
      $("#characterChoice").add(new Option(`${c.name} · ${c.title}`, c.id));
      const button = document.createElement("button");
      button.type = "button"; button.dataset.character = c.id;
      button.innerHTML = `<img src="${c.portrait}" alt="" loading="lazy"><strong>${escapeHtml(c.name)}</strong><span>${escapeHtml(c.title)}</span>`;
      button.setAttribute("aria-label", setupText("选择人物：", "Choose character: ") + c.name);
      button.onclick = () => { $("#characterChoice").value = c.id; renderCharacterPreview(); };
      $("#characterCards").appendChild(button);
    }
    $("#characterChoice").value = [...$("#characterChoice").options].some(o => o.value === previous) ? previous : "random";
    renderCharacterPreview();
    filterCharacterCards();
  } catch (_) {
    $("#characterPreview").textContent = setupText("人物未能加载，请刷新重试。", "Characters could not load. Reload and retry.");
  }
}

$("#characterChoice").onchange = renderCharacterPreview;
$("#characterSearch").oninput = filterCharacterCards;
$("#driverMode").addEventListener("change", () => { connectionSummary(); feedback(""); });
$("#agentConnection").addEventListener("change", () => { connectionSummary(); feedback(""); });
$("#apiFields").addEventListener("input", () => feedback(setupText("设置已改变，请重新检查连接。", "Settings changed; check the connection again.")));
$("#locale").addEventListener("change", () => { loadCharacterCards(); refreshConnectionSetup(); });

const jump = $("#actionJump");
const updateJump = () => { jump.hidden = panelEl.style.display === "none" || !panelEl.children.length; };
new MutationObserver(updateJump).observe(panelEl, {attributes:true, childList:true});
jump.onclick = () => { panelEl.scrollIntoView({block:"center", behavior:window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"}); panelEl.focus({preventScroll:true}); };
loadCharacterCards(); refreshConnectionSetup(); updateJump();
