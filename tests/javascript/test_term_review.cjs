// node tests/javascript/test_term_review.cjs
// Exercise async saves, keyboard gating and stale/deleted cards without a server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor() {
    this.hidden = false;
    this.disabled = false;
    this.textContent = '';
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
  }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  setAttribute(name, value) { this.attributes[name] = value; }
  replaceChildren() { this.children = []; }
  appendChild(child) { this.children.push(child); }
  focus() { this.focused = true; }
  closest() { return null; }
}

const tick = () => new Promise(resolve => setImmediate(resolve));
const source = fs.readFileSync('lute/static/js/term-review.js', 'utf8');

function fixture(ids, options = {}) {
  const elements = {};
  const names = ['show-answer', 'skip', 'retry', 'error', 'card', 'answer', 'word',
    'language', 'meanings', 'loading', 'progress', 'progress-bar', 'current-status',
    'navigation', 'help', 'complete', 'complete-title', 'summary'];
  names.forEach(name => { elements[name] = new Element(); });
  elements.complete.hidden = true;
  const levels = [1, 2, 3, 4, 5, 99, 98].map(status => {
    const element = new Element();
    element.dataset.reviewStatus = String(status);
    element.textContent = String(status);
    return element;
  });
  const root = {
    querySelector: selector => elements[selector.replace('#review-', '')],
    querySelectorAll: selector => selector === '[data-review-status]' ? levels
      : [...levels, elements['show-answer'], elements.skip, elements.retry],
  };
  const posts = [];
  const loaded = [];
  const context = vm.createContext({
    document: {querySelector() { return null; }, createElement() { return new Element(); }, addEventListener() {}},
    Math: Object.assign(Object.create(Math), {random: () => options.random ?? .999}),
    root,
    configuration: {term_ids: ids, untranslated: 2},
    fetch: async (url, request = {}) => {
      if (request.method === 'POST') {
        posts.push(JSON.parse(request.body));
        if (options.save) return options.save(posts);
        return {ok: true, json: async () => ({status: posts.at(-1).values})};
      }
      const id = Number(url.split('/').at(-1));
      loaded.push(id);
      if (options.load) return options.load(id, loaded);
      return {ok: true, status: 200, json: async () => ({id, text: `word${id}`, language: 'Finnish',
        direction: 'rtl', status: posts.length ? 4 : 1,
        meanings: [{parent: 'base', translation: '<script>evil()</script>\ntranslation'}]})};
    },
  });
  vm.runInContext(source, context);
  const review = vm.runInContext('new LuteTermReview(root, configuration)', context);
  return {review, elements, levels, posts, loaded};
}

(async () => {
  const f = fixture([1, 2]);
  await tick();
  assert.equal(f.elements.word.textContent, 'word1');
  assert.equal(f.elements.word.dir, 'rtl');
  assert.equal(f.elements.answer.hidden, true);
  assert.equal(f.elements.complete.hidden, true);
  assert.equal(f.elements.meanings.children.length, 0, 'no answer in the front DOM');
  await f.review.rate(4);
  assert.equal(f.posts.length, 0, 'cannot rate before revealing');
  let prevented = false;
  f.review.handleKey({code: 'Space', key: ' ', preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(f.elements.answer.hidden, false);
  assert.equal(f.elements.meanings.children[1].textContent, '<script>evil()</script>\ntranslation');
  f.review.handleKey({key: '4', preventDefault() {}});
  await tick();
  assert.equal(f.posts[0].term_id, 1);
  assert.equal(f.posts[0].values, 4);
  assert.equal(f.review.index, 1);
  assert.equal(f.elements.word.textContent, 'word2');
  assert.equal(f.elements.answer.hidden, true, 'next answer starts hidden');
  assert.equal(f.review.card.status, 4, 'loads current synchronized status');
  f.review.skip();
  await tick();
  assert.equal(f.posts.length, 1, 'skip never writes');
  assert.equal(f.review.rated, 1);
  assert.equal(f.review.skipped, 1);
  assert.equal(f.elements.card.hidden, true);
  assert.equal(f.elements['complete-title'].textContent, 'Practice complete');

  const tapped = fixture([1]);
  await tick();
  tapped.elements.card.listeners.click();
  assert.equal(tapped.elements.answer.hidden, false, 'tapping the card reveals the answer');

  const repeated = fixture([1, 1, 2, 1, 2]);
  await tick();
  assert.equal(repeated.elements.progress.textContent, 'Card 1 of 2');
  repeated.review.showAnswer();
  await repeated.review.rate(3);
  assert.equal(repeated.elements.word.textContent, 'word2');
  assert.equal(repeated.elements.progress.textContent, 'Card 2 of 2');
  repeated.review.skip();
  await tick();
  assert.deepEqual(repeated.loaded, [1, 2], 'each term is shown only once');
  assert.equal(repeated.posts.length, 1);
  assert.equal(repeated.elements.complete.hidden, false);
  assert.equal(repeated.elements.progress.textContent, '2 of 2 cards completed');
  assert.equal(repeated.elements.summary.textContent, '1 reviewed · 1 skipped · 0 unavailable.');

  let release;
  const failing = fixture([1], {save: posts => posts.length === 1
    ? new Promise(resolve => { release = resolve; })
    : {ok: true, json: async () => ({status: 5})}});
  await tick();
  failing.review.showAnswer();
  const pending = failing.review.rate(5);
  assert.equal(failing.review.busy, true);
  assert.equal(failing.levels.every(level => level.disabled), true);
  await failing.review.rate(5);
  failing.review.skip();
  assert.equal(failing.posts.length, 1, 'double input does not duplicate a save');
  assert.equal(failing.review.index, 0, 'stays on card until saving succeeds');
  release({ok: false});
  await pending;
  assert.equal(failing.review.index, 0);
  assert.equal(failing.elements.answer.hidden, false);
  assert.equal(failing.elements.error.hidden, false);
  assert.equal(failing.review.busy, false);
  await failing.review.rate(5);
  assert.equal(failing.review.rated, 1);

  const missing = fixture([1, 2, 3], {load: id => ({ok: false, status: {1: 404, 2: 410, 3: 422}[id]})});
  await tick();
  assert.equal(missing.review.unavailable, 3);
  assert.equal(missing.elements.complete.hidden, false);
  assert.equal(missing.posts.length, 0);

  const broken = fixture([1], {load: () => { throw new Error('offline'); }});
  await tick();
  assert.equal(broken.elements.retry.hidden, false);
  assert.equal(broken.elements.error.hidden, false);
  assert.equal(broken.review.index, 0);
  broken.review.skip();
  await tick();
  assert.equal(broken.review.skipped, 1);

  const shuffled = fixture([1, 2, 3], {random: 0});
  await tick();
  assert.deepEqual([...shuffled.review.ids], [2, 3, 1]);

  const empty = fixture([]);
  await tick();
  assert.equal(empty.elements['complete-title'].textContent, 'No terms to practice');
  assert.equal(empty.loaded.length, 0);
  console.log('Term review interaction checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
