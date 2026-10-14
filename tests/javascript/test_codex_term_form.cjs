// node tests/javascript/test_codex_term_form.cjs
// Codex fills the term form without overwriting the reader's own edits.
const assert = require('node:assert/strict');
const {loadCodex} = require('./fake-dom.cjs');

const {CodexTermForm, termStackOnLoad, pushTermStack, popTermStack, termEditFromChange, bindTermBack, embeddedTermFormSaved, postEmbeddedTermForm} = loadCodex();

function makeContainer() {
  const fields = {
    '#translation': {value: '', dispatchEvent() {}},
    '#text': {value: 'cats'},
    '#language_id': {value: '1'},
    '#parentslist': {_tagify: {value: [], addTags(tags) { this.value.push(...tags); }}},
    '#suggested_parent_text': {value: ''},
    '#suggested_parent_translation': {value: '', dispatchEvent() {}},
    '#suggested_parent_translation_selected': {value: ''},
    '#btnsubmit': {clicks: 0, click() { this.clicks++; }},
    '#codex_phrases': {value: ''},
    '#codex_words': {value: ''},
  };
  return {fields, dataset: {}, querySelector: selector => fields[selector]};
}

const container = makeContainer();
const form = new CodexTermForm(container);
const {fields} = container;
assert.equal(form.text(), 'cats');
assert.equal(form.languageId(), 1);

assert.equal(form.useTranslation('кошки', true), true);
assert.equal(fields['#translation'].value, 'кошки', 'fills an empty field');
fields['#translation'].value = 'my saved translation';
assert.equal(form.useTranslation('коты', true), false);
assert.equal(fields['#translation'].value, 'my saved translation', 'preserves a saved or edited translation');
assert.equal(form.useTranslation('коты', false), true);
assert.equal(fields['#translation'].value, 'коты', 'a deliberate choice replaces the translation');
fields['#translation'].value = ' \n ';
assert.equal(form.useTranslation('кошки', true), true, 'whitespace counts as empty');

const tags = fields['#parentslist']._tagify;
const parent = {text: 'cat', translation: 'кошка', status: 1};
form.useParent(parent);
assert.equal(tags.value[0].value, 'cat', 'adds the base form as a parent');
assert.equal(fields['#suggested_parent_translation'].value, 'кошка', 'stages the dictionary translation');
form.useParent({...parent, translation: 'кот'});
assert.equal(tags.value.length, 1, 'does not duplicate the parent');
assert.equal(fields['#suggested_parent_translation'].value, 'кот');
form.useParent({...parent, existingTranslation: true, translationSelected: true});
assert.equal(fields['#suggested_parent_translation_selected'].value, 'y', 'stages an explicit replacement of a saved parent translation');
form.useParent({...parent, existingTranslation: true});
assert.equal(fields['#suggested_parent_translation_selected'].value, '', 'automatic suggestions keep a saved parent translation');
form.useParent({text: 'Cats', translation: 'кошки'});
assert.equal(tags.value.length, 1, 'the term itself is never its own parent');

tags.value = [];
container.dataset.codexParentsEdited = 'true';
form.useParent(parent);
assert.equal(tags.value.length, 0, 'does not re-add a manually removed parent');
container.dataset.codexParentsEdited = '';
tags.value = [{value: 'feline'}];
fields['#suggested_parent_text'].value = '';
form.useParent(parent);
assert.equal(tags.value[0].value, 'feline', 'preserves existing parents');
assert.equal(fields['#suggested_parent_text'].value, '', 'no suggestion is staged for another parent');

form.usePhrases([{text: 'cats sleep', translation: 'кошки спят'}]);
assert.deepEqual(JSON.parse(fields['#codex_phrases'].value), [{text: 'cats sleep', translation: 'кошки спят'}],
  'checked phrases are posted with the term');
form.useWords([{text: 'cats', translation: 'кошки', lemma: 'cat', is_inflected: true, lemma_translation: 'кошка'}]);
assert.deepEqual(JSON.parse(fields['#codex_words'].value),
  [{text: 'cats', translation: 'кошки', lemma: 'cat', is_inflected: true, lemma_translation: 'кошка'}],
  'checked words are posted with the term');

