// DOM integration test for the unified driver selector + unconfigured guidance.
// From the repository root: npm test (development only).
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
const connectionsResponse = {connections: [
  {name: 'local-codex', adapter: 'codex', model: 'gpt-x'},
]};
let startResponse = {ok: true, game_id: 'ui-test'};
let rejoinResponse = null;
w.fetch = async (url, options = {}) => {
  const body = options.body ? JSON.parse(options.body) : null;
  requests.push({url, body});
  let response;
  let ok = true;
  if (url === '/api/agent_connections') response = connectionsResponse;
  else if (url.startsWith('/api/offline/cast')) response = {characters: players.map(p => ({...p, description:'Fixed personality'}))};
  else if (url === '/api/offline/start') response = {ok:true, game_id:'offline-ui', counted:false};
  else if (url.startsWith('/api/rejoin')) response = rejoinResponse;
  else if (url.startsWith('/api/boards')) response = {
    boards: [{id:'classic',name:'Classic',difficulty:'Intro',roles:['seer','werewolf','werewolf','villager']}],
    roles: {seer:{cn:'Seer'},werewolf:{cn:'Werewolf'},villager:{cn:'Villager'}}};
  else if (url.startsWith('/api/cast')) response = {players, personalities: []};
  else if (url === '/api/start') { response = startResponse; ok = startResponse.ok !== false; }
  else if (url === '/api/campaign/status') response = {ok:true, role:'civilian', board_id:'classic', goal_cn:'判断身份', goal_en:'Read', unlocked:0};
  else response = {ok: true};
  return {ok, status: ok ? 200 : 422, json: async () => response};
};
w.EventSource = class { close(){} constructor(){} };
w.confirm = () => true;
vm.runInContext(fs.readFileSync(path.join(root, 'js', 'i18n.js'), 'utf8'), dom.getInternalVMContext());
vm.runInContext(fs.readFileSync(path.join(root, 'js', 'app.js'), 'utf8'), dom.getInternalVMContext());
const flush = () => new Promise(resolve => setTimeout(resolve, 10));
(async () => {
  await flush();
  const driverMode = w.document.querySelector('#driverMode');
  const connectionRow = w.document.querySelector('#agentConnectionRow');
  const connectionSel = w.document.querySelector('#agentConnection');
  assert.ok(driverMode);
  assert.equal(driverMode.value, '');                       // server default
  assert.equal(connectionRow.hidden, true);                 // hidden unless agent

  // ---- agent driver: select a pre-configured connection (never a command) ----
  driverMode.value = 'agent';
  driverMode.dispatchEvent(new w.Event('change'));
  assert.equal(connectionRow.hidden, false);
  assert.equal(connectionSel.options.length, 1);
  assert.equal(connectionSel.options[0].value, 'local-codex');

  w.document.querySelector('#newGame').click();
  await flush();
  const agentStart = requests.filter(r => r.url === '/api/start').pop().body;
  assert.equal(agentStart.driver, 'agent');
  assert.equal(agentStart.connection, 'local-codex');
  assert.ok(!('command' in agentStart));                    // never an executable

  w.eval('gameId = null');

  // ---- offline driver: explicit offline is sent as the driver selector ----
  driverMode.value = 'offline';
  driverMode.dispatchEvent(new w.Event('change'));
  w.document.querySelector('#newGame').click();
  await flush();
  const offlineStart = requests.filter(r => r.url === '/api/start').pop().body;
  assert.equal(offlineStart.driver, 'offline');

  w.eval('gameId = null');

  // ---- unconfigured (422): the server's guidance message is surfaced ----
  startResponse = {ok: false, detail: 'No model or offline mode configured. / 未配置模型或离线模式。'};
  driverMode.value = '';
  driverMode.dispatchEvent(new w.Event('change'));
  w.document.querySelector('#newGame').click();
  await flush();
  const guidance = w.document.querySelector('#setupGuidance');
  assert.equal(guidance.hidden, false);
  assert.match(guidance.textContent, /未配置模型或离线模式/);

  // ---- table_answer (human clarification): answer / skip controls ----
  w.eval('gameId = "ui-test"');
  w.eval('showAction({kind: "table_answer", data: {from: "Alice"}})');
  assert.ok(w.document.querySelector('#tableAnswerInput'));
  assert.ok(w.document.querySelector('#skipTableAnswer'));
  assert.ok(w.document.querySelector('#sendTableAnswer'));
  w.document.querySelector('#skipTableAnswer').click();
  await flush();
  const skipAction = requests.filter(r => r.url === '/api/action').pop().body;
  assert.equal(skipAction.skip, true);
  assert.equal(skipAction.game_id, 'ui-test');
  w.eval('showAction({kind: "table_answer", data: {from: "Alice"}})');
  w.document.querySelector('#tableAnswerInput').value = '我来回答';
  w.document.querySelector('#sendTableAnswer').click();
  await flush();
  const answerAction = requests.filter(r => r.url === '/api/action').pop().body;
  assert.equal(answerAction.answer, '我来回答');
  assert.equal(answerAction.game_id, 'ui-test');

  // A detached old button must not submit its payload for the next question.
  w.eval('showAction({kind:"table_answer", request_id:"old-request", data:{from:"Alice"}})');
  const oldButton = w.document.querySelector('#skipTableAnswer');
  w.eval('showAction({kind:"table_answer", request_id:"new-request", data:{from:"Bob"}})');
  const beforeStale = requests.filter(r => r.url === '/api/action').length;
  oldButton.click();
  await flush();
  assert.equal(requests.filter(r => r.url === '/api/action').length, beforeStale);
  w.document.querySelector('#skipTableAnswer').click();
  await flush();
  assert.equal(requests.filter(r => r.url === '/api/action').pop().body.request_id, 'new-request');

  // Real frontend rejoin path retains the server's durable request identity.
  rejoinResponse = {ok:true, view:{finished:false, public_events:[], private_events:[],
    terminal:[], next_event_no:42, pending:{type:'request', kind:'table_answer',
      request_id:'restored-request', event_no:41, data:{from:'Bob'}}}};
  await w.eval('rejoin()');
  w.document.querySelector('#tableAnswerInput').value = '恢复后的答案';
  w.document.querySelector('#sendTableAnswer').click();
  await flush();
  const recovered = requests.filter(r => r.url === '/api/action').pop().body;
  assert.equal(recovered.request_id, 'restored-request');
  assert.equal(recovered.answer, '恢复后的答案');

  assert.equal(w.document.querySelector('#offlineCharacter').options.length, 12);
  w.confirm = () => false;
  const beforeCancel = requests.length;
  w.document.querySelector('#offlineGame').click();
  await flush();
  assert.equal(requests.length, beforeCancel);
  w.confirm = () => true;
  w.document.querySelector('#offlineSpectator').checked = true;
  w.document.querySelector('#offlineGame').click();
  await flush();
  const offlineBody = requests.filter(r => r.url === '/api/offline/start').pop().body;
  assert.equal(offlineBody.offline_confirmed, true);
  assert.equal(offlineBody.spectator, true);
  assert.equal(offlineBody.player_role, 'random');
  assert.ok(!('llm' in offlineBody));
  w.eval('showPlayer(null)');
  assert.match(w.document.querySelector('#playerBody').textContent, /旁观|spectator/);
  rejoinResponse = {ok:true, view:{finished:false, counted:false, public_events:[], private_events:[],
    terminal:[], next_event_no:51, pending:{type:'request', kind:'speech', request_id:'offline-restored',
      event_no:50, choices:[{id:'suspect:2', group:'Opinion', label:'Suspect seat 2'}]}}};
  await w.eval('rejoin()');
  const choiceButton = w.document.querySelector('#actionPanel button');
  assert.equal(choiceButton.textContent, 'Suspect seat 2');
  choiceButton.click();
  await flush();
  const choiceAction = requests.filter(r => r.url === '/api/action').pop().body;
  assert.equal(choiceAction.choice_id, 'suspect:2');
  assert.equal(choiceAction.request_id, 'offline-restored');
  assert.ok(!('text' in choiceAction));
  w.eval('showAction({kind:"speech",request_id:"next",choices:[]})');
  const beforeDetached = requests.length;
  choiceButton.click();
  await flush();
  assert.equal(requests.length, beforeDetached);
  w.eval('showAction({kind:"speech",request_id:"situational",choices:[{id:"context:probe",group:"Discussion",label:"Why that report?",suggested:true},{id:"wait",group:"Respond",label:"Listen",suggested:true},{id:"claim:seer",group:"Claim",label:"I claim seer"}]})');
  const panel = w.document.querySelector('#actionPanel');
  assert.equal(panel.querySelectorAll(':scope > button').length, 2);
  const more = panel.querySelector('details');
  assert.equal(more.open, false);
  assert.equal(more.querySelector('button').textContent, 'I claim seer');
  more.open = true;
  more.querySelector('button').click();
  await flush();
  assert.equal(requests.filter(r => r.url === '/api/action').pop().body.choice_id, 'claim:seer');
  assert.deepEqual(errors, []);
  console.log('PASS: driver selector (api/agent/offline), pre-configured connection, unconfigured guidance, and table_answer controls');
  w.close();
})().catch(error => { console.error(error); w.close(); process.exitCode = 1; });
