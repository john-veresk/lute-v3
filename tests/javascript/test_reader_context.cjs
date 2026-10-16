// Repeated sentences must keep their own occurrence when sent from the reader.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('lute/static/js/lute.js', 'utf8');
const start = source.indexOf('function set_lookup_context(el)');
const end = source.indexOf('function show_bulk_term_edit_form', start);
const spans = [
  {id: 1, text: 'Before.'}, {id: 2, text: 'The cats '}, {id: 2, text: 'sleep.'},
  {id: 3, text: 'Middle.'}, {id: 4, text: 'The cats '}, {id: 4, text: 'sleep.'},
  {text: '\u200b'},
];
const context = vm.createContext({
  window: {},
  $: value => typeof value === 'string' ? {toArray: () => spans} : {data: () => value.id},
  _get_textitems_text: items => items.map(item => item.text).join(''),
});
vm.runInContext(source.slice(start, end), context);
context.set_lookup_context({data: () => 4});
assert.equal(context.window.LUTE_LOOKUP_CONTEXT, 'The cats sleep.');
assert.equal(context.window.LUTE_LOOKUP_SENTENCE_INDEX, 3);
context.set_lookup_context({data: () => 2});
assert.equal(context.window.LUTE_LOOKUP_CONTEXT, 'The cats sleep.');
assert.equal(context.window.LUTE_LOOKUP_SENTENCE_INDEX, 1);
console.log('Reader context checks passed');
