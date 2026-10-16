// node tests/javascript/test_codex_lookup_modes.cjs
// A filled Translation shows only a saved result; an empty one translates.
const assert = require('node:assert/strict');
const {makeWindow, loadCodex, settle} = require('./fake-dom.cjs');

const {CodexPanel, startTermCodex} = loadCodex();
const result = {lemma: '', is_inflected: false, options: [{translation: 'кошки', explanation: ''}], words: [], phrases: []};

function openCard(translation, job = {job_id: null}, {mode = 'auto', beforePoll = () => {}} = {}) {
  const win = makeWindow(async url => {
    if (url === '/translation/jobs') return job;
    beforePoll();
    return {status: 'complete', result};
  });
  const fields = {
    '#translation': {value: translation, dispatchEvent() {}},
    '#text': {value: 'kissat'},
    '#language_id': {value: '1'},
    '#codex_phrases': {value: ''},
    '#codex_words': {value: ''},
  };
  win.document.getElementById('term-form-container').querySelector = selector => fields[selector];
  const panel = startTermCodex(win, 'Kissat nukkuvat.');
  if (mode === 'refresh') panel.start('refresh');
  return {win, fields, el: id => win.document.getElementById(id)};
}

async function checks() {
  const fresh = openCard('', {job_id: 'job', saved: false});
  assert.deepEqual(fresh.win.requests[0], {url: '/translation/jobs', body: {
    language_id: 1, text: 'kissat', context: 'Kissat nukkuvat.', kind: 'term', mode: 'auto',
  }}, 'an empty translation uses a saved result or translates');
  await settle();
  assert.equal(fresh.win.timers(), 1, 'a new translation is timed');
  assert.equal(fresh.el('codex-options').children.length, 1);

  const known = openCard('мой перевод');
  assert.equal(known.win.requests[0].body.mode, 'stored', 'a filled translation never starts Codex by itself');
  await settle();
  assert.equal(known.win.requests.length, 1, 'nothing saved means no polling');
  assert.equal(known.win.timers(), 0);
  assert.equal(known.el('codex-status').textContent, 'Press ↻ to translate.');
  assert.equal(known.el('codex-skeleton').hidden, true);

  known.el('codex-refresh').handlers.click();
  assert.equal(known.win.requests[1].body.mode, 'refresh', 'the refresh icon always asks Codex again');
  assert.equal(known.el('codex-refresh').disabled, true, 'refresh waits for the running lookup');

  const saved = openCard('мой перевод', {job_id: 'job', saved: true});
  await settle();
  assert.equal(saved.el('codex-timer').textContent, 'saved', 'a saved result is labeled instead of timed');
  assert.equal(saved.win.timers(), 0);
  assert.equal(saved.el('codex-options').children.length, 1, 'a saved result is shown even for a known term');
  assert.equal(saved.el('codex-refresh').disabled, false);
  assert.equal(saved.fields['#translation'].value, 'мой перевод', 'opening a saved result preserves the card');

  const refreshed = openCard('мой перевод', {job_id: 'job', saved: false}, {mode: 'refresh'});
  await settle();
  assert.equal(refreshed.fields['#translation'].value, 'кошки', 'explicit refresh replaces an existing translation');

  let edited;
  edited = openCard('мой перевод', {job_id: 'job', saved: false}, {
    mode: 'refresh', beforePoll: () => { edited.fields['#translation'].value = 'typed while waiting'; },
  });
  await settle();
  assert.equal(edited.fields['#translation'].value, 'typed while waiting', 'refresh preserves edits made during the request');

  const win = makeWindow(async url => url === '/translation/jobs' ? {job_id: 'job', saved: false} : {status: 'complete', result});
  const sentence = new CodexPanel({window: win, languageId: 1, kind: 'sentence'});
  sentence.setLookup('Kissat nukkuvat.', '');
  sentence.start('auto');
  assert.equal(win.requests[0].body.kind, 'sentence');
  await settle();
  assert.equal(win.document.getElementById('codex-options').children[0].tagName, 'DIV', 'sentences cannot be chosen');
  console.log('Codex lookup mode checks passed');
}
checks().catch(error => { console.error(error); process.exitCode = 1; });
