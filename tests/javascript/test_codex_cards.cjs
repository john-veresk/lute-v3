// node tests/javascript/test_codex_cards.cjs
// Meanings, optional phrase and word cards, and shortcuts in the term card.
const assert = require('node:assert/strict');
const {makeWindow, loadCodex, settle} = require('./fake-dom.cjs');

const {CodexPanel} = loadCodex();
const phrases = [
  {text: 'looked after', translation: 'присматривал за'},
  {text: 'looked after the cats', translation: 'присматривал за кошками'},
];

function makeForm(text = 'looked') {
  return {
    saves: 0, translation: '', choices: [], phrases: null, words: null,
    usePhrases(phrases) { this.phrases = JSON.parse(JSON.stringify(phrases)); },
    useWords(words) { this.words = JSON.parse(JSON.stringify(words)); },
    text: () => text,
    languageId: () => 1,
    useTranslation(value, automatic) {
      this.choices.push({value, automatic});
      if (automatic && this.translation) return false;
      this.translation = value;
      return true;
    },
    useParent() {},
    save() { this.saves++; },
  };
}

function makePanel({words = [], phraseCards = phrases, saveResponse, form = makeForm(), embedded = false, openWord = null} = {}) {
  const win = makeWindow(async (url, body) => {
    if (url === '/translation/jobs') return {job_id: 'job', saved: false};
    if (url === '/translation/jobs/job') return {
      status: 'complete',
      result: {lemma: '', is_inflected: false, options: [{translation: 'смотрел', explanation: ''}], words, phrases: phraseCards},
    };
    if (saveResponse) return saveResponse();
    const cards = url === '/translation/phrases' ? phraseCards : words;
    return {saved: body.indices.map(index => ({index, ...cards[index]}))};
  });
  let cardsSaved = 0;
  const panel = new CodexPanel({window: win, form, embedded, openWord, onCardsSaved: () => { cardsSaved++; }});
  panel.setLookup('looked', 'He looked after the cats.');
  panel.start('auto');
  return {win, panel, form, el: id => win.document.getElementById(id), cardsSaved: () => cardsSaved};
}

