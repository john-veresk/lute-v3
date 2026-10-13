// Regression checks for late iframe responses and preservation of user edits.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const handlers = [];
const translation = {value: '', dispatchEvent() {}};
const text = {value: 'kissa'};
const language = {value: '1'};
const parentTags = {value: [], addTags(tags) {this.value.push(...tags);}};
const parents = {_tagify: parentTags};
const suggestedParent = {value: ''};
const suggestedTranslation = {value: '', dispatchEvent() {}};
const source = {postMessage() {}};
const container = {dataset: {}, querySelector(selector) {
  return {'#translation': translation, '#text': text, '#language_id': language,
    '#parentslist': parents, '#suggested_parent_text': suggestedParent,
    '#suggested_parent_translation': suggestedTranslation}[selector];
}};
const context = vm.createContext({
  window: {location: {origin: 'http://localhost:5001'}, addEventListener(type, fn) {handlers.push(fn);}},
  document: {getElementById() {return null;}},
  Event: class Event {},
  container, source,
});
vm.runInContext(fs.readFileSync('lute/static/js/dict-tabs.js', 'utf8'), context);
vm.runInContext(`
  const button = Object.create(CodexButton.prototype);
  button.frame = {contentWindow: source};
  button.lookupText = 'kissa';
  button.lookupLanguage = 1;
  button.lookupId = 'current';
  LookupButton.all = [button];
  LookupButton.TERM_FORM_CONTAINER = container;
`, context);
function send(changes = {}, origin = 'http://localhost:5001', from = source) {
  handlers[0]({origin, source: from, data: {
    event: 'LuteCodexTranslation', request_id: 'current', text: 'kissa',
    language_id: 1, translation: 'кошка', automatic: true, index: 0,
    ...changes,
  }});
}
send();
assert.equal(translation.value, 'кошка', 'fills an empty field');
translation.value = 'my saved translation';
send();
assert.equal(translation.value, 'my saved translation', 'preserves a saved or edited translation');
send({automatic: false, translation: 'кот'});
assert.equal(translation.value, 'кот', 'a deliberate selection replaces the translation');
translation.value = '';
send({request_id: 'previous'});
send({text: 'another word'});
send({language_id: 2});
send({}, 'https://untrusted.example');
send({}, 'http://localhost:5001', {});
assert.equal(translation.value, '', 'ignores stale, unrelated and cross-origin responses');
text.value = 'new word';
send();
assert.equal(translation.value, '', 'ignores a response after the term text changes');
text.value = 'cats';
vm.runInContext("button.lookupText = 'cats'", context);
translation.value = 'my saved translation';
const parent = {text: 'cat', translation: 'кошка', status: 1};
send({text: 'cats', parent});
assert.equal(translation.value, 'my saved translation', 'can add a parent without overwriting a saved child translation');
assert.equal(parentTags.value[0].value, 'cat', 'automatically adds the base form');
assert.equal(suggestedTranslation.value, 'кошка', 'stages the separate dictionary translation');
send({text: 'cats', parent: {...parent, translation: 'кот'}});
assert.equal(parentTags.value.length, 1, 'does not duplicate the parent');
assert.equal(suggestedTranslation.value, 'кот', 'stages edits to the suggested dictionary meaning');
parentTags.value = [];
container.dataset.codexParentsEdited = 'true';
send({text: 'cats', parent});
assert.equal(parentTags.value.length, 0, 'does not re-add a manually removed parent');
container.dataset.codexParentsEdited = '';
parentTags.value = [{value: 'feline'}];
send({text: 'cats', parent});
assert.equal(parentTags.value[0].value, 'feline', 'preserves existing parents');
console.log('Codex iframe regression checks passed');
