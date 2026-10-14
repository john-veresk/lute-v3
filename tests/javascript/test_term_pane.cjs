// node tests/javascript/test_term_pane.cjs
// The phone term pane slides over the text and closes with the system Back button.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function classes() {
  const set = new Set();
  return {add: name => set.add(name), remove: name => set.delete(name), contains: name => set.has(name)};
}

function fixture(compact = true) {
  const entries = [{state: null}];
  // A frame navigation adds an entry that keeps the page state and fires no popstate.
  const history = {
    get state() { return entries.at(-1).state; },
    pushState(state) { entries.push({state}); },
    frameNavigation() { entries.push({state: this.state, frame: true}); },
    back() { const entry = entries.pop(); if (!entry.frame) this.onpop?.(); },
  };
  const pane = {classList: classes()};
  const root = {classList: classes()};
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync('lute/static/js/term-pane.js', 'utf8'), context);
  const termPane = vm.runInContext('(deps) => new TermPane(deps)', context)({
    pane, root, history, isCompact: () => compact,
  });
  history.onpop = () => termPane.onPopState();
  // The reading page reports when Back reloaded the term form frame.
  const settle = () => { while (entries.at(-1).state && !termPane.isOpen && termPane.unwinding) termPane.onFrameTraversed(); };
  return {termPane, pane, root, entries, history, settle};
}

const phone = fixture();
assert.equal(phone.termPane.openIfRequested(), false, 'a form opened without a tap stays hidden');
phone.termPane.request();
assert.equal(phone.termPane.openIfRequested(), true);
assert.equal(phone.pane.classList.contains('open-dict'), true);
assert.equal(phone.root.classList.contains('term-pane-open'), true);
assert.equal(phone.entries.length, 2, 'opening adds one Back step');
assert.equal(phone.termPane.openIfRequested(), false, 'a request opens the pane only once');
phone.termPane.request();
phone.termPane.openIfRequested();
assert.equal(phone.entries.length, 2, 'opening another word does not add Back steps');

phone.history.back();
assert.equal(phone.termPane.isOpen, false, 'the system Back button closes the pane');
assert.equal(phone.root.classList.contains('term-pane-open'), false);

phone.termPane.open();
phone.termPane.close();
assert.equal(phone.termPane.isOpen, false);
assert.equal(phone.entries.length, 1, 'closing from the page removes its Back step');
phone.termPane.close();
assert.equal(phone.entries.length, 1, 'closing twice never leaves the page');

phone.termPane.open();
phone.history.frameNavigation();
phone.termPane.close();
phone.settle();
assert.equal(phone.entries.length, 1, 'a saved form frame entry is unwound too');
assert.equal(phone.entries[0].state, null);

phone.termPane.open();
phone.history.frameNavigation();
phone.termPane.close();
phone.termPane.request();
phone.termPane.openIfRequested();
phone.termPane.onFrameTraversed();
assert.equal(phone.termPane.isOpen, true, 'tapping a word while closing keeps the new pane open');
assert.equal(phone.history.state.luteTermPane, true);

phone.termPane.close();
phone.termPane.onFrameTraversed();
phone.termPane.onFrameTraversed();
assert.equal(phone.entries.length, 1, 'stray frame loads never step back past the reading page');

const desktop = fixture(false);
desktop.termPane.request();
assert.equal(desktop.termPane.openIfRequested(), false, 'the side-by-side layout has no sliding pane');
desktop.termPane.close();
assert.equal(desktop.entries.length, 1);
console.log('Term pane checks passed');
