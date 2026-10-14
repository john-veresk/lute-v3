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

  useParent(parent) { applyCodexParent(this.container, parent); }

  /** Checked phrase cards are created when the term is saved. */
  usePhrases(phrases) { this.field('#codex_phrases').value = JSON.stringify(phrases); }

  /** Checked word cards are created when the term is saved. */
  useWords(words) { this.field('#codex_words').value = JSON.stringify(words); }

  save() { this.field('#btnsubmit').click(); }
}

/**
 * Show Codex in the term card.  A saved translation is shown without a new
 * request; an empty Translation is translated automatically.
 */
function startTermCodex(window, context) {
  const form = new CodexTermForm(window.document.getElementById('term-form-container'));
  const panel = new CodexPanel({
    window, form,
    onCardsSaved: () => window.parent.postMessage({event: 'LuteCodexWordsSaved'}, window.location.origin),
  });
  panel.setLookup(form.text(), context);
  panel.start(form.translation().trim() ? 'stored' : 'auto');
  return panel;
}
