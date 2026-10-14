// Optional context phrases and existing phrase-word cards use explicit saves.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync('lute/static/js/codex-panel.js', 'utf8');
const phrases = [
  {text: 'looked after', translation: 'присматривал за'},
  {text: 'looked after the cats', translation: 'присматривал за кошками'},
];

function makePanel({words = [], phraseCards = phrases, saveResponse} = {}) {
  const elements = new Map();
  const handlers = new Map();
  const requests = [];
  const messages = [];
  const parent = {postMessage(message) {messages.push(message);}};
  function element() {
    return {
      hidden: true, disabled: false, textContent: '', children: [], handlers: {}, dataset: {},
      classList: {toggle() {}},
      addEventListener(type, fn) {this.handlers[type] = fn;},
      append(...children) {this.children.push(...children);},
      appendChild(child) {this.children.push(child);},
      replaceChildren() {this.children = [];},
      setAttribute(key, value) {this[key] = value;},
      querySelectorAll(type) {return this.children.filter(child => child.type === type);},
    };
  }
  function getElement(id) {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  }
  const context = vm.createContext({
    URLSearchParams,
    window: {
      location: {origin: 'http://localhost:5001', search: '?language_id=1&request_id=current'},
      parent,
      addEventListener(type, fn) {
        if (!handlers.has(type)) handlers.set(type, []);
        handlers.get(type).push(fn);
      },
    },
    document: {getElementById: getElement, createElement: element},
    performance: {now: () => 0},
    setInterval() {return 1;}, clearInterval() {},
    async fetch(url, options) {
      requests.push({url, body: options && JSON.parse(options.body)});
      let data;
      if (url === '/translation/jobs') data = {job_id: 'job'};
      else if (url === '/translation/jobs/job') data = {
        status: 'complete',
        result: {lemma: '', is_inflected: false, options: [{translation: 'смотрел', explanation: ''}], words, phrases: phraseCards},
      };
      else if (saveResponse) return saveResponse();
      else {
        const cards = url === '/translation/phrases' ? phraseCards : words;
        data = {saved: JSON.parse(options.body).indices.map(index => ({index, ...cards[index]}))};
      }
      return {ok: true, json: async () => data};
    },
  });
  vm.runInContext(script, context);
  for (const fn of handlers.get('message')) fn({
    origin: context.window.location.origin, source: parent,
    data: {event: 'LuteCodexLookup', request_id: 'current', payload: {text: 'looked', context: 'He looked after the cats.', autostart: true}},
  });
  return {getElement, requests, messages};
}

const settle = () => new Promise(resolve => setImmediate(resolve));

async function checks() {
  const panel = makePanel();
  await settle();
  assert.equal(panel.getElement('codex-phrases').hidden, false);
  assert.equal(panel.getElement('codex-words').hidden, true);
  const rows = panel.getElement('codex-phrase-cards').children;
  assert.equal(rows.length, 2);
  assert.equal(rows[0].children[1].children[0].textContent, 'looked after');
  assert.equal(rows[0].children[1].children[1].textContent, 'присматривал за');
  assert.equal(rows[0].children[0].checked, false, 'context phrases start unchecked');
  assert.equal(panel.getElement('codex-add-phrases').disabled, true);
  assert.equal(panel.requests.length, 2, 'rendering suggestions does not save cards');
  assert.equal(panel.messages.filter(message => message.event === 'LuteCodexTranslation').length, 1);
  assert.equal(panel.messages.find(message => message.event === 'LuteCodexTranslation').text, 'looked');

  await rows[0].children[2].handlers.click();
  assert.deepEqual(panel.requests[2], {
    url: '/translation/phrases', body: {language_id: 1, job_id: 'job', indices: [0]},
  });
  assert.equal(rows[0].children[2].textContent, 'Saved');
  assert.equal(rows[0].children[2].disabled, true);
  assert.equal(rows[0].children[0].disabled, true);
  assert.equal(panel.messages.filter(message => message.event === 'LuteCodexWordCardsSaved').length, 1, 'saving refreshes reading highlights');
  assert.equal(panel.messages.filter(message => message.event === 'LuteCodexTranslation').length, 1, 'saving a phrase leaves the word form alone');
  rows[1].children[0].checked = true;
  rows[1].children[0].handlers.change();
  assert.equal(panel.getElement('codex-add-phrases').disabled, false);
  await panel.getElement('codex-add-phrases').onclick();
  assert.deepEqual(panel.requests[3].body.indices, [1], 'only checked unsaved phrases are saved');

  const empty = makePanel({phraseCards: []});
  await settle();
  assert.equal(empty.getElement('codex-phrases').hidden, true);

  const wordPanel = makePanel({phraseCards: [], words: [{text: 'cats', translation: 'кошки', is_inflected: true, lemma: 'cat', lemma_translation: 'кошка'}]});
  await settle();
  const wordRow = wordPanel.getElement('codex-word-cards').children[0];
  assert.equal(wordRow.children[0].checked, true, 'existing word cards remain selected by default');
  assert.equal(wordRow.children[1].children[2].textContent, 'Parent: cat — кошка');
  await wordPanel.getElement('codex-add-words').onclick();
  assert.equal(wordPanel.requests[2].url, '/translation/words');

  const failed = makePanel({saveResponse: async () => ({ok: false, json: async () => ({error: 'Translation expired. Translate again.'})})});
  await settle();
  const failedRow = failed.getElement('codex-phrase-cards').children[0];
  await failedRow.children[2].handlers.click();
  assert.equal(failed.getElement('codex-phrases-status').textContent, 'Translation expired. Translate again.');
  assert.equal(failedRow.children[2].disabled, false, 'failed saves can be retried');
  assert.equal(failedRow.children[2].textContent, 'Add phrase');
  assert.equal(failed.messages.filter(message => message.event === 'LuteCodexWordCardsSaved').length, 0);

  let releaseSave;
  const stale = makePanel({saveResponse: () => new Promise(resolve => {releaseSave = resolve;})});
  await settle();
  const pendingSave = stale.getElement('codex-phrase-cards').children[0].children[2].handlers.click();
  await stale.getElement('codex-retry').handlers.click();
  const newRow = stale.getElement('codex-phrase-cards').children[1];
  newRow.children[0].checked = true;
  newRow.children[0].handlers.change();
  releaseSave({ok: true, json: async () => ({saved: [{index: 0, ...phrases[0]}]})});
  await pendingSave;
  assert.equal(stale.getElement('codex-add-phrases').disabled, false, 'a late save cannot change a newer lookup');
  assert.equal(newRow.children[2].textContent, 'Add phrase');
  assert.equal(stale.messages.filter(message => message.event === 'LuteCodexWordCardsSaved').length, 0);
  console.log('Codex optional card checks passed');
}
checks().catch(error => {console.error(error); process.exitCode = 1;});
