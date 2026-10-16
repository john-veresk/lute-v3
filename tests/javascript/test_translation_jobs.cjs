// node tests/javascript/test_translation_jobs.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const timers = [];
function element() {
  return {dataset: {}, children: [], append(child) { this.children.push(child); }};
}
const context = vm.createContext({
  document: {activeElement: null, createElement: element},
  setTimeout: callback => { timers.push(callback); return timers.length; },
  clearTimeout() {},
});
const source = fs.readFileSync('lute/static/js/translation-jobs.js', 'utf8');
vm.runInContext(source.replace(/\nnew TranslationJobManager\([\s\S]*$/, ''), context);
const Manager = vm.runInContext('TranslationJobManager', context);

function fixture() {
  const manager = Object.create(Manager.prototype);
  const controls = {
    'jobs-search': {value: ''}, 'jobs-loading': {hidden: false},
    'jobs-books': {querySelectorAll: () => []},
  };
  Object.assign(manager, {
    state: {books: [], jobs: []}, selected: new Set(), startPages: new Map(),
    selectedTags: new Set(), busy: false, refreshing: false, bookSignature: '',
    find: id => controls[id], error(message = '') { this.lastError = message; },
    renderBooks() {}, renderJobs() {}, renderTags() {}, renderSelection() {}, updateButtons() {},
  });
  return {manager, controls};
}

(async () => {
  const {manager, controls} = fixture();
  manager.state.books = [
    {id: 1, title: 'Suomen mestari', language: 'Finnish', tags: ['study'], start_page: 5},
    {id: 2, title: 'News', language: 'Finnish', tags: ['news'], start_page: 2},
    {id: 3, title: 'A book', language: 'English', tags: ['study'], start_page: 1},
  ];
  controls['jobs-search'].value = 'FINNISH';
  manager.selectedTags.add('study');
  assert.deepEqual(manager.visibleBooks().map(book => book.id), [1], 'search and tags work together');
  manager.selectedTags.add('news');
  assert.deepEqual(manager.visibleBooks().map(book => book.id), [1, 2], 'multiple tags use OR');
  manager.selectedTags.clear();
  controls['jobs-search'].value = '';
  assert.equal(manager.visibleBooks().length, 3);

  manager.selected.add(1);
  manager.selected.add(2);
  manager.startPages.set(2, 1);
  let submission;
  manager.command = (url, body) => { submission = {url, body}; };
  manager.addBooks();
  assert.equal(submission.url, '/jobs');
  assert.equal(JSON.stringify(submission.body), JSON.stringify({book_ids: [1, 2], start_pages: {1: 5, 2: 1}}));
  controls['jobs-books'].querySelectorAll = () => [{dataset: {startPage: '1'}, reportValidity: () => false}];
  submission = null;
  manager.addBooks();
  assert.equal(submission, null, 'invalid pages are rejected before submission');

  const locked = fixture().manager;
  let finish;
  let calls = 0;
  locked.selected.add(1);
  locked.request = () => { calls++; return new Promise(resolve => { finish = resolve; }); };
  locked.refresh = async () => {};
  const command = locked.command('/jobs');
  await locked.command('/jobs');
  assert.equal(calls, 1, 'double clicks cannot submit twice');
  finish({});
  await command;
  assert.equal(locked.busy, false);
  assert.equal(locked.selected.size, 0);

  const editor = fixture().manager;
  const editorControls = {};
  for (const name of ['title', 'cli', 'model', 'effort', 'error', 'effort-row', 'help', 'save', 'cancel']) editorControls[`job-settings-${name}`] = {};
  editorControls['job-settings-models'] = {children: [], replaceChildren() { this.children = []; }, append(item) { this.children.push(item); }};
  editorControls['job-settings-form'] = {reportValidity: () => true};
  editorControls['job-settings-dialog'] = {open: false, showModal() { this.open = true; }, close() { this.open = false; }};
  editor.find = id => editorControls[id];
  editor.modelOptions = {cursor: ['cursor-grok-4.6-medium'], codex: ['codex-model']};
  editor.state.jobs = [{id: 8, title: '<book>', status: 'paused', settings: {cli: 'cursor', model: 'cursor-grok-4.6-medium', effort: ''}}];
  editor.editSettings(8);
  assert.equal(editorControls['job-settings-dialog'].open, true);
  assert.equal(editorControls['job-settings-title'].textContent, 'Job 8 · <book>');
  assert.equal(editorControls['job-settings-model'].value, 'cursor-grok-4.6-medium');
  assert.equal(editorControls['job-settings-effort-row'].hidden, true);
  assert.equal(editorControls['job-settings-models'].children[0].value, 'cursor-grok-4.6-medium');
  editorControls['job-settings-model'].value = 'another-model';
  let patch;
  editor.request = async (url, body, method) => { patch = {url, body, method}; return {}; };
  editor.refresh = async () => {};
  await editor.saveSettings();
  assert.equal(patch.url, '/jobs/8/settings');
  assert.equal(patch.method, 'PATCH');
  assert.equal(JSON.stringify(patch.body), JSON.stringify({cli: 'cursor', model: 'another-model', effort: ''}));
  assert.equal(editorControls['job-settings-dialog'].open, false);
  assert.equal(editorControls['job-settings-save'].disabled, false);
  assert.equal(editorControls['job-settings-effort'].disabled, true);
  editor.editSettings(8);
  editor.request = async () => { throw new Error('Cannot save'); };
  await editor.saveSettings();
  assert.equal(editorControls['job-settings-dialog'].open, true, 'failed saves keep the editor and draft open');
  assert.equal(editorControls['job-settings-error'].textContent, 'Cannot save');
  assert.equal(editor.busy, false);

  // Late suggestions for the previous harness must not replace current choices.
  editor.modelOptions = {};
  let resolveCursor;
  editor.request = url => url.endsWith('cursor')
    ? new Promise(resolve => { resolveCursor = resolve; })
    : Promise.resolve({models: ['codex-model']});
  editor.editorCli = 'cursor';
  const cursorSuggestions = editor.configureEditor();
  editor.editorCli = 'codex';
  await editor.configureEditor();
  resolveCursor({models: ['cursor-model']});
  await cursorSuggestions;
  assert.equal(editorControls['job-settings-models'].children[0].value, 'codex-model');

  const polling = fixture().manager;
  let respond;
  polling.request = () => new Promise(resolve => { respond = resolve; });
  const refresh = polling.refresh();
  await polling.refresh();
  assert.equal(timers.length, 0, 'overlapping refreshes do not create extra timers');
  respond({books: [], jobs: []});
  await refresh;
  assert.equal(timers.length, 1, 'a manual refresh always leaves polling scheduled');
  polling.request = async () => { throw new Error('Offline'); };
  await polling.refresh();
  assert(polling.lastError.includes('Reconnecting'));
  assert.equal(timers.length, 2, 'connection failures keep polling');
  polling.request = async () => ({books: [], jobs: []});
  await polling.refresh();
  assert.equal(polling.lastError, '', 'successful reconnection clears the connection error');

  const timing = fixture().manager;
  assert.equal(timing.duration(null), '—');
  assert.equal(timing.duration(12.34), '12.3 s');
  assert.equal(timing.duration(90), '1 min 30 s');
  assert.equal(timing.duration(3660), '1 h 1 min');
  assert(timing.timingSummary({status: 'paused', average_word_seconds: null, eta_seconds: null}).includes('no measured translations yet'));
  const measured = {id: 8, status: 'paused', settings: {}, average_word_seconds: 10,
    timed_word_count: 1, eta_seconds: 20, current_word_elapsed_seconds: null,
    word_timings: [{word: '<word>', page: 7, duration_seconds: 10, attempts: 2, status: 'translated'}]};
  assert(timing.timingSummary(measured).includes('Average per word: 10.0 s (1 measured)'));
  assert(timing.timingSummary(measured).includes('ETA after resume: 20.0 s'));
  assert(timing.timingSummary({...measured, status: 'running', current_word_elapsed_seconds: 3}).includes('Current word: 3.0 s'));
  const list = {cards: [], replaceChildren() { this.cards = []; }, append(card) { this.cards.push(card); },
    querySelectorAll: () => [{dataset: {field: 'word-timing-details'}, closest: () => ({dataset: {jobId: '8'}})}]};
  const jobControls = {'jobs-list': list, 'jobs-summary': {}, 'jobs-empty': {},
    'job-card-template': {content: {firstElementChild: {cloneNode() {
      const fields = {};
      const details = [element(), Object.assign(element(), {dataset: {field: 'word-timing-details'}})];
      return {dataset: {}, fields, details,
        querySelector(selector) { return fields[selector] ||= element(); },
        querySelectorAll: selector => selector === 'details' ? details : []};
    }}}}};
  timing.find = id => jobControls[id];
  timing.state.jobs = [measured, {status: 'cancelled'}];
  Manager.prototype.renderJobs.call(timing);
  assert.equal(list.cards.length, 1, 'cancelled jobs stay hidden');
  assert.equal(list.cards[0].details[0].open, false);
  assert.equal(list.cards[0].details[1].open, true, 'word timings stay expanded after polling');
  const rows = list.cards[0].fields['[data-field="word-timings"]'].children;
  assert.deepEqual(rows[0].children.map(cell => cell.textContent), ['<word>', 7, '10.0 s', 2, 'Translated']);
  timing.state.jobs = [{status: 'cancelled'}];
  Manager.prototype.renderJobs.call(timing);
  assert.equal(list.cards.length, 0);
  assert.equal(jobControls['jobs-empty'].hidden, false);
  console.log('Translation jobs UI checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