form.save();
assert.equal(fields['#btnsubmit'].clicks, 1, 'Codex saves through the form button');

function memoryStorage(initial = {}) {
  const data = {...initial};
  return {
    getItem(key) { return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null; },
    setItem(key, value) { data[key] = String(value); },
    removeItem(key) { delete data[key]; },
  };
}

const shown = value => JSON.stringify(value);
const fresh = memoryStorage({'lute-term-stack': '["/read/edit_term/9"]'});
assert.equal(shown(termStackOnLoad(fresh)), '[]', 'opening a term from the text starts a new stack');
const stack = memoryStorage();
pushTermStack(stack, '/read/edit_term/1');
pushTermStack(stack, '/read/termform/1/data%20here');
assert.equal(shown(termStackOnLoad(stack)), '["/read/edit_term/1","/read/termform/1/data%20here"]');
assert.equal(popTermStack(stack), '/read/termform/1/data%20here');
assert.equal(shown(termStackOnLoad(stack)), '["/read/edit_term/1"]', 'back returns one card at a time');
assert.equal(shown(termStackOnLoad(memoryStorage({'lute-term-stack': 'not-json', 'lute-term-drill': '1'}))), '[]');

assert.equal(termEditFromChange({originalEvent: {isTrusted: false}}), false, 'a Codex fill is not an edit');
assert.equal(termEditFromChange({originalEvent: {isTrusted: true}}), true);
assert.equal(termEditFromChange({}), true, 'a reader change without a native event still counts');

let marked = 0;
const noted = makeContainer();
noted.ownerDocument = {defaultView: {markTermFormEdited() { marked++; }}};
new CodexTermForm(noted).noteUserEdit();
assert.equal(marked, 1, 'picking a meaning counts as an edit');

function button() {
  const handlers = {};
  return {
    addEventListener(type, fn) { (handlers[type] ||= []).push(fn); },
    fire(type, event) { (handlers[type] || []).forEach(fn => fn(event)); },
  };
}
let leaves = 0;
const back = button();
bindTermBack(back, () => { leaves++; });
back.fire('click', {});
assert.equal(leaves, 1);
back.fire('pointerup', {pointerType: 'mouse', preventDefault() {}});
back.fire('click', {});
assert.equal(leaves, 2, 'a mouse press uses the click');
let prevented = false;
back.fire('pointerup', {pointerType: 'touch', preventDefault() { prevented = true; }});
back.fire('click', {});
assert.equal(prevented, true, 'the touch is taken before the keyboard can swallow it');
assert.equal(leaves, 3, 'the following click does not leave twice');

assert.equal(embeddedTermFormSaved('<meta name="lute-term-saved" content="1">'), true);
assert.equal(embeddedTermFormSaved('<p>event: "LuteTermFormPosted", keepOpen: true</p>'), false,
  'the form page mentions the event, but it is not a completed save');

(async () => {
  const saved = [];
  const replaced = [];
  const requests = [];
  const deps = {
    fetch: async (url, options) => {
      requests.push({url, method: options.method, body: options.body});
      const html = requests.length === 1
        ? '<meta name="lute-term-saved" content="1">'
        : '<form id="term-form">invalid</form>';
      return {ok: true, text: async () => html};
    },
    formData: () => 'fields',
    notify: () => saved.push('posted'),
    replaceDocument: html => replaced.push(html),
  };
  const form = {action: '/read/edit_term/261'};
  assert.equal(await postEmbeddedTermForm(form, deps), 'saved');
  assert.deepEqual(saved, ['posted'], 'a saved term tells the reading page without navigating');
  assert.deepEqual(requests, [{url: '/read/edit_term/261', method: 'POST', body: 'fields'}]);
  assert.equal(await postEmbeddedTermForm(form, deps), 'invalid');
  assert.equal(replaced.length, 1, 'a validation error stays in the frame');
  assert.equal(saved.length, 1, 'an invalid form does not close the pane');
  console.log('Codex term form checks passed');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
