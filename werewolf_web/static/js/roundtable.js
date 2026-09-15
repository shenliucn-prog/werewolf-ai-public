// Progressive setup and public table presence. Never reads hidden role data.
const entryInterface = $("#entryInterface");
const entryMode = $("#entryMode");
const setupSections = [...document.querySelectorAll(".setup-grid > section")];
let tableDay = 0, tableNight = 0;

function updateRoundtable(event) {
  const state = event.state || event;
  tableDay = state.day ?? state.day_count ?? tableDay;
  tableNight = state.night ?? state.night_count ?? tableNight;
  const phase = state.phase;
  const labels = {night:["夜晚","Night"], dawn:["天亮","Dawn"], day:["白天","Day"], election:["警长竞选","Election"], vote:["放逐投票","Exile ballot"], onboarding:["认识本局","Meet the table"], table_talk:["公开讨论","Discussion"]};
  if (labels[phase]) $("#tablePhase").textContent = labels[phase][uiLocale === "en" ? 1 : 0] + (phase === "onboarding" ? "" : ` · ${phase === "night" ? tableNight : tableDay}`);
  if (event.type === "speech") {
    const who = seats[event.seat]?.data;
    $("#speakerName").textContent = `${seatText(event.seat)} · ${event.name}`;
    const id = who?.character_id || PORTRAITS[who?.player_id];
    const portrait = $("#speakerPortrait");
    portrait.hidden = !id;
    if (id && /^[a-z][a-z0-9_]{0,31}$/.test(id)) {
      portrait.src = `/img/portraits/${id}.png`;
      portrait.alt = event.name;
    }
    $("#tableTurn").textContent = setupText("正在发言", "Speaking");
    if (event.turn) $("#tableTurn").textContent += ` · ${event.turn}/${event.turn_total}`;
    if (Number.isInteger(event.remaining_before_you)) $("#tableTurn").textContent += setupText(` · 你前面还有 ${event.remaining_before_you} 位（可能插话）`, ` · ${event.remaining_before_you} before you (interruptions possible)`);
  } else if (event.type === "request") {
    $("#tableTurn").textContent = event.data?.last_words ? setupText("轮到你的遗言", "Your last words") : event.kind === "ready" ? setupText("准备好，再开始第一夜", "Ready when you are") : setupText("轮到你了 · 下方回应", "Your turn · respond below");
    highlightSpeaker(["speech", "table_reply", "table_answer"].includes(event.kind) ? mySeat : null);
  } else if (event.type === "discussion_closed") {
    $("#tableTurn").textContent = setupText("主持人收口 · 即将投票", "Host closes discussion · ballot next");
  } else if (event.type === "gameover") {
    $("#tableTurn").textContent = setupText("本局结束", "Game ended");
  }
}

function updateEntryFlow() {
  const selected = Boolean(entryInterface.value);
  const driver = $("#driverMode").value;
  const offline = driver === "offline";
  setupSections[0].hidden = !selected;
  setupSections[1].hidden = !selected;
  setupSections[2].hidden = !selected;
  // Connection stays before mode and cast. Server-default is a valid explicit
  // option: the backend decides whether it is actually configured.
  $("#textGuide").open = entryInterface.value === "agent";
  $("#offlineSetup").hidden = !selected || !offline || entryInterface.value !== "web";
  $("#offlineSetup").open = offline;
  $("#connectionTools").hidden = offline;
  const mode = entryMode.value;
  $("#newGame").hidden = mode !== "free" || (offline && entryInterface.value === "web");
  $("#campaignGame").hidden = mode !== "campaign" || offline;
  $("#continueGame").hidden = mode !== "continue";
  for (const id of ["newGame", "campaignGame", "continueGame"]) {
    const b = $("#" + id);
    if (b.nextElementSibling?.classList.contains("field-help")) b.nextElementSibling.hidden = b.hidden;
  }
  $("#tableSettingsTitle").parentElement.querySelector(".controls").hidden = mode === "continue";
  $("#board").closest("label").hidden = mode === "campaign";
  $("#playerRole").closest("label").hidden = mode === "campaign";
  $("#boardDescription").hidden = mode === "campaign";
  $("#entryExplanation").textContent = offline && mode === "campaign"
    ? setupText("离线仅模拟，不计闯关成绩。请选择自由对局。", "Offline simulation has no campaign score. Choose free play.")
    : setupText("先选界面，再选驱动，然后决定玩法和人物。人物不是狼人杀身份。", "Interface first, then driver, mode and character. A character is not a secret role.");
  updateAgentBrief();
}

