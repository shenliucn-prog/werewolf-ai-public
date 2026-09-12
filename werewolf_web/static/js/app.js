// ===== 狼人杀 Web 前端 =====
const PORTRAITS = {
  "dashan": "dashan", "amo": "amo", "alan": "alan", "xiaoman": "xiaoman",
  "yexiao": "yexiao", "xiaolu": "xiaolu", "aman": "aman", "tiandou": "tiandou",
  "xicao": "xicao", "laomai": "laomai", "aji": "aji", "acheng": "acheng",
  "大山": "dashan", "阿墨": "amo", "阿岚": "alan", "小满": "xiaoman",
  "夜枭": "yexiao", "小鹿": "xiaolu", "阿蛮": "aman", "甜豆": "tiandou",
  "细草": "xicao", "老麦": "laomai", "阿吉": "aji", "阿承": "acheng"
};

let es = null;
let gameId = null;
let lastEventNo = 0;
let rejoinAttempts = 0;
let faulted = false;    // 可恢复故障：保留对局与本地续玩记录，不自动重连
let campaignReviewGameId = null;   // 短复盘失败后保留的 game_id，供重试按钮使用
let campaignTeachingGameId = null; // 角色教学失败后保留的 game_id，供重试按钮使用
const SAVE_KEY = "werewolf.game";
let seats = {};        // pos -> seat DOM
let mySeat = null;
let pendingReq = null;
let uiLocale = "zh-CN";
let castRequest = 0;
let boardData = {boards: [], roles: {}};
let reviewFocus = null;
const UI = {"zh-CN": {brand:"暗夜茶馆 · 狼人杀", start:"开始自由对局", identity:"你的身份", host:"问主持人（规则单聊）", hint:"我只解释规则和公开流程，不会泄露身份或替你决策。", starting:"开局中...", failed:"开局失败"}, en: {brand:"Night Table · Werewolf", start:"Start free game", identity:"Your role", host:"Ask the Host (rules)", hint:"I explain rules and public flow only. I never reveal identities or choose for you.", starting:"Starting...", failed:"Could not start game"}};

const $ = (s) => document.querySelector(s);
const logEl = $("#log");
const tableEl = $("#table");
const panelEl = $("#actionPanel");

function applyLocale(value) {
  uiLocale = value === "en" ? "en" : "zh-CN"; const t = UI[uiLocale];
  document.documentElement.lang = uiLocale;
  document.title = t.brand;
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = tr(el.dataset.i18n); });
  document.querySelectorAll("input[placeholder]").forEach(el => {
    el.dataset.placeholder = el.dataset.placeholder || el.placeholder;
    el.placeholder = tr(el.dataset.placeholder);
  });
  $("#board").title = tr("选择板子");
  $("#playerRole").setAttribute("aria-label", tr("你的角色"));
  $(".center-logo").textContent = uiLocale === "en" ? "🐺" : "狼人杀";
  if (!gameId) $("#playerBody").textContent = tr("尚未入局");
  $("#brand").textContent = t.brand; $("#newGame").textContent = t.start;
  $("#identityTitle").textContent = t.identity; $("#hostChatTitle").textContent = t.host;
  $("#hostChatLog").textContent = t.hint;
  const command = `python -u -m werewolf_web.chat_game --board classic --lang ${uiLocale}`;
  $("#textCommand").textContent = uiLocale === "en"
    ? `Help me play Werewolf here in our conversation. Repository: https://github.com/shenliucn-prog/werewolf-ai-public\nRead README.md and docs/AGENT_PLAY.md, prepare the local environment, then keep this interactive process alive:\n${command}\nRelay the game's statements and my private prompts. Wait for my decisions; do not autoplay, invent game events or inspect hidden roles. If you cannot maintain an interactive process, tell me rather than simulating a game.`
    : `请让我在当前 Agent 对话里玩狼人杀。仓库：https://github.com/shenliucn-prog/werewolf-ai-public\n阅读 README.md 和 docs/AGENT_PLAY.md，准备本地环境，并持续保留以下交互进程：\n${command}\n转述游戏发言和属于我的私密提示，等待我的决定，不代打、不编造事件、不读取其他人的隐藏身份。如果无法保持交互进程，请说明限制，不要模拟一局冒充真实游戏。`;
  $("#copyStatus").textContent = "";
  updateDriverHint();
  updateContinueUI();
}

// ---------- 板子选择 ----------
async function loadBoards() {
  const locale = uiLocale;
  const r = await fetch(`/api/boards?locale=${encodeURIComponent(locale)}`);
  const d = await r.json();
  if (locale !== uiLocale) return;
  boardData = d;
  const sel = $("#board");
  const previous = sel.value;
  sel.innerHTML = "";
  (d.boards || []).forEach((b) => {
    const o = document.createElement("option");
    o.value = b.id; o.textContent = `${b.name}（${b.difficulty}）`;
    sel.appendChild(o);
  });
  if ([...sel.options].some(o => o.value === previous)) sel.value = previous;
  loadRoleChoices();
}

function loadRoleChoices() {
  const select = $("#playerRole");
  const previous = select.value;
  const board = boardData.boards.find(b => b.id === $("#board").value);
  $("#boardDescription").textContent = board?.desc || "";
  select.replaceChildren(new Option(tr("随机身份"), "random"));
  [...new Set(board?.roles || [])].forEach(role => {
    select.add(new Option(board?.role_labels?.[role] || boardData.roles?.[role]?.cn || role, role));
  });
  select.value = [...select.options].some(o => o.value === previous) ? previous : "random";
}

async function loadCast() {
  const request = ++castRequest;
  const locale = uiLocale;
  $("#randomNames").disabled = true;
  $("#newGame").disabled = true;
  try {
    const response = await fetch(`/api/cast?locale=${encodeURIComponent(locale)}`);
    if (!response.ok) throw new Error("cast unavailable");
    const data = await response.json();
    if (request !== castRequest || locale !== uiLocale) return;
    const savedChoices = Object.fromEntries([...document.querySelectorAll("#castNames select")]
      .map(input => [input.dataset.playerId, input.value]));
    $("#castNames").replaceChildren();
    data.players.forEach((player, index) => {
      const label = document.createElement("label");
      const caption = document.createElement("span");
      caption.textContent = player.is_player ? tr("你") : `NPC ${index}`;
      const input = document.createElement("input");
      input.dataset.playerId = player.id;
      input.value = player.name;
      input.maxLength = 24;
      input.autocomplete = "off";
      label.append(caption, input);
      if (!player.is_player) {
        const select = document.createElement("select");
        select.dataset.playerId = player.id;
        select.setAttribute("aria-label", `${caption.textContent} ${tr("名字与人格")}`);
        select.add(new Option(tr("每局随机"), "random"));
        (data.personalities || []).forEach(p => select.add(new Option(p.label, p.id)));
        select.value = savedChoices[player.id] || "random";
        label.append(select);
      }
      $("#castNames").append(label);
    });
    $("#castError").textContent = "";
  } catch (_) {
    if (request === castRequest) $("#castError").textContent = tr("名字加载失败，请重试。");
  } finally {
    if (request === castRequest) {
      $("#randomNames").disabled = Boolean(gameId);
      $("#newGame").disabled = false;
    }
  }
}

