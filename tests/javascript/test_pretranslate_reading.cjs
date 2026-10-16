// node tests/javascript/test_pretranslate_reading.cjs
// Opening cards moves background translation to the reader's latest position.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const tick = () => new Promise(resolve => setImmediate(resolve));
const template = fs.readFileSync('lute/templates/read/index.html', 'utf8');
const collectWords = template.match(/  function pretranslate_page\([\s\S]*?\n  }/)[0];

function fixture(enabled = true) {
  const items = [
    ['Kissa', true], [' ', false], ['nukkuu', true], ['. ', false],
    ['Koira', true, 1], [' ', false], ['juoksee', true], [' ', false], ['kissa', true], ['.', false],
  ].map(([text, word, status = 0], order) => ({
    textContent: text, word, status,
    data: {'order': order, 'sentence-id': order < 4 ? 1 : 2, 'paragraph-id': 1, 'lang-id': 1, 'wid': order + 1},
  }));
  function $(value) {
    const elements = typeof value === 'string'
      ? items.filter(el => value === 'span.textitem' || (el.word && el.status === 0))
      : Array.isArray(value) ? value : [value];
    return {
      length: elements.length,
      data: key => elements[0]?.data[key],
      attr: key => elements[0]?.data[key.replace('data-', '')],
      text: () => elements.map(el => el.textContent).join(''),
      toArray: () => elements,
      each(fn) { elements.forEach(el => fn.call(el)); },
      filter: fn => $(elements.filter(el => fn.call(el))),
      eq: index => $(elements.at(index)),
    };
  }
  const submitted = [];
  const progress = [];
  const navigated = [];
  let release;
  const context = vm.createContext({
    $, LUTE_CODEX_PRETRANSLATE: enabled,
    applyInitialPaneSizes() {},
    top: {frames: {wordframe: {location: {replace: url => navigated.push(url)}}}},
    progress,
    fetch: async (url, options) => {
      if (options) {
        const body = JSON.parse(options.body);
        submitted.push(body);
        return {ok: true, json: async () => ({job_id: body.text})};
      }
      if (submitted.length === 1) await new Promise(resolve => { release = resolve; });
      return {ok: true, json: async () => ({status: 'complete'})};
    },
  });
  context.window = context;
  vm.runInContext(fs.readFileSync('lute/static/js/pretranslate.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('lute/static/js/lute.js', 'utf8'), context);
  vm.runInContext(`const pretranslator = new Pretranslator({
    languageId: 1, fetch, wait: async () => {}, onProgress: event => progress.push({...event}),
  });`, context);
  vm.runInContext(collectWords, context);
  const pretranslator = vm.runInContext('pretranslator', context);
  return {
    context, pretranslator, submitted, progress, navigated,
    release: () => release(),
    open: order => context.show_term_edit_form($(items[order])),
    select: (start, end) => context.show_multiword_term_edit_form($(items.slice(start, end + 1))),
    start: () => context.pretranslate_page(),
    texts: () => submitted.map(body => body.text),
    queued: () => Array.from(pretranslator.queue, word => word.text),
  };
}

(async () => {
  const ahead = fixture();
  ahead.start();
  await tick();
  ahead.open(4); // A known word still establishes the reading position.
  assert.deepEqual(ahead.texts(), ['Kissa'], 'the current translation is allowed to finish');
  assert.deepEqual(ahead.queued(), ['juoksee', 'kissa'], 'skip words before and at the selected position');
  assert.equal(ahead.navigated.at(-1), '/read/edit_term/5', 'the card still opens');
  ahead.release();
  await ahead.pretranslator.draining;
  assert.deepEqual(ahead.texts(), ['Kissa', 'juoksee', 'kissa'], 'the next request follows the clicked word');
  assert.equal(ahead.submitted[1].context, 'Koira juoksee kissa.', 'keep the complete sentence as context');
  assert.equal(ahead.progress.at(-1).done, 2, 'the old in-flight word does not count toward the new queue');

  const back = fixture();
  back.start();
  await tick();
  back.open(6);
  back.open(0);
  assert.deepEqual(back.queued(), ['nukkuu', 'juoksee', 'kissa'], 'an earlier click rebuilds from the earlier position');
  back.release();
  await back.pretranslator.draining;
  assert.deepEqual(back.texts(), ['Kissa', 'nukkuu', 'juoksee', 'kissa'], 'the latest click wins while a request is running');
  assert.equal(back.submitted.at(-1).context, 'Koira juoksee kissa.', 'deduplicate after filtering so later occurrences remain');

  const phrase = fixture();
  phrase.start();
  await tick();
  phrase.select(2, 6);
  assert.deepEqual(phrase.queued(), ['kissa'], 'a phrase moves the queue past its last selected item');
  assert.equal(phrase.navigated.at(-1), '/read/termform/1/nukkuu. Koira juoksee');
  phrase.release();
  await phrase.pretranslator.draining;
  assert.deepEqual(phrase.texts(), ['Kissa', 'kissa']);

  const end = fixture();
  end.start();
  await tick();
  end.open(8);
  assert.deepEqual(end.queued(), [], 'opening the last word clears the waiting queue');
  end.release();
  await end.pretranslator.draining;
  assert.deepEqual(end.texts(), ['Kissa'], 'only the current job finishes at the end of the page');
  end.open(4);
  await end.pretranslator.draining;
  assert.deepEqual(end.texts(), ['Kissa', 'juoksee', 'kissa'], 'going back restarts a drained queue');

  const disabled = fixture(false);
  disabled.start();
  disabled.open(4);
  disabled.select(2, 6);
  await tick();
  assert.deepEqual(disabled.texts(), [], 'opening cards does not enable background translation');

  console.log('Reading-position pretranslation checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
