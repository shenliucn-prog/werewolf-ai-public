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
w.fetch = async (url, options = {}) => {
  const body = options.body ? JSON.parse(options.body) : null;
  requests.push({url, body});
  const response = url.startsWith('/api/boards') ? {boards: [
    {id:'classic',name:'Classic',difficulty:'Intro',roles:['seer','werewolf','werewolf','villager']},
    {id:'other',name:'Other',difficulty:'Intro',roles:['guard','werewolf','villager']},
    {id:'divine_witch_dual',name:'Divine Witch',difficulty:'Experimental',roles:['witch','werewolf','villager'],role_labels:{witch:'Divine Witch'}}],
    roles:{seer:{cn:'Seer'},werewolf:{cn:'Werewolf'},villager:{cn:'Villager'},guard:{cn:'Guard'}}} :
    url.startsWith('/api/cast') ? {players, personalities: [{id:'aman',label:'Analytical'}, {id:'dashan',label:'Bold'}]} :
    url === '/api/start' ? {ok:true,game_id:'ui-test'} : {ok:true};
  return {ok:true,json:async()=>response};
};
w.EventSource = class {close(){}};
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
  assert.match(w.document.querySelector('#textCommand').textContent,/chat_game .*--lang zh-CN --offline/);
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
  assert.match(w.document.querySelector('#textCommand').textContent,/--lang en --offline/);
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
  assert.deepEqual(errors,[]);
  console.log('PASS: setup, locale, fixed/random selection, start payload, dual-table editing, public-only rendering, unlock, Divine Witch labels and dual/single potion controls');
  w.close();
})().catch(error=>{console.error(error);w.close();process.exitCode=1;});