function lockNames(locked) {
  $("#randomNames").disabled = locked;
  $("#conjectureMode").disabled = locked;
  $("#board").disabled = locked;
  $("#playerRole").disabled = locked;
  document.querySelectorAll("#castNames input, #castNames select").forEach(input => { input.disabled = locked; });
}

// ---------- 座位渲染 ----------
function renderSeats(state) {
  document.body.classList.add("has-table");
  // 清掉旧座位（保留 moon/center）
  Object.values(seats).forEach((s) => s.el.remove());
  seats = {};
  const list = state.seats;
  list.forEach((s) => {
    const el = document.createElement("button");
    el.type = "button";
    el.dataset.seat = s.pos;
    const angle = (s.pos - 1) * Math.PI / 6 - Math.PI / 2;
    el.style.setProperty("--seat-x", `${50 + 40 * Math.cos(angle)}%`);
    el.style.setProperty("--seat-y", `${50 + 42 * Math.sin(angle)}%`);
    el.onclick = () => document.querySelector(`#actionPanel button[data-target="${s.pos}"]`)?.click();
    el.className = "seat";
    const file = typeof s.character_id === "string" && /^[a-z][a-z0-9_]{0,31}$/.test(s.character_id)
      ? s.character_id : PORTRAITS[s.player_id] || PORTRAITS[s.name] || "";
    const initial = s.name.slice(0, 1);
    el.innerHTML = `
      <div class="avatar">${escapeHtml(initial)}
        ${file ? `<img src="/img/portraits/${file}.png" alt="" onerror="this.remove()">` : ""}
      </div>
      <div class="name">${seatText(s.pos)} ${escapeHtml(s.name)}</div>
      <div class="seat-status"></div><div class="role-badge"></div>`;
    tableEl.appendChild(el);
    seats[s.pos] = { el, data: s };
    if (s.is_player) { mySeat = s.pos; el.classList.add("mine"); }
    if (s.alive === false) el.classList.add("dead");
    if (s.alive === false && s.role_cn) {
      el.querySelector(".role-badge").textContent = s.role_cn;
      el.querySelector(".role-badge").style.display = "inline-block";
    }
  });
  if (state.sheriff) markSheriff(state.sheriff);
  updateSeatLabels();
}

function updateSeatLabels() {
  const list = Object.values(seats);
  list.forEach(({el, data}) => {
    const flags = [];
    if (data.is_player) flags.push(tr("你"));
    if (el.classList.contains("sheriff")) flags.push(tr("警长"));
    flags.push(el.classList.contains("dead") ? tr("已出局") : tr("在场"));
    if (el.classList.contains("speaking")) flags.push(tr("发言中"));
    el.querySelector(".seat-status").textContent = flags.join(" · ");
  });
  const alive = list.filter(s => !s.el.classList.contains("dead")).length;
  $("#rosterCount").textContent = list.length ? `${alive} / ${list.length} ${tr("在场")}` : tr("发牌后显示完整座次");
}

function markSheriff(pos) {
  Object.values(seats).forEach((s) => s.el.classList.remove("sheriff"));
  if (seats[pos]) seats[pos].el.classList.add("sheriff");
  updateSeatLabels();
}
function markDead(pos) {
  if (seats[pos]) seats[pos].el.classList.add("dead");
  updateSeatLabels();
}
function revealRole(pos, roleCn) {
  const s = seats[pos];
  if (!s) return;
  s.el.classList.add("dead");
  const badge = s.el.querySelector(".role-badge");
  badge.style.display = "inline-block";
  badge.textContent = roleCn;
  updateSeatLabels();
}
function highlightSpeaker(pos) {
  Object.values(seats).forEach((s) => s.el.classList.remove("speaking"));
  if (seats[pos]) seats[pos].el.classList.add("speaking");
  updateSeatLabels();
  // A speech remains current until the next speaker/phase, not for 2.5 seconds.
}

// ---------- 日志 ----------
function log(text, cls = "") {
  const follow = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 60;
  logEl.querySelector(".empty-log")?.remove();
  const row = document.createElement("div");
  row.className = "row " + cls;
  row.innerHTML = text;
  logEl.appendChild(row);
  if (follow) logEl.scrollTop = logEl.scrollHeight;
  else $("#latestSpeech").hidden = false;
}
function narr(text) { log(escapeHtml(text), "narr"); }

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- 玩家身份 ----------
function showPlayer(pv) {
  $("#myRoleQuick").textContent = pv ? `${uiLocale === "en" ? "Your private role" : "你的私密身份"} · ${pv.role_cn}` : (uiLocale === "en" ? "Public spectator" : "公开旁观");
  if (!pv) {
    mySeat = null;
    $("#playerBody").textContent = uiLocale === "en" ? "Public spectator · no private information" : "公开旁观 · 不显示私密信息";
    return;
  }
  const el = $("#playerBody");
  let html = `${tr("你是")} <b>${seatText(pv.pos)} ${escapeHtml(pv.name)}</b><br>${tr("身份")}: <span class="role-tag">${escapeHtml(pv.role_cn)}</span>`;
  if (pv.ability) html += pv.ability.length > 180
    ? `<details><summary>${tr("技能规则（点击展开）")}</summary><p>${escapeHtml(pv.ability)}</p></details>`
    : `<p>${escapeHtml(pv.ability)}</p>`;
  if (pv.is_wolf && pv.wolfmates && pv.wolfmates.length) {
    html += `<br>${tr("狼队友")}: ${pv.wolfmates.map((m) => `<span class="wolfmate">${seatText(m)}</span>`).join(", ")}`;
  }
  el.innerHTML = html;
}

