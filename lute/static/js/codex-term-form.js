"use strict";

/** Stage the Codex base form as the term's parent, keeping the reader's own edits. */
function applyCodexParent(container, parent) {
  if (!parent || typeof parent.text !== 'string' || typeof parent.translation !== 'string') return;
  const tagify = container.querySelector('#parentslist')?._tagify || container.ownerDocument?.defaultView?.parents_tagify;
  if (!tagify || container.dataset.codexParentsEdited === 'true') return;
  const clean = value => value.replaceAll('\u200b', '').trim().toLocaleLowerCase();
  if (clean(parent.text) === clean(container.querySelector('#text').value)) return;
  if (tagify.value.length === 0) {
    tagify.addTags([{value: parent.text, status: parent.status, codexSuggested: true}]);
  }
  if (tagify.value.length !== 1 || clean(tagify.value[0].value) !== clean(parent.text)) return;
  container.querySelector('#suggested_parent_text').value = parent.text;
  const translationField = container.querySelector('#suggested_parent_translation');
  translationField.value = parent.translation;
  container.querySelector('#suggested_parent_translation_selected').value = parent.translationSelected === true ? 'y' : '';
  translationField.dispatchEvent(new Event('change', {bubbles: true}));
}

const TERM_STACK_KEY = 'lute-term-stack';
const TERM_DRILL_KEY = 'lute-term-drill';

/** Cards opened from the reading text start fresh. A drill-down keeps the return path. */
function readTermStack(storage) {
  try {
    const value = JSON.parse(storage.getItem(TERM_STACK_KEY) || '[]');
    return Array.isArray(value) ? value.filter(item => typeof item === 'string' && item.startsWith('/')) : [];
  } catch (error) {
    return [];
  }
}

function termStackOnLoad(storage) {
  const drilling = storage.getItem(TERM_DRILL_KEY) === '1';
  storage.removeItem(TERM_DRILL_KEY);
  if (!drilling) {
    storage.removeItem(TERM_STACK_KEY);
    return [];
  }
  return readTermStack(storage);
}

function pushTermStack(storage, url) {
  const stack = readTermStack(storage);
  stack.push(url);
  if (stack.length > 20) stack.shift();
  storage.setItem(TERM_STACK_KEY, JSON.stringify(stack));
  storage.setItem(TERM_DRILL_KEY, '1');
}

function popTermStack(storage) {
  const stack = readTermStack(storage);
  const previous = stack.pop() || '';
  storage.setItem(TERM_STACK_KEY, JSON.stringify(stack));
  if (previous) storage.setItem(TERM_DRILL_KEY, '1');
  return previous;
}

/** Codex writes fields with script-dispatched events. Those are not reader edits. */
function termEditFromChange(event) {
  const native = event?.originalEvent;
  return !(native && native.isTrusted === false);
}

/**
 * A touch on Back has to run on pointerup. While the term field is focused,
 * the phone uses the first click only to dismiss the keyboard.
 */
function bindTermBack(button, leave) {
  let fromTouch = false;
  button.addEventListener('pointerup', event => {
    if (event.pointerType === 'mouse') return;
    event.preventDefault();
    fromTouch = true;
    leave();
  });
  button.addEventListener('click', () => {
    if (fromTouch) {
      fromTouch = false;
      return;
    }
    leave();
  });
}

/** The term form fields that Codex reads and fills. */
class CodexTermForm {
  constructor(container) { this.container = container; }

  field(selector) { return this.container.querySelector(selector); }

  text() { return this.field('#text').value; }

  languageId() { return Number(this.field('#language_id').value); }

  translation() { return this.field('#translation').value; }

  /** An automatic choice only fills an empty Translation. */
  useTranslation(value, automatic) {
    const translation = this.field('#translation');
    if (automatic && translation.value.trim()) return false;
    translation.value = value;
    translation.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }

  /** A meaning the reader picked, as opposed to an automatic fill. */
  noteUserEdit() {
    this.container.ownerDocument?.defaultView?.markTermFormEdited?.();
  }

  useParent(parent) { applyCodexParent(this.container, parent); }

  /** Checked phrase cards are created when the term is saved. */
  usePhrases(phrases) { this.field('#codex_phrases').value = JSON.stringify(phrases); }

  /** Checked word cards are created when the term is saved. */
  useWords(words) { this.field('#codex_words').value = JSON.stringify(words); }

  save() { this.field('#btnsubmit').click(); }
}

/** The reading-pane success page is the only response with this marker. */
function embeddedTermFormSaved(html) {
  return typeof html === 'string' && html.includes('name="lute-term-saved"');
}

/**
 * Post the term form without navigating the frame.
 * A normal submit adds a Back step, and closing the phone pane then
 * presses Back while that frame is reloading, which freezes mobile Safari.
 */
async function postEmbeddedTermForm(form, {fetch, formData, notify, replaceDocument}) {
  const response = await fetch(form.action, {method: 'POST', body: formData(form)});
  const html = await response.text();
  if (!response.ok) throw new Error('Save failed');
  if (embeddedTermFormSaved(html)) {
    notify();
    return 'saved';
  }
  replaceDocument(html);
  return 'invalid';
}

/**
 * Show Codex in the term card.  A saved translation is shown without a new
 * request; an empty Translation is translated automatically.
 */
function startTermCodex(window, context, {embedded = false, openWord = null, bookId = null, pageNum = null, sentenceIndex = null} = {}) {
  const form = new CodexTermForm(window.document.getElementById('term-form-container'));
  const panel = new CodexPanel({
    window, form, embedded, openWord, bookId, pageNum, sentenceIndex,
    onCardsSaved: () => window.parent.postMessage({event: 'LuteCodexWordsSaved'}, window.location.origin),
  });
  panel.setLookup(form.text(), context);
  panel.start(form.translation().trim() ? 'stored' : 'auto');
  return panel;
}
