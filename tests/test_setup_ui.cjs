// DOM integration test (not a real-browser visual test).
// From the repository root: npm ci && npm test (development only).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {JSDOM, VirtualConsole} = require('jsdom');
const root = path.join(__dirname, '..', 'werewolf_web', 'static');
const errors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', error => errors.push(error));
const dom = new JSDOM(fs.readFileSync(path.join(root, 'index.html'), 'utf8'), {
  url: 'http://localhost/', runScripts: 'outside-only', virtualConsole
});
const w = dom.window;
const players = ['acheng','dashan','amo','alan','xiaoman','yexiao','xiaolu','aman','tiandou','xicao','laomai','aji']
  .map((id, i) => ({id, name: `Player ${i}`, is_player: i === 0}));
const requests = [];
let rejoinView = {ok:true, view:{finished:false, review_status:null, counted:null, public_events:[], private_events:[], terminal:[], next_event_no:1}};
let teachingResponse = {ok:true, game_id:'ui-campaign', role:'civilian', text:'教学文本'};
w.fetch = async (url, options = {}) => {
  const body = options.body ? JSON.parse(options.body) : null;
  requests.push({url, body});
  const response = url.startsWith('/api/campaign/start') ? {ok:true, game_id:'ui-campaign', role:'civilian', board_id:'classic', counted:false} :
    url.startsWith('/api/campaign/status') ? {ok:true, role:'civilian', board_id:'classic', goal_cn:'判断身份', goal_en:'Read', unlocked:0} :
    url.startsWith('/api/campaign/review') ? {ok:true, game_id: body && body.game_id, text:'重试复盘'} :
    url.startsWith('/api/campaign/teaching') ? teachingResponse :
    url.startsWith('/api/leave') ? {ok:true} :
    url.startsWith('/api/rejoin') ? rejoinView :
    url.startsWith('/api/boards') ? {boards: [
    {id:'classic',name:'Classic',difficulty:'Intro',roles:['seer','werewolf','werewolf','villager']},
    {id:'other',name:'Other',difficulty:'Intro',roles:['guard','werewolf','villager']},
    {id:'divine_witch_dual',name:'Divine Witch',difficulty:'Experimental',roles:['witch','werewolf','villager'],role_labels:{witch:'Divine Witch'}}],
    roles:{seer:{cn:'Seer'},werewolf:{cn:'Werewolf'},villager:{cn:'Villager'},guard:{cn:'Guard'}}} :
    url.startsWith('/api/cast') ? {players, personalities: [{id:'aman',label:'Analytical'}, {id:'dashan',label:'Bold'}]} :
    url === '/api/start' ? {ok:true,game_id:'ui-test'} : {ok:true};
  return {ok:true,json:async()=>response};
};
let lastEs = null;
w.EventSource = class { close(){} constructor(){ lastEs = this; } };
w.confirm = () => true;
vm.runInContext(fs.readFileSync(path.join(root, 'js', 'i18n.js'), 'utf8'), dom.getInternalVMContext());
vm.runInContext(fs.readFileSync(path.join(root, 'js', 'app.js'), 'utf8'), dom.getInternalVMContext());
const flush = () => new Promise(resolve => setTimeout(resolve, 10));
(async () => {
  await flush();
  assert.equal(w.document.querySelectorAll('#castNames input').length,12);
  assert.equal(w.document.querySelectorAll('#castNames select').length,11);
  assert.equal(w.document.querySelector('#conjectureMode').checked,false);
  assert.match(w.document.querySelector('#playTitle').textContent,/推荐/);
  assert.match(w.document.querySelector('#playTitle').textContent,/Agent/);
  assert.match(w.document.querySelector('#textGuide').textContent,/尚无通用 Agent 插件或 MCP/);
  assert.match(w.document.querySelector('#textCommand').textContent,/不代打、不编造事件/);
  assert.match(w.document.querySelector('#textCommand').textContent,/chat_game .*--lang zh-CN/);
  assert.ok(!w.document.querySelector('#textCommand').textContent.includes('--offline'));
  assert.equal(w.document.querySelector('#log').closest('.conversation'),w.document.querySelector('.conversation'));
  assert.equal(w.document.querySelector('#actionPanel').closest('.conversation'),w.document.querySelector('.conversation'));
  assert.ok(w.document.querySelector('#playerCard').closest('.game-context'));
  assert.equal(w.document.querySelector('.host-chat').tagName,'DETAILS');
  assert.equal(w.document.querySelector('.host-chat').open,false);
  const role = w.document.querySelector('#playerRole');
  assert.equal(role.value,'random');
  assert.equal(role.options.length,4);
  role.value='seer';
  const board = w.document.querySelector('#board');
  board.value='other'; board.dispatchEvent(new w.Event('change'));
  assert.equal(role.value,'random');
  assert.ok(![...role.options].some(o=>o.value==='seer'));
  board.value='classic'; board.dispatchEvent(new w.Event('change'));
  role.value='seer';
  const select = w.document.querySelector('#castNames select'); select.value='aman';
  w.document.querySelector('#locale').value='en';
  w.document.querySelector('#locale').dispatchEvent(new w.Event('change'));
  await flush();
  assert.equal(w.document.querySelector('#castNames select').value,'aman');
  assert.equal(role.value,'seer');
  assert.equal(role.getAttribute('aria-label'),'Your role');
  assert.match(w.document.querySelector('#playTitle').textContent,/Recommended/);
  assert.match(w.document.querySelector('#playTitle').textContent,/your own Agent/);
  assert.match(w.document.querySelector('#textGuide').textContent,/No universal Agent plugin or MCP/);
  assert.match(w.document.querySelector('#textCommand').textContent,/do not autoplay/);
  assert.match(w.document.querySelector('#textCommand').textContent,/--lang en/);
  assert.ok(!w.document.querySelector('#textCommand').textContent.includes('--offline'));
  let copied='';
  Object.defineProperty(w.navigator,'clipboard',{configurable:true,value:{writeText:async text=>{copied=text;}}});
  w.document.querySelector('#copyTextCommand').click(); await flush();
  assert.equal(copied,w.document.querySelector('#textCommand').textContent);
  assert.equal(w.document.querySelector('#copyStatus').textContent,'Copied');
  w.navigator.clipboard.writeText=async()=>{throw new Error('denied');};
  w.document.querySelector('#copyTextCommand').click(); await flush();
  assert.match(w.document.querySelector('#copyStatus').textContent,/manually/);
  assert.match(w.document.querySelector('.quick-help').textContent,/Good wins when all wolves are out/);
  assert.equal(w.document.querySelector('#hostQuestion').getAttribute('aria-labelledby'),'hostChatTitle');
  assert.match(w.document.querySelector('.mode-note').textContent,/not designed or implemented/);
  w.document.querySelector('#conjectureMode').checked=true;
  w.document.querySelector('#newGame').click(); await flush();
  const started = requests.find(r=>r.url==='/api/start').body;
  assert.equal(w.document.querySelector('#gameSetup').open,false);
  assert.ok(w.document.body.classList.contains('playing'));
  assert.equal(started.conjecture,true);
  assert.equal(started.player_role,'seer');
  assert.equal(role.disabled,true);
  assert.equal(started.personalities.dashan,'aman');
  assert.equal(w.document.querySelector('#conjectureMode').disabled,true);
  const rows = players.map(p=>({player:p.name,judgment:'unknown',reason:''}));
  w.eval('showAction({kind:"ready", data:{}})');
  assert.match(w.document.querySelector('#actionPanel').textContent, /Night one waits/);
  w.document.querySelector('#readyGame').click(); await flush();
  const readiness = requests.filter(r=>r.url==='/api/action').pop();
  assert.equal(readiness.body.ready,true);
  w.eval('showAction({kind:"election_withdraw",data:{}})');
  w.document.querySelector('#withdrawYes').click(); await flush();
  assert.equal(requests.filter(r=>r.url==='/api/action').pop().body.withdraw,true);
  w.eval('showAction({kind:"vote",data:{candidates:[{pos:0,name:"Peaceful Day"},{pos:2,name:"Player"}]}})');
  assert.equal(w.document.querySelector('#voteBtns button').textContent,'Peaceful Day');
  w.document.querySelector('#voteBtns button').click();
  w.document.querySelector('#sendVote').click(); await flush();
  assert.equal(requests.filter(r=>r.url==='/api/action').pop().body.target,0);
  w.eval('handleEvent({type:"ballots",text:"#1 → Peaceful Day (1.5)\\n#2 → #3 (1)"})');
  assert.match(w.document.querySelector('#log').textContent, /Peaceful Day \(1.5\)/);
  const data = {players:players.map(p=>p.name),options:['unknown','wolf','good'],private:rows,public:rows,hint:'Dual tables'};
  w.eval(`showAction(${JSON.stringify({kind:'conjecture',data})})`);
  assert.equal(w.document.querySelectorAll('#actionPanel select').length,24);
  const inputs = w.document.querySelectorAll('#actionPanel input');
  inputs[0].value='PRIVATE_CANARY'; inputs[12].value='PUBLIC_REASON';
  w.document.querySelector('#actionPanel button').click(); await flush();
  const action=requests.filter(r=>r.url==='/api/action').pop().body;
  assert.equal(action.private[0].reason,'PRIVATE_CANARY');
  assert.equal(action.public[0].reason,'PUBLIC_REASON');
  assert.ok(!JSON.stringify(action.public).includes('PRIVATE_CANARY'));
  w.eval(`handleEvent(${JSON.stringify({type:'conjecture',tables:[{actor:'Player 0',version:1,rows:action.public}]})})`);
  assert.match(w.document.querySelector('#log').textContent,/PUBLIC_REASON/);
  assert.ok(!w.document.querySelector('#log').textContent.includes('PRIVATE_CANARY'));

  // ---- Endgame / rejoin / fault sequence (P1 regressions) ----
  // gameover marks the result but must NOT clear resume info (no finishStream);
  // the reveal (narration) and review still arrive; review is the close signal.
  w.eval('handleEvent({type:"gameover", reason:"狼人获胜", winner:"wolf"})');
  assert.ok(w.localStorage.getItem('werewolf.game'));                 // resume kept
  w.eval('handleEvent({type:"narration", text:"最终身份\\n#1 张三: 狼人"})');
  assert.match(w.document.querySelector('#log').textContent, /最终身份/);
  w.eval('handleEvent({type:"review", text:"复盘文本", winner:"wolf"})');
  assert.equal(w.document.querySelector('#reviewMask').style.display, 'flex');
  assert.equal(w.localStorage.getItem('werewolf.game'), null);        // review closed the stream
  w.document.querySelector('#closeReview').click();

  // Re-start, then exercise the actual rejoin path against a fresh resume record.
  w.document.querySelector('#newGame').click(); await flush();
  assert.ok(w.localStorage.getItem('werewolf.game'));

  // finished=true but review pending, through the real rejoin() path: show the
  // pending state, do NOT clear resume info.
  rejoinView = {ok:true, view:{finished:true, review_status:"pending", public_events:[], private_events:[], terminal:[], next_event_no:1}};
  w.eval('rejoin()'); await flush();
  assert.equal(w.document.querySelector('#reviewMask').style.display, 'flex');
  assert.match(w.document.querySelector('#reviewText').textContent, /unavailable/);
  assert.ok(w.localStorage.getItem('werewolf.game'));                 // resume preserved
  w.document.querySelector('#closeReview').click();

  // Recoverable error: pause the stream but keep the same game's resume info.
  w.eval('handleEvent({type:"error", text:"模型故障，已暂停"})');
  assert.match(w.document.querySelector('#status').textContent, /模型故障/);
  assert.ok(w.localStorage.getItem('werewolf.game'));                 // resume preserved

  // fault → new game → network disconnect: the fault flag must be reset on a new
  // game, so a later disconnect re-enters the rejoin flow (mocked-server frontend
  // integration test, not an end-to-end client/server test).
  rejoinView = {ok:true, view:{finished:false, review_status:null, public_events:[], private_events:[], terminal:[], next_event_no:1}};
  w.document.querySelector('#newGame').click(); await flush();
  const rejoinBefore = requests.filter(r => r.url.startsWith('/api/rejoin')).length;
  lastEs.onerror();                                                 // simulate a disconnect
  await new Promise(resolve => setTimeout(resolve, 500));           // let the backoff fire
  const rejoinAfter = requests.filter(r => r.url.startsWith('/api/rejoin')).length;
  assert.ok(rejoinAfter > rejoinBefore);                            // rejoin re-engaged

  w.eval('finishStream("done")');
  assert.ok(!w.document.body.classList.contains('playing'));
  assert.equal(w.document.querySelector('#conjectureMode').disabled,false);
  assert.equal(role.disabled,false);
  board.value='divine_witch_dual'; board.dispatchEvent(new w.Event('change'));
  assert.equal([...role.options].find(o=>o.value==='witch').textContent,'Divine Witch');
  for (const dual of [false,true]) {
    const night = {kind:'night',data:{role_key:'witch',role:'Divine Witch',antidote:true,poison:true,
      dual_potions:dual,save_candidates:[{pos:2,name:'Saved'}],candidates:[{pos:3,name:'Poisoned'}]}};
    w.eval(`showAction(${JSON.stringify(night)})`);
    const save=w.document.querySelector('#saveSel'); const poison=w.document.querySelector('#poisonSel');
    assert.equal(w.document.querySelector('label[for="saveSel"]').textContent,'Antidote');
    assert.equal(w.document.querySelector('label[for="poisonSel"]').textContent,'Poison');
    save.value='2'; save.dispatchEvent(new w.Event('change'));
    poison.value='3'; poison.dispatchEvent(new w.Event('change'));
    assert.equal(save.value,dual?'2':'');
    w.document.querySelector('#sendNight').click(); await flush();
    const sent=requests.filter(r=>r.url==='/api/action').at(-1).body;
    assert.equal(sent.save,dual?2:null); assert.equal(sent.poison,3);
  }
  for (const retryChoice of [true, false]) {
    w.eval('showAction({kind:"model_retry",data:{}})');
    const buttons = w.document.querySelectorAll('#actionPanel button');
    assert.equal(buttons[0].textContent, 'Retry');
    assert.equal(buttons[1].textContent, 'Stop game');
    buttons[retryChoice ? 0 : 1].click(); await flush();
    assert.equal(requests.filter(r=>r.url==='/api/action').at(-1).body.retry, retryChoice);
  }
  // --- P1: cancelling the offline notice must not abandon the old game ---
  w.confirm = () => true;
  w.document.querySelector('#llmMode').value = 'local';
  w.document.querySelector('#newGame').click(); await flush();
  const confirmAnswers = [true, false];   // [end old game, offline notice]
  w.confirm = () => confirmAnswers.shift();
  const leaveBefore = requests.filter(r => r.url === '/api/leave').length;
  const campaignBefore = requests.filter(r => r.url === '/api/campaign/start').length;
  w.document.querySelector('#campaignGame').click(); await flush();
  assert.equal(requests.filter(r => r.url === '/api/leave').length, leaveBefore);            // no leave
  assert.equal(requests.filter(r => r.url === '/api/campaign/start').length, campaignBefore); // no start
  assert.ok(w.localStorage.getItem('werewolf.game'));                                        // record kept

  // --- P2: the offline "not counted" badge survives status updates and reconnect ---
  w.confirm = () => true;
  w.document.querySelector('#campaignGame').click(); await flush();
  assert.ok(!w.document.querySelector('#modeBadge').hidden);
  assert.match(w.document.querySelector('#modeBadge').textContent, /not counted|不计/);
  w.eval('handleEvent({type:"llm_status", llm_status:{label:"running"}})'); await flush();   // status update
  assert.ok(!w.document.querySelector('#modeBadge').hidden);
  assert.match(w.document.querySelector('#modeBadge').textContent, /not counted|不计/);
  rejoinView = {ok:true, view:{finished:false, review_status:null, counted:false, public_events:[], private_events:[], terminal:[], next_event_no:1}};
  w.eval('rejoin()'); await flush();                                                        // reconnect
  assert.ok(!w.document.querySelector('#modeBadge').hidden);
  assert.match(w.document.querySelector('#modeBadge').textContent, /not counted|不计/);

  // --- campaign short-review retry button (Gap 1) ---
  w.eval('gameId = null; campaignReviewGameId = "ui-campaign-review"');
  w.eval('handleEvent({type:"campaign_review", text:"短复盘", winner:"wolf", unavailable:true})');
  assert.equal(w.document.querySelector('#retryCampaignReview').hidden, false);
  w.document.querySelector('#retryCampaignReview').click(); await flush();
  const reviewReq = requests.filter(r => r.url === '/api/campaign/review').pop();
  assert.ok(reviewReq);
  assert.equal(reviewReq.body.game_id, 'ui-campaign-review');
  assert.match(w.document.querySelector('#log').textContent, /重试复盘/);
  w.eval('handleEvent({type:"campaign_review", text:"好复盘", winner:"wolf"})');           // success hides it
  assert.equal(w.document.querySelector('#retryCampaignReview').hidden, true);

  // --- campaign teaching retry button (teaching retry) ---
  w.eval('gameId = null; campaignTeachingGameId = "ui-campaign-teaching"');
  w.eval('handleEvent({type:"teaching", role:"civilian", text:"教学暂不可用", unavailable:true})');
  assert.equal(w.document.querySelector('#retryCampaignTeaching').hidden, false);

  // 重试成功：记录教学并隐藏按钮
  teachingResponse = {ok:true, game_id:'ui-campaign-teaching', role:'civilian', text:'教学文本'};
  w.document.querySelector('#retryCampaignTeaching').click(); await flush();
  const teachingReq = requests.filter(r => r.url === '/api/campaign/teaching?game_id=ui-campaign-teaching').pop();
  assert.ok(teachingReq);
  assert.match(w.document.querySelector('#log').textContent, /教学文本/);
  assert.equal(w.document.querySelector('#retryCampaignTeaching').hidden, true);

  // 首次失败 → 重试仍失败 → 再次重试成功
  w.eval('handleEvent({type:"teaching", role:"civilian", text:"教学又不可用", unavailable:true})');
  assert.equal(w.document.querySelector('#retryCampaignTeaching').hidden, false);
  teachingResponse = {ok:true, game_id:'ui-campaign-teaching', role:'civilian', text:'教学仍不可用', unavailable:true};
  w.document.querySelector('#retryCampaignTeaching').click(); await flush();
  assert.equal(w.document.querySelector('#retryCampaignTeaching').hidden, false);   // keep on failure
  assert.match(w.document.querySelector('#log').textContent, /教学仍不可用/);

  teachingResponse = {ok:true, game_id:'ui-campaign-teaching', role:'civilian', text:'教学成功'};
  w.document.querySelector('#retryCampaignTeaching').click(); await flush();
  assert.match(w.document.querySelector('#log').textContent, /教学成功/);
  assert.equal(w.document.querySelector('#retryCampaignTeaching').hidden, true);

  assert.deepEqual(errors,[]);
  console.log('PASS: setup, locale, fixed/random selection, start payload, dual-table editing, public-only rendering, unlock, Divine Witch labels and dual/single potion controls');
  w.close();
})().catch(error=>{console.error(error);w.close();process.exitCode=1;});