// ---------- 事件分发 ----------
function handleEvent(d) {
  if (typeof updateRoundtable === "function") updateRoundtable(d);
  switch (d.type) {
    case "badge": narr(d.text); markSheriff(d.target); break;
    case "state": renderSeats(d.state); break;
    case "discussion_closed":
      narr(d.text);
      for (const q of d.deferred || []) narr(`${q.from} → ${q.target} · ${uiLocale === "en" ? "deferred" : "暂缓"}`);
      break;
    case "init":
      applyLocale(d.state.locale);
      $("#locale").disabled = true;
      renderSeats(d.state); showPlayer(d.player);
      if (d.offline_choices) setModeBadge(uiLocale === "en" ? "Offline choices · not counted" : "离线选项 · 不计闯关成绩");
      showLlmStatus(d.llm_status);
      log(`🎙️ ${escapeHtml(d.host_intro)}`, "narr"); break;
    case "llm_status": showLlmStatus(d.llm_status); break;
    case "narration":
      narr(d.text);
      if (d.full_rules) log(`<details><summary>${uiLocale === "en" ? "Full rules for this table" : "本局完整规则"}</summary>${escapeHtml(d.full_rules).replace(/\n/g, "<br>")}</details>`, "narr");
      setPhase(d.phase); if (d.sheriff) markSheriff(d.sheriff); break;
    case "private": log(`🔒 ${escapeHtml(d.text)}`, "private"); break;
    case "speech":
      highlightSpeaker(d.seat);
      if (d.reply_to?.length) log(`<details><summary>${uiLocale === "en" ? "Replying to" : "回应的追问"}</summary>${d.reply_to.map(q => `<p>${escapeHtml(q.from)}：${escapeHtml(q.text)}</p>`).join("")}</details>`, "narr");
      log(`<b>${d.seat ? seatText(d.seat) + " · " : ""}${escapeHtml(d.name)}</b>${d.talk_kind === "last_words" ? (uiLocale === "en" ? " · Last words" : " · 遗言") : ""}：${escapeHtml(d.text)}`, "speech"); break;
    case "death": log(`💀 ${escapeHtml(d.text)}`, "death"); markDead(d.seat); break;
    case "flip": log(`🂠 ${escapeHtml(d.text)}`, "flip"); revealRole(d.seat, d.role_cn); break;
    case "exile": log(`⚖️ ${escapeHtml(d.text)}`, "exile"); markDead(d.seat); break;
    case "vote_result": showTally(d.tally); break;
    case "ballots": log(escapeHtml(d.text).replace(/\n/g, "<br>"), "narr"); break;
    case "host_rule": log(`🎲 ${escapeHtml(d.text)}`, "host-rule"); break;
    case "conjecture":
      d.tables.forEach(table => {
        log(`<details><summary>${escapeHtml(table.actor)} · ${tr("公开猜想表")} v${table.version}</summary>` +
          table.rows.map(row => `${escapeHtml(row.player)}: ${escapeHtml(d.labels?.[row.judgment] || row.judgment)} — ${escapeHtml(row.reason)}`).join("<br>") + "</details>", "speech");
      });
      break;
    case "request": showAction(d); break;
    case "teaching":
      log(d.unavailable ? `⚠️ ${escapeHtml(d.text)}` : `📖 ${escapeHtml(d.text)}`, "narr");
      if (d.unavailable) {
        if (gameId) campaignTeachingGameId = gameId;   // keep an id for the retry
        showCampaignTeachingRetry();
      } else {
        hideCampaignTeachingRetry();
      }
      break;
    case "campaign_review":
      log(`📋 ${escapeHtml(d.text).replace(/\n/g, "<br>")}`, "narr");
      if (d.unavailable) {
        if (gameId) campaignReviewGameId = gameId;   // keep an id for the retry
        showCampaignReviewRetry();
      } else {
        hideCampaignReviewRetry();
      }
      break;
    case "review": showReview(d.text); finishStream(tr("对局结束")); break;
    case "gameover":
      // 只标记胜负已定、禁用行动，不在此断流：身份揭晓(narration)与复盘(review)
      // 紧跟其后，关闭流会让它们丢失。结果流以 review（成功或兜底）为收尾信号。
      log(`🏆 ${escapeHtml(d.reason)}`, "win"); panelEl.style.display = "none"; break;
    case "error": log(escapeHtml(d.text), "err"); pauseStream(d.text); break;
  }
}

function showLlmStatus(status) {
  if (!status) return;
  const suffix = status.model ? ` · ${status.model}` : "";
  $("#status").textContent = `${tr(status.label || "本地策略运行中")}${suffix}`;
}

function appendHostChat(prefix, text) {
  const line = document.createElement("div");
  line.textContent = `${prefix} ${text}`;
  $("#hostChatLog").appendChild(line);
  $("#hostChatLog").scrollTop = $("#hostChatLog").scrollHeight;
}

async function askHostRule() {
  const input = $("#hostQuestion");
  const question = input.value.trim();
  if (!question || !gameId) return;
  input.value = "";
  appendHostChat(tr("你："), question);
  try {
    const response = await fetch("/api/host_chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_id: gameId, question })
    });
    const data = await response.json();
    appendHostChat(tr("主持人："), data.reply || tr("这局暂时无法回答，请稍后再问。"));
  } catch (_) {
    appendHostChat(tr("主持人："), tr("连接暂时不可用；你的对局不会受到影响。"));
  }
}

function configuredLlmOptions() {
  const mode = $("#llmMode").value;
  if (mode === "local") return { enabled: false };
  if (mode !== "custom") return null;
  const options = { enabled: true, api_key: $("#llmApiKey").value.trim() };
  [["base_url", "#llmBaseUrl"], ["model", "#llmModel"],
   ["reasoning_effort", "#llmReasoningEffort"],
   ["reasoning_param", "#llmReasoningParam"]].forEach(([key, selector]) => {
    const value = $(selector).value.trim();
    if (value) options[key] = value;
  });
  return options;
}

function driverSelection() {
  const mode = $("#driverMode").value;
  if (mode === "offline") return { driver: "offline" };
  if (mode === "agent") {
    const connection = $("#agentConnection").value.trim();
    return connection ? { driver: "agent", connection } : { driver: "agent" };
  }
  if (mode === "api") return { driver: "api" };
  return {};
}

function syncDriverUI() {
  const mode = $("#driverMode").value;
  const row = $("#agentConnectionRow");
  if (row) row.hidden = mode !== "agent";
  $("#apiFields").hidden = mode !== "api";
  // One visible selector; the legacy field remains only as an internal bridge.
  $("#llmMode").value = mode === "api" ? "custom" : mode === "offline" ? "local" : "";
  if (mode !== "api") $("#llmApiKey").value = "";
  updateDriverHint();
}

function updateDriverHint() {
  const hints = {
    "": "使用本地已保存的连接。未配置时会提示设置，不会自动转为离线。",
    api: "支持兼容接口与本地模型服务。密钥只用于本局，不写入设置。",
    agent: "只使用本机预配置连接；网页不接收可执行命令。",
    offline: "程序策略规则测试，不调用模型、不计闯关成绩。选项玩法见下方独立入口。"
  };
  $("#driverHint").textContent = tr(hints[$("#driverMode").value] || hints[""]);
}