function updateAgentBrief() {
  if (entryInterface.value !== "agent") return;
  const driver = $("#driverMode").value;
  const mode = entryMode.value;
  const board = $("#board").value || "classic";
  const role = $("#playerRole").value || "random";
  const character = $("#characterChoice").value || "random";
  const connection = $("#agentConnection").value;
  // No keys, argv or endpoint strings in the clipboard. The receiving Agent
  // reads its own trusted local configuration and validates the connection.
  const choices = `interface=Agent conversation; driver=${driver || "saved configuration (not offline)"}; mode=${mode}; board=${board}; role=${role}; character=${character}; locale=${uiLocale}`;
  $("#textCommand").textContent = setupText(
    `在本机项目里读取 docs/AGENT_PLAY.md，按下面选择开局：\n${choices}\n${connection ? "我选择已登记连接：" + connection + "。\n" : ""}请使用项目提供的入口，持续保留交互进程；不重新替我选择，不代打，不读取其他座位的私密信息。模型接入未配置时先协助配置，不自动转离线。离线选择使用 offline_game 选项入口。继续游戏不得重新发牌。`,
    `Read docs/AGENT_PLAY.md in my local project and start with these choices:\n${choices}\n${connection ? "Selected registered connection: " + connection + ".\n" : ""}Use the project's entry point and keep its interactive process alive. Do not choose again for me, autoplay or inspect other seats' secrets. Help configure a missing model connection; never silently switch offline. Explicit offline uses the offline_game choice entry. Continuing must not redeal.`);
}

// The existing buttons retain their backend actions in Web mode. In Agent
// mode they prepare an instruction, not an accidental second browser game.
for (const id of ["newGame", "campaignGame", "continueGame"]) {
  const button = $("#" + id), launch = button.onclick;
  button.onclick = event => {
    if (entryInterface.value === "agent") {
      updateAgentBrief(); $("#textGuide").open = true;
      $("#copyTextCommand").focus();
      $("#copyStatus").textContent = setupText("复制这段说明到自己的 Agent；尚未开局。", "Copy this brief to your Agent; no game has started.");
      return;
    }
    return launch(event);
  };
}
entryInterface.onchange = updateEntryFlow;
entryMode.onchange = updateEntryFlow;
for (const id of ["driverMode", "agentConnection", "board", "playerRole", "characterChoice", "locale"]) {
  $("#" + id).addEventListener("change", updateEntryFlow);
}
updateEntryFlow();
// Keep the action shortcut in the header's own space, never floating over a
// question, portrait or transcript. Mobile can reach it without losing text.
document.querySelector(".topbar").append($("#actionJump"));
const choiceControls = $("#board").closest(".controls");
choiceControls.prepend($("#board").closest("label"), $("#boardDescription"), $("#playerRole").closest("label"));

function syncTableActions() {
  for (const [pos, seat] of Object.entries(seats)) {
    const target = panelEl.querySelector(`button[data-target="${pos}"]`);
    seat.el.classList.toggle("eligible", Boolean(target) && panelEl.style.display !== "none");
    seat.el.classList.toggle("targeted", Boolean(target?.classList.contains("sel")) && panelEl.style.display !== "none");
    seat.el.setAttribute("aria-label", `${seatText(pos)} ${seat.data.name} · ${seat.el.querySelector('.seat-status').textContent}`);
  }
}
new MutationObserver(syncTableActions).observe(panelEl, {childList:true, subtree:true, attributes:true});