async function checks() {
  const card = makePanel();
  await settle();
  assert.equal(card.el('codex-phrases').hidden, false);
  assert.equal(card.el('codex-words').hidden, true);
  const rows = card.el('codex-phrase-cards').children;
  assert.equal(rows.length, 2);
  assert.equal(rows[0].children[1].children[0].textContent, 'looked after');
  assert.equal(rows[0].children[1].children[1].textContent, 'присматривал за');
  assert.equal(rows[0].children[0].checked, false, 'context phrases start unchecked');
  assert.equal(card.win.requests.length, 2, 'rendering suggestions does not save cards');
  assert.deepEqual(card.form.choices, [{value: 'смотрел', automatic: true}], 'the best meaning fills the form');

  await rows[0].children[2].handlers.click();
  assert.deepEqual(card.win.requests[2], {
    url: '/translation/phrases', body: {language_id: 1, job_id: 'job', indices: [0]},
  });
  assert.equal(rows[0].children[2].textContent, 'Saved');
  assert.equal(rows[0].children[2].disabled, true);
  assert.equal(rows[0].children[0].disabled, true);
  assert.equal(card.cardsSaved(), 1, 'saving refreshes reading highlights');
  assert.equal(card.form.choices.length, 1, 'saving a phrase leaves the word form alone');

  assert.deepEqual(card.form.phrases, [], 'no phrase is saved with the card until checked');
  rows[1].children[0].checked = true;
  rows[1].children[0].handlers.change();
  assert.deepEqual(card.form.phrases, [phrases[1]], 'a checked phrase is saved with the card');
  rows[0].children[0].checked = true;
  rows[0].children[0].handlers.change();
  assert.deepEqual(card.form.phrases, [phrases[1]], 'a phrase saved with Add is not saved again');
  card.el('codex-refresh').handlers.click();
  assert.deepEqual(card.form.phrases, [], 'a new lookup clears the checked phrases');
  assert.deepEqual(card.form.words, [], 'a new lookup clears the checked words');
  await settle();

  const empty = makePanel({phraseCards: []});
  await settle();
  assert.equal(empty.el('codex-phrases').hidden, true);

  const wordPanel = makePanel({phraseCards: [], words: [{text: 'cats', translation: 'кошки', is_inflected: true, lemma: 'cat', lemma_translation: 'кошка'}]});
  await settle();
  const wordRow = wordPanel.el('codex-word-cards').children[0];
  const word = {text: 'cats', translation: 'кошки', lemma: 'cat', is_inflected: true, lemma_translation: 'кошка'};
  assert.equal(wordRow.children[0].checked, false, 'words start unchecked');
  assert.deepEqual(wordPanel.form.words, [], 'no word is saved with the card until checked');
  assert.equal(wordRow.children[1].children[2].textContent, 'Parent: cat — кошка');
  wordRow.children[0].checked = true;
  wordRow.children[0].handlers.change();
  assert.deepEqual(wordPanel.form.words, [word], 'a checked word is saved with the card');
  await wordRow.children[2].handlers.click();
  assert.equal(wordPanel.win.requests[2].url, '/translation/words');
  assert.equal(wordRow.children[0].checked, true, 'an added word stays checked');
  assert.equal(wordRow.children[0].disabled, true, 'an added word cannot be selected again');
  assert.equal(wordRow.children[2].textContent, 'Saved');
  assert.equal(wordRow.children[2].disabled, true);
  assert.deepEqual(wordPanel.form.words, [], 'a word saved with Add is not saved again');

  const known = makePanel({phraseCards: [], words: [{...word, saved: true}]});
  await settle();
  const knownRow = known.el('codex-word-cards').children[0];
  assert.equal(knownRow.children[0].checked, true, 'a word already in the vocabulary starts checked');
  assert.equal(knownRow.children[0].disabled, true, 'a saved word cannot be clicked');
  assert.equal(knownRow.children[2].textContent, 'Saved');
  assert.equal(knownRow.children[2].disabled, true);
  assert.deepEqual(known.form.words, [], 'a saved word is not posted again');
  assert.equal(knownRow.children[1].children[0].getAttribute('href'), '/term/editbytext/1/cats', 'a saved word opens its card');

  let opened = '';
  let prevented = false;
  const reading = makePanel({
    phraseCards: [], embedded: true, openWord: url => { opened = url; },
    words: [{text: 'a/b', translation: 'дробь'}],
  });
  await settle();
  const readingRow = reading.el('codex-word-cards').children[0];
  const wordLink = readingRow.children[1].children[0];
  assert.equal(wordLink.getAttribute('href'), '/read/termform/1/aLUTESLASHb');
  wordLink.handlers.click({preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(opened, '/read/termform/1/aLUTESLASHb', 'the word opens in the reading pane');
  assert.equal(readingRow.children[0].checked, false, 'opening a word does not select it for saving');
  assert.equal(card.el('codex-phrase-cards').children[0].children[1].children[0].tagName, 'STRONG', 'a phrase name stays plain text');

  const failed = makePanel({saveResponse: async () => ({ok: false, json: async () => ({error: 'Translation expired. Translate again.'})})});
  await settle();
  const failedRow = failed.el('codex-phrase-cards').children[0];
  await failedRow.children[2].handlers.click();
  assert.equal(failed.el('codex-phrases-status').textContent, 'Translation expired. Translate again.');
  assert.equal(failedRow.children[2].disabled, false, 'failed saves can be retried');
  assert.equal(failedRow.children[2].textContent, 'Add');
  assert.equal(failed.cardsSaved(), 0);

  let releaseSave;
  const stale = makePanel({saveResponse: () => new Promise(resolve => { releaseSave = resolve; })});
  await settle();
  const pendingSave = stale.el('codex-phrase-cards').children[0].children[2].handlers.click();
  stale.el('codex-refresh').handlers.click();
  await settle();
  const newRow = stale.el('codex-phrase-cards').children[0];
  releaseSave({ok: true, json: async () => ({saved: [{index: 0, ...phrases[0]}]})});
  await pendingSave;
  assert.equal(newRow.children[2].textContent, 'Add', 'a late save cannot change a newer lookup');
  assert.equal(stale.cardsSaved(), 0);

  const quick = makePanel();
  await settle();
  assert.deepEqual(['codex-context-before', 'codex-context-word', 'codex-context-after'].map(id => quick.el(id).textContent),
    ['He ', 'looked', ' after the cats.'], 'the selected word is marked in its sentence');
  const press = (key, target = {closest: () => null}) => {
    let prevented = false;
    quick.win.dispatch('keydown', {key, target, preventDefault() { prevented = true; }});
    return prevented;
  };
  assert.equal(press('1'), true);
  assert.deepEqual(quick.form.choices.at(-1), {value: 'смотрел', automatic: false}, 'number keys choose a meaning deliberately');
  assert.equal(press('9'), false, 'missing meanings are ignored');
  press('Enter');
  assert.equal(quick.form.saves, 1, 'Enter saves the card');
  press('1', {closest: () => ({})});
  assert.equal(quick.form.choices.length, 2, 'typing in a field is not a shortcut');
  quick.el('codex-options').children[0].handlers.dblclick();
  assert.equal(quick.form.saves, 2, 'double-click chooses and saves');
  assert.equal(quick.form.choices.length, 3);
  assert.equal(quick.el('codex-options').children[0].classList.contains('selected'), true);

  const edited = makePanel({form: makeForm()});
  await settle();
  edited.form.text = () => 'looked after';
  edited.el('codex-options').children[0].handlers.click();
  assert.equal(edited.form.choices.length, 1, 'a meaning is not applied after the term text changes');
  console.log('Codex card checks passed');
}
checks().catch(error => { console.error(error); process.exitCode = 1; });