async function loadAgentConnections() {
  const sel = $("#agentConnection");
  if (!sel) return;
  try {
    const response = await fetch("/api/agent_connections");
    const data = await response.json();
    const previous = sel.value;
    sel.innerHTML = "";
    (data.connections || []).forEach((c) => {
      const option = document.createElement("option");
      option.value = c.name;
      option.textContent = c.adapter ? `${c.name} (${c.adapter})` : c.name;
      sel.appendChild(option);
    });
    if (!(data.connections || []).length) {
      sel.appendChild(new Option(tr("无可用连接，请先在本地配置 Agent 连接。"), ""));
    } else if ([...sel.options].some((o) => o.value === previous)) {
      sel.value = previous;
    }
  } catch (_) { /* the connection list is optional */ }
}

function showSetupGuidance(message) {
  const el = $("#setupGuidance");
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
  $("#gameSetup").open = true;
}

function hideSetupGuidance() {
  const el = $("#setupGuidance");
  if (el) el.hidden = true;
}

function setPhase(phase) {
  const b = $("#phase-banner");
  if (phase === "day") {
    b.textContent = tr("☀️ 白天"); tableEl.classList.remove("night"); $("#moon").textContent = "🌕";
  } else if (phase === "night") {
    b.textContent = tr("🌙 夜晚"); tableEl.classList.add("night"); $("#moon").textContent = "🌑";
  }
}

function showTally(tally) {
  const entries = Object.entries(tally).sort((a, b) => b[1] - a[1]);
  const lines = entries.map(([pos, v]) => `${Number(pos) === 0 ? tr("平安日") : seatText(pos)}: ${v} ${tr("票")}`).join("　");
  log(`🗳️ ${tr("投票结果")}: ${lines || tr("无人投票（平安日）")}`, "narr");
}

