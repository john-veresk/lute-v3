// A saved card must not submit a job or start the timer until the panel button is clicked.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync('lute/static/js/codex-panel.js', 'utf8');
const origin = 'http://localhost:5001';

function makePanel(kind = 'term') {
  const elements = new Map();
  const handlers = new Map();
  const requests = [];
  const parent = {postMessage() {}};
  let timers = 0;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      hidden: true, textContent: '', handlers: {},
      addEventListener(type, fn) {this.handlers[type] = fn;},
      replaceChildren() {},
    });
    return elements.get(id);
  }
  const context = vm.createContext({
    URLSearchParams,
    window: {
      location: {origin, search: `?language_id=1&request_id=current&kind=${kind}`},
      parent,
      addEventListener(type, fn) {
        if (!handlers.has(type)) handlers.set(type, []);
        handlers.get(type).push(fn);
      },
    },
    document: {getElementById: element},
    performance: {now: () => 0},
    setInterval() {return ++timers;},
    clearInterval() {},
    fetch(url, options) {requests.push({url, options}); return new Promise(() => {});},
  });
  vm.runInContext(script, context);
  return {
    element, requests, timers: () => timers,
    lookup(payload, changes = {}) {
      for (const fn of handlers.get('message')) fn({
        origin, source: parent,
        data: {event: 'LuteCodexLookup', request_id: 'current', payload},
        ...changes,
      });
    },
  };
}

const payload = {text: 'kissat', context: 'Kissat nukkuvat.', autostart: false};
const saved = makePanel();
assert.equal(saved.requests.length, 0, 'loading the panel does not submit a job');
saved.lookup({...payload, autostart: true}, {origin: 'https://untrusted.example'});
saved.lookup({...payload, autostart: true}, {source: {}});
assert.equal(saved.requests.length, 0, 'untrusted messages cannot start translation');
saved.lookup(payload);
assert.equal(saved.requests.length, 0, 'opening a saved card does not submit a job');
assert.equal(saved.timers(), 0, 'the timer waits for the explicit request');
assert.equal(saved.element('codex-start').hidden, false, 'shows the separate translation button');
assert.equal(saved.element('codex-text').textContent, payload.text);
saved.lookup({...payload, autostart: true});
assert.equal(saved.requests.length, 0, 'repeated lookup messages cannot bypass the button');
saved.element('codex-start').handlers.click();
assert.equal(saved.requests.length, 1, 'clicking the panel button submits one job');
assert.equal(saved.requests[0].url, '/translation/jobs');
assert.equal(saved.requests[0].options.method, 'POST');
assert.deepEqual(JSON.parse(saved.requests[0].options.body), {
  language_id: 1, text: payload.text, context: payload.context, kind: 'term',
});
assert.equal(saved.element('codex-start').hidden, true, 'hides the button while translating');
assert.equal(saved.timers(), 1, 'starts the timer with the explicit request');

const fresh = makePanel();
fresh.lookup({...payload, autostart: true});
assert.equal(fresh.requests.length, 1, 'new terms still translate automatically');

const sentence = makePanel('sentence');
sentence.lookup({text: 'Kissat nukkuvat.', context: ''});
assert.equal(sentence.requests.length, 1, 'sentence commands still translate immediately');
console.log('Codex manual-start regression checks passed');
