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
const SAVE_KEY = "werewolf.game";
let seats = {};        // pos -> seat DOM
let mySeat = null;
let pendingReq = null;
let uiLocale = "zh-CN";
let castRequest = 0;
let boardData = {boards: [], roles: {}};
const UI = {"zh-CN": {brand:"🐺 暗夜茶馆 · 狼人杀", start:"开始新游戏", identity:"你的身份", host:"🎙️ 问主持人（规则单聊）", hint:"我只解释规则和公开流程，不会泄露身份或替你决策。", starting:"开局中...", failed:"开局失败"}, en: {brand:"🐺 Night Table · Werewolf", start:"Start game", identity:"Your role", host:"🎙️ Ask the Host (rules)", hint:"I explain rules and public flow only. I never reveal identities or choose for you.", starting:"Starting...", failed:"Could not start game"}};

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
  const command = `python -u -m werewolf_web.chat_game --board classic --lang ${uiLocale} --offline`;
  $("#textCommand").textContent = uiLocale === "en"
    ? `Help me play Werewolf here in our conversation. Repository: https://github.com/shenliucn-prog/werewolf-ai-public\nRead README.md and docs/AGENT_PLAY.md, prepare the local environment, then keep this interactive process alive:\n${command}\nRelay the game's statements and my private prompts. Wait for my decisions; do not autoplay, invent game events or inspect hidden roles. If you cannot maintain an interactive process, tell me rather than simulating a game.`
    : `请让我在当前 Agent 对话里玩狼人杀。仓库：https://github.com/shenliucn-prog/werewolf-ai-public\n阅读 README.md 和 docs/AGENT_PLAY.md，准备本地环境，并持续保留以下交互进程：\n${command}\n转述游戏发言和属于我的私密提示，等待我的决定，不代打、不编造事件、不读取其他人的隐藏身份。如果无法保持交互进程，请说明限制，不要模拟一局冒充真实游戏。`;
  $("#copyStatus").textContent = "";
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
  // 清掉旧座位（保留 moon/center）
  Object.values(seats).forEach((s) => s.el.remove());
  seats = {};
  const list = state.seats;
  list.forEach((s) => {
    const el = document.createElement("div");
    el.className = "seat";
    const file = PORTRAITS[s.player_id] || PORTRAITS[s.name] || "";
    const initial = s.name.slice(0, 1);
    el.innerHTML = `
      <div class="avatar">${escapeHtml(initial)}
        ${file ? `<img src="/img/portraits/${file}.png" alt="" onerror="this.remove()">` : ""}
      </div>
      <div class="name">${seatText(s.pos)} ${escapeHtml(s.name)}</div>
      <div class="role-badge"></div>`;
    tableEl.appendChild(el);
    seats[s.pos] = { el, data: s };
    if (s.is_player) mySeat = s.pos;
  });
  if (state.sheriff) markSheriff(state.sheriff);
}

function markSheriff(pos) {
  Object.values(seats).forEach((s) => s.el.classList.remove("sheriff"));
  if (seats[pos]) seats[pos].el.classList.add("sheriff");
}
function markDead(pos) {
  if (seats[pos]) seats[pos].el.classList.add("dead");
}
function revealRole(pos, roleCn) {
  const s = seats[pos];
  if (!s) return;
  s.el.classList.add("dead");
  const badge = s.el.querySelector(".role-badge");
  badge.style.display = "inline-block";
  badge.textContent = roleCn;
}
function highlightSpeaker(pos) {
  Object.values(seats).forEach((s) => s.el.classList.remove("speaking"));
  if (seats[pos]) seats[pos].el.classList.add("speaking");
  setTimeout(() => { if (seats[pos]) seats[pos].el.classList.remove("speaking"); }, 2500);
}

// ---------- 日志 ----------
function log(text, cls = "") {
  const row = document.createElement("div");
  row.className = "row " + cls;
  row.innerHTML = text;
  logEl.appendChild(row);
  logEl.scrollTop = logEl.scrollHeight;
}
function narr(text) { log(escapeHtml(text), "narr"); }

function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