// ---------- 玩家行动面板 ----------
function showAction(d) {
  pendingReq = d;
  // Bind buttons to this prompt, not whichever prompt is current on click.
  const submitAction = payload => sendActionForRequest(payload, d);
  const kind = d.kind, data = d.data || {};
  panelEl.style.display = "block";
  panelEl.innerHTML = "";
  if (Array.isArray(d.choices)) {
    const hint = document.createElement("p");
    hint.textContent = data.last_words ? (uiLocale === "en" ? "Your last words. Choose a statement or skip." : "你的遗言：选择一句话，或跳过。") : data.final_reply ? tr("投票前，留给你一次完整回应") + "。" + tr("可以集中解释刚才的质疑，也可以跳过。提交后进入投票，不再追加追问。")
      : kind === "ready" ? tr("先阅读本局规则，有疑问可问主持人。确认后才进入第一夜。")
      : (uiLocale === "en" ? "Respond, or listen for now" : "接着桌上的话，也可以先听听");
    panelEl.append(hint);
    const suggested = d.choices.filter(c => c.suggested);
    const renderChoices = (choices, parent) => {
      let group = null;
      for (const choice of choices) {
        if (group !== choice.group) {
          group = choice.group;
          const title = document.createElement("h3"); title.textContent = group; parent.append(title);
        }
        const button = document.createElement("button");
        button.textContent = choice.label;
        button.onclick = () => submitAction({choice_id: choice.id});
        parent.append(button);
      }
    };
    renderChoices(suggested.length ? suggested : d.choices, panelEl);
    if (suggested.length) {
      const more = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = uiLocale === "en" ? "Other responses" : "其他说法";
      more.append(summary);
      renderChoices(d.choices.filter(c => !c.suggested), more);
      panelEl.append(more);
    }
  } else if (kind === "model_retry") {
    const hint = document.createElement("p"); hint.textContent = tr("模型连接暂停，不会切换离线玩家。");
    const retry = document.createElement("button"); retry.textContent = tr("重试");
    retry.onclick = () => submitAction({retry: true});
    const stop = document.createElement("button"); stop.textContent = tr("结束本局");
    stop.onclick = () => submitAction({retry: false});
    panelEl.append(hint, retry, stop);
  } else if (kind === "ready") {
    const hint = document.createElement("p");
    hint.textContent = tr("先阅读本局规则，有疑问可问主持人。确认后才进入第一夜。");
    const button = document.createElement("button");
    button.id = "readyGame"; button.textContent = tr("准备好了，进入第一夜");
    button.onclick = () => submitAction({ready: true});
    const ask = document.createElement("button"); ask.textContent = tr("提问");
    ask.onclick = () => { document.querySelector(".host-chat").open = true; $("#hostQuestion").focus(); };
    panelEl.append(hint, ask, button);
  } else if (kind === "conjecture") {
    const hint = document.createElement("p"); hint.textContent = data.hint; panelEl.append(hint);
    const editors = {};
    for (const scope of ["private", "public"]) {
      const details = document.createElement("details"); details.open = scope === "public";
      const summary = document.createElement("summary");
      summary.textContent = tr(scope === "private" ? "私有判断" : "公开辩论"); details.append(summary);
      editors[scope] = data[scope].map(row => {
        const label = document.createElement("label"); label.style.display = "block";
        const name = document.createElement("span"); name.textContent = row.player + " ";
        const select = document.createElement("select");
        select.setAttribute("aria-label", `${summary.textContent}: ${row.player}`);
        data.options.forEach(value => select.add(new Option(data.option_labels?.[value] || value, value))); select.value = row.judgment;
        select.disabled = scope === "private" && Boolean(data.locked_private?.[row.player]);
        const reason = document.createElement("input"); reason.maxLength = 500;
        reason.setAttribute("aria-label", `${summary.textContent}: ${row.player} ${tr("判断理由")}`);
        reason.placeholder = tr("判断理由"); reason.value = row.reason;
        label.append(name, select, reason); details.append(label);
        return () => ({player: row.player, judgment: select.value, reason: reason.value});
      });
      panelEl.append(details);
    }
    const submit = document.createElement("button"); submit.textContent = tr("提交双表");
    submit.onclick = () => submitAction(Object.fromEntries(Object.entries(editors)
      .map(([scope, rows]) => [scope, rows.map(read => read())])));
    panelEl.append(submit);
  } else if (kind === "speech") {
    panelEl.innerHTML = `<h4>${tr("轮到你发言")} (${escapeHtml(data.phase || "")})</h4>
      <textarea id="speechInput" maxlength="4000" aria-label="${tr("轮到你发言")}" placeholder="${tr("输入你的发言...")}"></textarea>
      <button class="send-btn" id="sendSpeech">${tr("发送发言")}</button>`;
    $("#sendSpeech").onclick = () => {
      const t = $("#speechInput").value.trim();
      if (!t) return;
      submitAction({ text: t });
    };
  } else if (kind === "table_reply") {
    panelEl.innerHTML = `<h4>${escapeHtml(data.from || tr("有人"))} ${tr("正在打岔")}</h4>
      <div class="talk-quote">${escapeHtml(data.text || "")}</div>
      <textarea id="tableReplyInput" maxlength="4000" aria-label="${tr("回应")}" placeholder="${tr("简短回应，或让主持人继续推进...")}"></textarea>
      <div class="btn-row"><button class="cand-btn" id="skipTableReply">${tr("暂不回应")}</button>
      <button class="send-btn" id="sendTableReply">${tr("回应")}</button></div>`;
    $("#skipTableReply").onclick = () => submitAction({ text: "" });
    $("#sendTableReply").onclick = () => submitAction({ text: $("#tableReplyInput").value.trim() });
  } else if (kind === "table_answer") {
    panelEl.innerHTML = `<h4>${data.last_words ? (uiLocale === "en" ? "Your last words" : "请留下遗言") : data.final_reply ? tr("投票前，留给你一次完整回应") : `${escapeHtml(data.from || tr("有人"))} ${tr("在追问你")}`}</h4>
      ${(data.questions || []).map(q => `<blockquote class="talk-quote"><b>${escapeHtml(q.from)}</b> · ${q.event_no ? `#${Number(q.event_no)}` : ""}<br>${escapeHtml(q.text)}</blockquote>`).join("")}
      ${data.final_reply ? `<p>${tr("可以集中解释刚才的质疑，也可以跳过。提交后进入投票，不再追加追问。")}</p>` : ""}
      <textarea id="tableAnswerInput" maxlength="4000" aria-label="${tr("回答")}" placeholder="${tr("简短回应，或让主持人继续推进...")}"></textarea>
      <div class="btn-row"><button class="cand-btn" id="skipTableAnswer">${tr("跳过")}</button>
      <button class="send-btn" id="sendTableAnswer">${tr("回答")}</button></div>`;
    $("#skipTableAnswer").onclick = () => submitAction({ skip: true });
    $("#sendTableAnswer").onclick = () => submitAction({ answer: $("#tableAnswerInput").value.trim() });
  } else if (kind === "election_withdraw") {
    panelEl.innerHTML = `<p>${tr("警上发言结束，是否退警？")}</p><button id="withdrawYes">${tr("退警")}</button><button id="withdrawNo">${tr("不退警")}</button>`;
    $("#withdrawYes").onclick = () => submitAction({withdraw:true});
    $("#withdrawNo").onclick = () => submitAction({withdraw:false});
  } else if (kind === "election_up") {
    panelEl.innerHTML = `<h4>${tr("是否上警竞选警长？")}</h4>
      <div class="btn-row">
        <button class="cand-btn" id="upYes">${tr("上警")}</button>
        <button class="cand-btn" id="upNo">${tr("不上警")}</button>
      </div>`;
    $("#upYes").onclick = () => submitAction({ up: true });
    $("#upNo").onclick = () => submitAction({ up: false });
  } else if (kind === "vote") {
    const cands = data.candidates || [];
    panelEl.innerHTML = `<h4>${tr(data.sheriff ? "投票选警长" : "投票放逐")}</h4><div class="btn-row" id="voteBtns"></div>
      <button class="send-btn" id="sendVote" disabled>${tr("确认投票")}</button>`;
    const btns = $("#voteBtns"); let sel = null;
    cands.forEach((c) => {
      const b = document.createElement("button");
      b.className = "cand-btn";
      b.dataset.target = c.pos;
      b.textContent = c.pos === 0 ? tr("平安日") : `${seatText(c.pos)} ${c.name}${c.note ? " (" + c.note + ")" : ""}`;
      b.onclick = () => {
        sel = c.pos;
        [...btns.children].forEach((x) => x.classList.remove("sel"));
        b.classList.add("sel");
        $("#sendVote").disabled = false;
        $("#sendVote").textContent = `${tr("确认投票")} → ${c.pos === 0 ? tr("平安日") : seatText(c.pos) + " " + c.name}`;
      };
      btns.appendChild(b);
    });
    $("#sendVote").onclick = () => submitAction({ target: sel });
  } else if (kind === "night" || kind === "day_skill") {
    // 夜间行动：target 或 女巫 save/poison
    const cands = data.candidates || [];
    const isWitch = data.role_key === "witch" || data.role === "女巫";
    let html = `<h4>${escapeHtml(data.role)} · ${escapeHtml(data.desc || "")}</h4>`;
    if (isWitch) {
      const options = items => items.map(c => `<option value="${c.pos}">${seatText(c.pos)} ${escapeHtml(c.name)}</option>`).join("");
      html += `<div><label for="saveSel">${tr("救人")}</label>: <select id="saveSel" ${data.antidote === false ? "disabled" : ""}><option value="">${tr("不救")}</option>${options(data.save_candidates || cands)}</select></div>
        <div style="margin-top:6px"><label for="poisonSel">${tr("毒人")}</label>: <select id="poisonSel" ${data.poison === false ? "disabled" : ""}><option value="">${tr("不毒")}</option>${options(cands)}</select></div>`;
    } else {
      html += `<div class="btn-row" id="nightBtns"></div>`;
    }
    html += `<button class="send-btn" id="sendNight">${isWitch ? tr("确认") : data.role_key === "badge" ? (uiLocale === "en" ? "Destroy badge" : "撕毁警徽") : tr("跳过")}</button>`;
    panelEl.innerHTML = html;
    if (!isWitch) {
      const btns = $("#nightBtns"); let sel = null;
      cands.forEach((c) => {
        const b = document.createElement("button");
        b.className = "cand-btn";
        b.dataset.target = c.pos;
        b.textContent = `${seatText(c.pos)} ${c.name}${c.note || ""}`;
        if (c.note) b.classList.add("self-knife");
        b.onclick = () => {
          sel = c.pos;
          [...btns.children].forEach((x) => x.classList.remove("sel"));
          b.classList.add("sel");
          $("#sendNight").textContent = `${tr("确认")} → ${seatText(c.pos)} ${c.name}`;
        };
        btns.appendChild(b);
      });
      $("#sendNight").onclick = () => submitAction({ target: sel });
    } else {
      $("#saveSel").onchange = () => { if (!data.dual_potions && $("#saveSel").value) $("#poisonSel").value = ""; };
      $("#poisonSel").onchange = () => { if (!data.dual_potions && $("#poisonSel").value) $("#saveSel").value = ""; };
      $("#sendNight").onclick = () => submitAction({
        save: $("#saveSel").value ? Number($("#saveSel").value) : null,
        poison: $("#poisonSel").value ? Number($("#poisonSel").value) : null
      });
    }
  }
}

