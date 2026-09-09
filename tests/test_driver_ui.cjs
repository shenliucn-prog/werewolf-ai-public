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
w.fetch = async (url, options = {}) => {
  const body = options.body ? JSON.parse(options.body) : null;
  requests.push({url, body});
  let response;
  let ok = true;
  if (url === '/api/agent_connections') response = connectionsResponse;
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

  assert.deepEqual(errors, []);
  console.log('PASS: driver selector (api/agent/offline), pre-configured connection, and unconfigured guidance');
  w.close();
})().catch(error => { console.error(error); w.close(); process.exitCode = 1; });