// ---------- 玩家身份 ----------
function showPlayer(pv) {
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
  switch (d.type) {
    case "init":
      applyLocale(d.state.locale);
      $("#locale").disabled = true;
      renderSeats(d.state); showPlayer(d.player);
      showLlmStatus(d.llm_status);
      log(`🎙️ ${escapeHtml(d.host_intro)}`, "narr"); break;
    case "llm_status": showLlmStatus(d.llm_status); break;
    case "narration": narr(d.text); setPhase(d.phase); if (d.sheriff) markSheriff(d.sheriff); break;
    case "private": log(`🔒 ${escapeHtml(d.text)}`, "private"); break;
    case "speech":
      highlightSpeaker(d.seat);
      log(`<b>${escapeHtml(d.name)}</b>：${escapeHtml(d.text)}`, "speech"); break;
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
    case "review": showReview(d.text); break;
    case "gameover":
      log(`🏆 ${escapeHtml(d.reason)}`, "win"); panelEl.style.display = "none";
      finishStream(tr("对局结束")); break;
    case "error": log(escapeHtml(d.text), "err"); finishStream(d.text); break;
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
  const kind = d.kind, data = d.data || {};
  panelEl.style.display = "block";
  panelEl.innerHTML = "";
  if (kind === "model_retry") {
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
      b.textContent = c.pos === 0 ? tr("平安日") : `${seatText(c.pos)} ${c.name}${c.note ? " (" + c.note + ")" : ""}`;
      b.onclick = () => {
        sel = c.pos;
        [...btns.children].forEach((x) => x.classList.remove("sel"));
        b.classList.add("sel");
        $("#sendVote").disabled = false;
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
    html += `<button class="send-btn" id="sendNight">${tr("确认")}</button>`;
    panelEl.innerHTML = html;
    if (!isWitch) {
      const btns = $("#nightBtns"); let sel = null;
      cands.forEach((c) => {
        const b = document.createElement("button");
        b.className = "cand-btn";
        b.textContent = `${seatText(c.pos)} ${c.name}${c.note || ""}`;
        if (c.note) b.classList.add("self-knife");
        b.onclick = () => {
          sel = c.pos;
          [...btns.children].forEach((x) => x.classList.remove("sel"));
          b.classList.add("sel");
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
  if (!payload) return;
  panelEl.style.display = "none";
  const submitted = pendingReq;
  try {
  const response = await fetch("/api/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, game_id: gameId })
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
  persistState();
}

// ---------- 断线重连 / 恢复（§6）----------
function persistState() {
  try {
    if (gameId) localStorage.setItem(SAVE_KEY, JSON.stringify({ game_id: gameId, last_event_no: lastEventNo }));
    else localStorage.removeItem(SAVE_KEY);
  } catch (_) { /* storage unavailable — rejoin only within this page load */ }
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
    if (!gameId) return;
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

  if (view.finished) {
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
  rejoin();
}

// ---------- 复盘弹窗 ----------
function showReview(text) {
  $("#reviewText").textContent = text;
  $("#reviewMask").style.display = "flex";
}
$("#closeReview").onclick = () => { $("#reviewMask").style.display = "none"; };

// ---------- 新游戏 ----------
async function newGame() {
  if (gameId && !window.confirm(uiLocale === "en" ? "End this game and start a new one?" : "结束当前对局并重新开局？")) return;
  const names = Object.fromEntries([...document.querySelectorAll("#castNames input")]
    .map(input => [input.dataset.playerId, input.value.trim()]));
  const values = Object.values(names);
  if (values.some(name => !name || [...name].length > 24) ||
      new Set(values.map(name => name.normalize("NFKC").toLocaleLowerCase())).size !== values.length) {
    $("#castError").textContent = tr("名字必须不同，且为1至24字的文字、数字、空格或连字符。");
    return;
  }
  const board = $("#board").value;
  const locale = $("#locale").value;
  applyLocale(locale);
  const llm = configuredLlmOptions();
  const personalities = Object.fromEntries([...document.querySelectorAll("#castNames select")]
    .map(input => [input.dataset.playerId, input.value]));
  const conjecture = $("#conjectureMode").checked;
  const player_role = $("#playerRole").value;
  $("#status").textContent = UI[uiLocale].starting;
  panelEl.style.display = "none";
  logEl.innerHTML = "";
  if (es) es.close();
  $("#locale").disabled = true;
  $("#newGame").disabled = true;
  lockNames(true);
  $("#reviewMask").style.display = "none";
  try {
  const start = await fetch("/api/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ board_id: board, locale, llm, names, personalities, conjecture, player_role })
  });
  // Credentials are scoped to the request/game runner, never retained by UI.
  $("#llmApiKey").value = "";
  const started = await start.json();
  gameId = started.game_id || null;
  if (!gameId) {
    $("#castError").textContent = tr("开局设置无效，请检查后重试。");
    finishStream(UI[uiLocale].failed);
    return;
  }
  document.body.classList.add("playing");
  $("#gameSetup").open = false;
  $("#textGuide").open = false;
  lastEventNo = 0;
  rejoinAttempts = 0;
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
$("#copyTextCommand").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("#textCommand").textContent);
    $("#copyStatus").textContent = tr("已复制");
  } catch (_) {
    $("#copyStatus").textContent = tr("请选中上方命令手动复制。");
  }
};
$("#board").onchange = loadRoleChoices;
$("#locale").onchange = () => { applyLocale($("#locale").value); loadBoards(); loadCast(); };
$("#randomNames").onclick = loadCast;
$("#askHost").onclick = askHostRule;
$("#hostQuestion").addEventListener("keydown", (event) => {
  if (event.key === "Enter") askHostRule();
});
loadBoards();
applyLocale($("#locale").value);
loadCast();
restoreSavedGame();