async function submitAction(payload) {
  return sendActionForRequest(payload, pendingReq);
}

async function sendActionForRequest(payload, submitted) {
  if (!payload) return;
  if (submitted !== pendingReq) return;
  panelEl.style.display = "none";
  try {
  const response = await fetch("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, game_id: gameId, request_id: submitted?.request_id })
  });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error("action rejected");
  } catch (_) {
    if (pendingReq === submitted) panelEl.style.display = "block";
    log(tr("操作发送失败，请重试。"), "err");
  }
}

function finishStream(status) {
  if (es) es.close();
  $("#status").textContent = status;
  $("#locale").disabled = false;
  panelEl.style.display = "none";
  gameId = null;
  document.body.classList.remove("playing");
  lockNames(false);
  setModeBadge(null);
  persistState();
}

// Persistent mode label (independent of the running-status line): offline
// simulation "not counted" survives status updates and reconnect.
function setModeBadge(text) {
  const el = $("#modeBadge");
  if (text) { el.textContent = text; el.hidden = false; }
  else { el.hidden = true; el.textContent = ""; }
}

// Explicitly abandon the current game (settle + delete its save) before a new
// start.  Returns true on success; false means the old game is still valid.
async function endCurrentGame() {
  if (!gameId) return true;
  const current = gameId;
  try {
    const response = await fetch("/api/leave", { method: "POST", headers: { "Content-Type": "application/json" },
                                                body: JSON.stringify({ game_id: current }) });
    const data = await response.json();
    return response.ok && data.ok;
  } catch (_) {
    return false;   // network error: keep the old game + its resume record
  }
}

// 可恢复故障（§3.3）：断流但不清理对局——保留 gameId 与本地续玩记录，后续可重连续玩。
// 完整重试入口留到教学/复盘里程碑；这里只保证「故障可恢复」在网页上有闭环。
function pauseStream(status) {
  faulted = true;
  if (es) es.close();
  $("#status").textContent = status;
  panelEl.style.display = "none";
  document.body.classList.remove("playing");
  persistState();   // gameId 仍在，保留同一局的恢复信息
}

// 胜负已定但复盘尚未生成（崩溃发生在复盘前）：展示待完成状态，不误判为全部完成，
// 且不清除续接信息。
function showReviewPending() {
  showReview(tr("复盘暂不可用，可稍后重试。"));
}

// ---------- 断线重连 / 恢复（§6）----------
function persistState() {
  try {
    if (gameId) localStorage.setItem(SAVE_KEY, JSON.stringify({ game_id: gameId, last_event_no: lastEventNo }));
    else localStorage.removeItem(SAVE_KEY);
  } catch (_) { /* storage unavailable — rejoin only within this page load */ }
  updateContinueUI();
}

function updateContinueUI() {
  const exists = Boolean(gameId || savedGame()?.game_id);
  $("#continueGame").disabled = !exists;
  $("#continueHint").textContent = tr(exists ? "继续本机保存的对局，不重新发牌。" : "本机暂无可继续的对局。");
}

function savedGame() {
  try {
    const raw = localStorage.getItem(SAVE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}

function dispatch(d) {
  const no = d.event_no || 0;
  if (no && no <= lastEventNo) return;   // 已处理过：不重复渲染
  if (no) lastEventNo = no;
  handleEvent(d);
  persistState();
}

function openStream(after) {
  if (es) es.close();
  es = new EventSource(`/api/stream?game_id=${encodeURIComponent(gameId)}&after=${Math.max(0, after || 0)}`);
  es.onmessage = (ev) => {
    try { dispatch(JSON.parse(ev.data)); } catch (e) { console.error(e); }
  };
  es.onerror = () => {
    es.close();
    if (!gameId || faulted) return;   // 故障已暂停：不自动重连，等玩家手动续玩
    // 服务端可能尚未清掉旧流的 active 标记；用退避重试，绝不因瞬时断线结束对局。
    rejoinAttempts += 1;
    if (rejoinAttempts > 12) { finishStream(tr("连接断开")); return; }
    setTimeout(rejoin, Math.min(3000, 400 * rejoinAttempts));
  };
}

async function rejoin() {
  if (!gameId) return;
  try {
    const response = await fetch(`/api/rejoin?game_id=${encodeURIComponent(gameId)}&last_event_no=${lastEventNo}`);
    if (response.status === 404) { finishStream(tr("对局已结束")); return; }
    if (!response.ok) throw new Error("rejoin failed");
    const data = await response.json();
    if (!data.ok) throw new Error("rejoin failed");
    rejoinAttempts = 0;
    applyRecoveryView(data.view);
  } catch (_) {
    rejoinAttempts += 1;
    if (rejoinAttempts > 12) { finishStream(tr("连接断开")); return; }
    setTimeout(rejoin, Math.min(3000, 400 * rejoinAttempts));
  }
}

function applyRecoveryView(view) {
  document.body.classList.add("playing");
  $("#gameSetup").open = false;
  lockNames(true);

  if (lastEventNo === 0) {
    // 页面重新加载：从 init 完整重建牌桌与身份，再回放公开/私密事件。
    logEl.innerHTML = "";
    panelEl.style.display = "none";
    pendingReq = null;
    mySeat = null;
    if (view.init) {
      applyLocale(view.init.state.locale);
      $("#locale").disabled = true;
      renderSeats(view.init.state);
      showPlayer(view.init.player);
      showLlmStatus(view.init.llm_status);
      log(`🎙️ ${escapeHtml(view.init.host_intro)}`, "narr");
      lastEventNo = view.init.event_no || 0;
    }
  }

  if (view.private) showPlayer(view.private);

  for (const ev of view.public_events || []) dispatch(ev);
  for (const ev of view.private_events || []) dispatch(ev);

  if (view.pending) {
    showAction(view.pending);
  } else {
    pendingReq = null;
    panelEl.style.display = "none";
  }

  // 终局信号（gameover/review/error）最后回放，避免提前关流。
  for (const ev of view.terminal || []) dispatch(ev);

  // Restore the persistent "offline · not counted" label after a reconnect.
  setModeBadge(view.counted === false
    ? (uiLocale === "en" ? "Offline · not counted" : "离线模拟 · 不计闯关成绩") : null);

  if (view.finished) {
    // 区分「对局结束」与「复盘完成/不可用」：胜负已定但复盘尚未生成（崩溃在
    // 复盘前）时，展示待完成状态并保留续接信息，不能把 finished 当作全部接收完毕。
    if (view.review_status === "pending") {
      showReviewPending();
      return;
    }
    finishStream(tr("对局结束"));
    return;
  }

  lastEventNo = Math.max(lastEventNo, (view.next_event_no || 1) - 1);
  persistState();
  openStream(Math.max(0, lastEventNo));
}

function restoreSavedGame() {
  const saved = savedGame();
  if (!saved || !saved.game_id) return;
  gameId = saved.game_id;
  lastEventNo = 0;   // 完整重建（init + 事件回放）
  faulted = false;   // 明确恢复当前局：解除上一次故障暂停
  rejoin();
}

// ---------- 复盘弹窗 ----------
function showReview(text) {
  $("#reviewText").textContent = text;
  if ($("#reviewMask").style.display === "none") reviewFocus = document.activeElement;
  $("#reviewMask").style.display = "flex";
  $("#openReview").hidden = false;
  $("#closeReview").focus();
}
function closeReview() {
  $("#reviewMask").style.display = "none";
  const target = reviewFocus?.isConnected && !reviewFocus.disabled && reviewFocus.getClientRects().length
    ? reviewFocus : $("#openReview");
  target.focus();
}
$("#closeReview").onclick = closeReview;
$("#openReview").onclick = () => showReview($("#reviewText").textContent);
$("#reviewMask").addEventListener("keydown", event => {
  if (event.key === "Escape") { event.preventDefault(); closeReview(); }
  if (event.key === "Tab") { event.preventDefault(); $("#closeReview").focus(); }
});
$("#latestSpeech").onclick = () => { logEl.scrollTop = logEl.scrollHeight; $("#latestSpeech").hidden = true; };
logEl.addEventListener("scroll", () => {
  if (logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 60) $("#latestSpeech").hidden = true;
});

// ---------- 闯关短复盘重试 ----------
function showCampaignReviewRetry() {
  const btn = $("#retryCampaignReview");
  if (btn) btn.hidden = false;
}
function hideCampaignReviewRetry() {
  const btn = $("#retryCampaignReview");
  if (btn) btn.hidden = true;
}
async function retryCampaignReview() {
  const id = campaignReviewGameId || gameId;
  if (!id) return;
  const btn = $("#retryCampaignReview");
  if (btn) btn.disabled = true;
  try {
    const response = await fetch("/api/campaign/review", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ game_id: id })
    });
    const data = await response.json();
    if (!response.ok) throw new Error("review failed");
    if (data.unavailable) {
      // Failed again: keep the retry control visible and show the fallback note.
      log(`⚠️ ${escapeHtml(data.text)}`, "narr");
    } else if (data.text) {
      log(`📋 ${escapeHtml(data.text).replace(/\n/g, "<br>")}`, "narr");
      hideCampaignReviewRetry();   // success only hides the retry
    } else if (data.review === null) {
      hideCampaignReviewRetry();   // not a loss — nothing to review
    }
  } catch (_) {
    // keep the retry control visible so the player can try again
  } finally {
    if (btn) btn.disabled = false;
  }
}
$("#retryCampaignReview").onclick = retryCampaignReview;

