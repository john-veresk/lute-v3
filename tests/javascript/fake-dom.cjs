// A minimal DOM and window for running the Codex scripts in node:vm.
const fs = require('node:fs');
const vm = require('node:vm');

function makeElement(tag = 'div') {
  const classes = new Set();
  return {
    tagName: tag.toUpperCase(), hidden: false, disabled: false, checked: false, open: false,
    textContent: '', value: '', children: [], handlers: {}, dataset: {}, attributes: {},
    classList: {
      toggle(name, on) { if (on) classes.add(name); else classes.delete(name); },
      contains: name => classes.has(name),
    },
    addEventListener(type, fn) { this.handlers[type] = fn; },
    dispatchEvent() {},
    append(...children) { this.children.push(...children); },
    appendChild(child) { this.children.push(child); },
    prepend(child) { this.children.unshift(child); },
    replaceChildren() { this.children = []; },
    setAttribute(key, value) { this.attributes[key] = value; },
    getAttribute(key) { return this.attributes[key]; },
    querySelectorAll(selector) { return this.children.filter(child => child.tagName === selector.toUpperCase()); },
  };
}

/** respond(url, body) returns the JSON for a request, or a Response-like object. */
function makeWindow(respond) {
  const elements = new Map();
  const handlers = new Map();
  const requests = [];
  const messages = [];
  let timers = 0;
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElement());
      return elements.get(id);
    },
    createElement: makeElement,
  };
  const window = {
    document, requests, messages,
    location: {origin: 'http://localhost:5001', search: ''},
    parent: {postMessage(message) { messages.push(message); }},
    performance: {now: () => 0},
    setInterval() { return ++timers; },
    clearInterval() {},
    setTimeout(fn) { setImmediate(fn); },
    timers: () => timers,
    addEventListener(type, fn) {
      if (!handlers.has(type)) handlers.set(type, []);
      handlers.get(type).push(fn);
    },
    dispatch(type, event) { (handlers.get(type) || []).forEach(fn => fn(event)); },
    async fetch(url, options) {
      const body = options && JSON.parse(options.body);
      requests.push({url, body});
      const data = await respond(url, body);
      if (data && typeof data.json === 'function') return data;
      return {ok: true, json: async () => data};
    },
  };
  return window;
}

/** Run the Codex scripts once, returning their globals. */
function loadCodex() {
  const context = vm.createContext({URLSearchParams, Event: class Event {}});
  for (const file of ['codex-panel.js', 'codex-term-form.js']) {
    vm.runInContext(fs.readFileSync(`lute/static/js/${file}`, 'utf8'), context);
  }
  return vm.runInContext(
    '({CodexPanel, CodexTermForm, applyCodexParent, startTermCodex, termStackOnLoad, pushTermStack, popTermStack})',
    context
  );
}

const settle = () => new Promise(resolve => setImmediate(resolve));

module.exports = {makeElement, makeWindow, loadCodex, settle};