// ---------- 闯关角色教学重试 ----------
function showCampaignTeachingRetry() {
  const btn = $("#retryCampaignTeaching");
  if (btn) btn.hidden = false;
}
function hideCampaignTeachingRetry() {
  const btn = $("#retryCampaignTeaching");
  if (btn) btn.hidden = true;
}
async function retryCampaignTeaching() {
  const id = campaignTeachingGameId || gameId;
  if (!id) return;
  const btn = $("#retryCampaignTeaching");
  if (btn) btn.disabled = true;
  try {
    const response = await fetch(`/api/campaign/teaching?game_id=${encodeURIComponent(id)}`);
    const data = await response.json();
    if (!response.ok) throw new Error("teaching failed");
    if (data.unavailable) {
      // Failed again: keep the retry control visible and show the fallback note.
      log(`⚠️ ${escapeHtml(data.text)}`, "narr");
    } else if (data.text) {
      log(`📖 ${escapeHtml(data.text)}`, "narr");
      hideCampaignTeachingRetry();   // success only hides the retry
    }
  } catch (_) {
    // keep the retry control visible so the player can try again
  } finally {
    if (btn) btn.disabled = false;
  }
}
$("#retryCampaignTeaching").onclick = retryCampaignTeaching;

// ---------- 新游戏 ----------
async function newGame() {
  if (gameId && !window.confirm(uiLocale === "en" ? "End this game and start a new one?" : "结束当前对局并重新开局？")) return;
  const names = Object.fromEntries([...document.querySelectorAll("#castNames input")]
    .map(input => [input.dataset.playerId, input.value.trim()]));
  const values = Object.values(names);
  if ($("#characterChoice").value === "custom" && (values.some(name => !name || [...name].length > 24) ||
      new Set(values.map(name => name.normalize("NFKC").toLocaleLowerCase())).size !== values.length)) {
    $("#castError").textContent = tr("名字必须不同，且为1至24字的文字、数字、空格或连字符。");
    return;
  }
  if (!(await endCurrentGame())) {
    $("#status").textContent = uiLocale === "en" ? "Could not end the current game; please retry." : "未能结束当前对局，请重试。";
    return;   // keep the old game + its resume record
  }
  const board = $("#board").value;
  const locale = $("#locale").value;
  applyLocale(locale);
  hideSetupGuidance();
  const llm = configuredLlmOptions();
  const driver = driverSelection();
  const personalities = Object.fromEntries([...document.querySelectorAll("#castNames select")]
    .map(input => [input.dataset.playerId, input.value]));
  const conjecture = $("#conjectureMode").checked;
  const player_role = $("#playerRole").value;
  $("#status").textContent = UI[uiLocale].starting;
  panelEl.style.display = "none";
  logEl.innerHTML = "";
  hideCampaignReviewRetry();
  campaignReviewGameId = null;
  hideCampaignTeachingRetry();
  campaignTeachingGameId = null;
  if (es) es.close();
  $("#locale").disabled = true;
  $("#newGame").disabled = true;
  lockNames(true);
  $("#reviewMask").style.display = "none";
  $("#openReview").hidden = true;
  try {
  const start = await fetch("/api/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ board_id: board, locale, llm, driver: driver.driver, connection: driver.connection, names, personalities, conjecture, player_role,
      character: $("#characterChoice").value === "custom" ? undefined : $("#characterChoice").value })
  });
  // Credentials are scoped to the request/game runner, never retained by UI.
  $("#llmApiKey").value = "";
  const started = await start.json();
  gameId = started.game_id || null;
  if (!gameId) {
    showSetupGuidance(started.detail || tr("开局设置无效，请检查后重试。"));
    finishStream(UI[uiLocale].failed);
    return;
  }
  document.body.classList.add("playing");
  $("#gameSetup").open = false;
  $("#textGuide").open = false;
  lastEventNo = 0;
  rejoinAttempts = 0;
  faulted = false;   // 新局重置故障暂停，前一局的故障不得影响后续对局
  persistState();
  openStream(0);
  // The init event replaces this with a safe model/local-runtime status.
  } catch (_) {
    finishStream(UI[uiLocale].failed);
  } finally {
    $("#llmApiKey").value = "";
    $("#newGame").disabled = false;
  }
}

$("#newGame").onclick = newGame;
$("#continueGame").onclick = () => restoreSavedGame();

async function loadOfflineCast() {
  try {
    const response = await fetch(`/api/offline/cast?locale=${encodeURIComponent(uiLocale)}`);
    if (!response.ok) return;
    const data = await response.json();
    const select = $("#offlineCharacter");
    const previous = select.value || "random";
    select.innerHTML = "";
    select.add(new Option(tr("随机人物（名字、头像、人格绑定）"), "random"));
    for (const c of data.characters) select.add(new Option(c.name, c.id));
    if (previous === "random" || data.characters.some(c => c.id === previous)) select.value = previous;
    select.onchange = () => {
      $("#offlineDescription").textContent = data.characters.find(c => c.id === select.value)?.description || "";
    };
    select.onchange();
  } catch (_) { /* The explicit launch reports connection errors. */ }
}

async function offlineGame() {
  if (!window.confirm(uiLocale === "en" ? "Start rule-based offline play? No campaign score. The current game, if any, will be abandoned."
    : "开始程序策略离线对局？不计闯关成绩；如有当前对局，将先放弃。")) return;
  const button = $("#offlineGame");
  button.disabled = true;
  try {
    if (!(await endCurrentGame())) throw new Error(uiLocale === "en" ? "Could not end current game" : "未能结束当前对局");
    const spectator = $("#offlineSpectator").checked;
    const response = await fetch("/api/offline/start", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({offline_confirmed: true, board_id: $("#board").value,
        locale: uiLocale, character: $("#offlineCharacter").value || "acheng", spectator,
        player_role: spectator ? "random" : $("#playerRole").value})
    });
    const data = await response.json();
    if (!response.ok || !data.game_id) throw new Error(data.detail || "Could not start game");
    gameId = data.game_id;
    lastEventNo = 0; rejoinAttempts = 0; faulted = false;
    logEl.innerHTML = ""; pendingReq = null; panelEl.style.display = "none";
    hideCampaignReviewRetry(); hideCampaignTeachingRetry();
    campaignReviewGameId = null; campaignTeachingGameId = null;
    $("#reviewMask").style.display = "none";
    $("#openReview").hidden = true;
    $("#offlineError").textContent = "";
    $("#gameSetup").open = false;
    document.body.classList.add("playing"); lockNames(true);
    setModeBadge(uiLocale === "en" ? "Offline choices · not counted" : "离线选项 · 不计闯关成绩");
    persistState(); openStream(0);
  } catch (error) {
    $("#offlineError").textContent = error.message;
  } finally { button.disabled = false; }
}
$("#offlineGame").onclick = offlineGame;
loadOfflineCast();

async function campaignGame() {
  if (gameId && !window.confirm(uiLocale === "en" ? "End this game and start a new one?" : "结束当前对局并重新开局？")) return;
  const llm = configuredLlmOptions();
  const driver = driverSelection();
  const offline = driver.driver === "offline" || (llm && llm.enabled === false);
  // Every confirmation runs BEFORE the abandon request, so a cancel never ends
  // the old game.
  if (offline && !window.confirm(uiLocale === "en"
      ? "Offline simulation does not count toward campaign progress (no unlock, no score). Continue?"
      : "离线模拟不计闯关成绩（不解锁、不计分）。确定继续？")) return;
  if (!(await endCurrentGame())) {
    $("#status").textContent = uiLocale === "en" ? "Could not end the current game; please retry." : "未能结束当前对局，请重试。";
    return;   // keep the old game + its resume record
  }
  try {
    const status = await (await fetch("/api/campaign/status")).json();
    const locale = $("#locale").value;
    applyLocale(locale);
    hideSetupGuidance();
    $("#status").textContent = UI[uiLocale].starting;
    panelEl.style.display = "none";
    logEl.innerHTML = "";
    hideCampaignReviewRetry();
    campaignReviewGameId = null;
    hideCampaignTeachingRetry();
    campaignTeachingGameId = null;
    if (es) es.close();
    $("#locale").disabled = true;
    lockNames(true);
    $("#reviewMask").style.display = "none";
    $("#openReview").hidden = true;
    const start = await fetch("/api/campaign/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: "default", role: status.role, locale, llm, driver: driver.driver, connection: driver.connection,
        character: $("#characterChoice").value === "custom" ? undefined : $("#characterChoice").value })
    });
    $("#llmApiKey").value = "";
    const started = await start.json();
    gameId = started.game_id || null;
    if (!gameId) {
      showSetupGuidance(started.detail || tr("开局设置无效，请检查后重试。"));
      finishStream(UI[uiLocale].failed);
      return;
    }
    document.body.classList.add("playing");
    $("#gameSetup").open = false;
    lastEventNo = 0; rejoinAttempts = 0; faulted = false;
    persistState();
    await loadCampaignTeaching(gameId);   // generate + emit the first-entry teaching before the stream
    openStream(0);
    setModeBadge(started.counted === false
      ? (uiLocale === "en" ? "Offline · not counted" : "离线模拟 · 不计闯关成绩") : null);
  } catch (_) { finishStream(UI[uiLocale].failed); }
}
async function loadCampaignTeaching(id) {
  // Best-effort: the teaching event arrives via the stream; this request only
  // triggers generation (and its "unavailable" marker on model failure).
  try {
    await fetch(`/api/campaign/teaching?game_id=${encodeURIComponent(id)}`);
  } catch (_) { /* the game proceeds regardless */ }
}
$("#campaignGame").onclick = campaignGame;
$("#copyTextCommand").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("#textCommand").textContent);
    $("#copyStatus").textContent = tr("已复制");
  } catch (_) {
    $("#copyStatus").textContent = tr("请选中上方命令手动复制。");
  }
};
$("#board").onchange = loadRoleChoices;
$("#locale").onchange = () => { applyLocale($("#locale").value); loadBoards(); loadCast(); loadOfflineCast(); };
$("#randomNames").onclick = loadCast;
$("#askHost").onclick = askHostRule;
$("#driverMode").onchange = syncDriverUI;
$("#hostQuestion").addEventListener("keydown", (event) => {
  if (event.key === "Enter") askHostRule();
});
loadBoards();
applyLocale($("#locale").value);
loadCast();
loadAgentConnections();
syncDriverUI();
restoreSavedGame();
