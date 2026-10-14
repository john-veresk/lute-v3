"use strict";

const withoutZeroWidth = value => value.replaceAll('\u200b', '');

/** Split the sentence around the first case-insensitive match of the term. */
function splitContext(sentence, term) {
  const plain = withoutZeroWidth(sentence);
  const target = withoutZeroWidth(term).trim();
  const index = target ? plain.toLocaleLowerCase().indexOf(target.toLocaleLowerCase()) : -1;
  if (index < 0) return [plain, '', ''];
  return [plain.slice(0, index), plain.slice(index, index + target.length), plain.slice(index + target.length)];
}

async function readResponse(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Translation failed. Try again.');
  return data;
}

/** Elapsed request time, shown beside the model when the language enables it. */
class CodexTimer {
  constructor(element, win) {
    this.element = element;
    this.win = win;
    this.interval = null;
    this.started = 0;
  }

  update() {
    this.element.textContent = `${((this.win.performance.now() - this.started) / 1000).toFixed(1)} s`;
  }

  start() {
    if (!this.element) return;
    this.win.clearInterval(this.interval);
    this.started = this.win.performance.now();
    this.update();
    this.interval = this.win.setInterval(() => this.update(), 100);
  }

  stop() {
    if (this.interval === null) return;
    this.update();
    this.win.clearInterval(this.interval);
    this.interval = null;
  }

  show(label) {
    if (!this.element) return;
    this.win.clearInterval(this.interval);
    this.interval = null;
    this.element.textContent = label;
  }
}

/**
 * Codex meanings, base form and optional word and phrase cards.
 *
 * Term lookups are connected to the term form through `form`;
 * sentence lookups only show the translation.
 */
class CodexPanel {
  constructor({window, languageId, kind = 'term', form = null, onCardsSaved = () => {}}) {
    this.win = window;
    this.doc = window.document;
    this.languageId = languageId;
    this.kind = kind;
    this.form = form;
    this.onCardsSaved = onCardsSaved;
    this.text = '';
    this.context = '';
    this.generation = 0;
    this.lastMode = 'auto';
    this.options = [];
    this.parentSuggestion = null;
    this.cardRows = {words: [], phrases: []};
    this.timer = new CodexTimer(this.element('codex-timer'), window);
    this.element('codex-refresh')?.addEventListener('click', () => this.start('refresh'));
    this.element('codex-retry').addEventListener('click', () => this.start(this.lastMode));
    window.addEventListener('pagehide', () => { this.generation++; this.timer.stop(); });
    if (form) window.addEventListener('keydown', event => this.onKey(event));
  }

  element(id) { return this.doc.getElementById(id); }

  setLookup(text, context) {
    this.text = text;
    this.context = context;
    const heading = this.element('codex-text');
    if (heading) heading.textContent = withoutZeroWidth(text);
    const parts = splitContext(context, text);
    ['before', 'word', 'after'].forEach((name, index) => {
      this.element(`codex-context-${name}`).textContent = parts[index];
    });
    this.element('codex-context').hidden = !context;
  }

  setBusy(busy) {
    this.element('codex-skeleton').hidden = !busy;
    const refresh = this.element('codex-refresh');
    if (!refresh) return;
    refresh.disabled = busy;
    refresh.classList.toggle('busy', busy);
  }

  reset() {
    this.element('codex-options').replaceChildren();
    this.element('codex-lemma').textContent = '';
    this.element('codex-retry').hidden = true;
    this.element('codex-status').textContent = '';
    this.options = [];
    this.selectedIndex = null;
    this.parentSuggestion = null;
    this.cardRows = {words: [], phrases: []};
    if (!this.form) return;
    this.form.usePhrases([]);
    this.form.useWords([]);
    this.element('codex-parent-options').replaceChildren();
    this.element('codex-parent').hidden = true;
    this.element('codex-parent').open = false;
    ['words', 'phrases'].forEach(type => { this.element(`codex-${type}`).hidden = true; });
  }

  /** mode: auto, stored or refresh (see LOOKUP_MODES in translation/routes.py). */
  async start(mode) {
    if (this.form) {
      this.text = this.form.text();
      this.languageId = this.form.languageId();
    }
    if (!withoutZeroWidth(this.text).trim() || !this.languageId) return;
    const current = ++this.generation;
    this.lastMode = mode;
    this.reset();
    this.setBusy(mode !== 'stored');
    try {
      const job = await this.submit(mode);
      if (current !== this.generation) return;
      if (!job.job_id) {
        this.element('codex-status').textContent = 'Press ↻ to translate with Codex.';
        return;
      }
      this.setBusy(true);
      if (job.saved) this.timer.show('saved');
      else this.timer.start();
      const result = await this.poll(job.job_id, current);
      if (current !== this.generation) return;
      await this.render(result, job.job_id, current);
    } catch (error) {
      if (current !== this.generation) return;
      this.element('codex-status').textContent = error.message;
      this.element('codex-retry').hidden = false;
    } finally {
      if (current === this.generation) {
        this.setBusy(false);
        this.timer.stop();
      }
    }
  }

  async submit(mode) {
    return readResponse(await this.win.fetch('/translation/jobs', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({language_id: this.languageId, text: this.text, context: this.context, kind: this.kind, mode}),
    }));
  }

  async poll(jobId, current) {
    const deadline = Date.now() + 8 * 90 * 1000;
    while (current === this.generation) {
      const data = await readResponse(await this.win.fetch(`/translation/jobs/${jobId}`));
      if (data.status === 'error') throw new Error(data.error);
      if (data.status === 'complete') return data.result;
      if (Date.now() > deadline) throw new Error('Translation timed out. Try again.');
      await new Promise(resolve => this.win.setTimeout(resolve, 700));
    }
    return null;
  }

  async render(result, jobId, current) {
    const clean = value => withoutZeroWidth(value).trim().toLocaleLowerCase();
    const isNewLemma = result.lemma && clean(result.lemma) !== clean(this.text);
    this.element('codex-lemma').textContent = isNewLemma ? result.lemma : '';
    if (this.form && result.is_inflected && isNewLemma) await this.renderParent(result, current);
    if (current !== this.generation) return;
    this.options = result.options;
    result.options.forEach((option, index) => this.element('codex-options').appendChild(this.renderOption(option, index)));
    if (!this.form) return;
    this.renderCards(result.words || [], jobId, current, 'words');
    this.renderCards(result.phrases || [], jobId, current, 'phrases');
    this.choose(0, true);
  }

  async renderParent(result, current) {
    try {
      const query = new URLSearchParams({language_id: this.languageId, text: result.lemma});
      const existing = await readResponse(await this.win.fetch(`/translation/parent?${query}`));
      if (current !== this.generation) return;
      this.parentSuggestion = {
        text: result.lemma,
        status: existing.status,
        existingTranslation: !!existing.translation.trim(),
        translation: existing.translation.trim() ? existing.translation : result.lemma_translation,
      };
      this.element('codex-parent-text').textContent = result.lemma;
      this.renderParentOptions(result.lemma_options || [{translation: result.lemma_translation, explanation: ''}], existing.translation);
      this.element('codex-parent').hidden = false;
    } catch (error) {
      this.element('codex-lemma').textContent += ' (base form lookup failed; add it in Parents)';
    }
  }

  renderParentOptions(choices, existingTranslation) {
    const cards = [...choices];
    if (existingTranslation.trim() && !cards.some(option => option.translation === existingTranslation)) {
      cards.unshift({translation: existingTranslation, explanation: 'Saved in your vocabulary.'});
    }
    cards.forEach(option => {
      const card = this.optionElement('button', option);
      card.type = 'button';
      card.title = 'Use this meaning for the base form';
      card.dataset.translation = option.translation;
      card.addEventListener('click', () => {
        this.parentSuggestion.translation = option.translation;
        this.parentSuggestion.translationSelected = true;
        this.updateParentSelection();
        if (this.options.length) this.choose(this.selectedIndex ?? 0, true);
      });
      this.element('codex-parent-options').appendChild(card);
    });
    this.updateParentSelection();
  }

  updateParentSelection() {
    this.element('codex-parent-options').querySelectorAll('button').forEach(button => {
      const selected = button.dataset.translation === this.parentSuggestion?.translation;
      button.classList.toggle('selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    this.element('codex-parent-choice').textContent = this.parentSuggestion?.translation || '';
  }

  optionElement(tag, option) {
    const card = this.doc.createElement(tag);
    card.className = 'codex-option';
    const translation = this.doc.createElement('strong');
    translation.textContent = option.translation;
    const explanation = this.doc.createElement('span');
    explanation.textContent = option.explanation;
    card.append(translation, explanation);
    return card;
  }

  renderOption(option, index) {
    if (!this.form) return this.optionElement('div', option);
    const card = this.optionElement('button', option);
    const key = this.doc.createElement('span');
    key.className = 'codex-key';
    key.textContent = index < 9 ? String(index + 1) : '';
    card.prepend(key);
    card.type = 'button';
    card.title = 'Click to use, double-click to use and save';
    card.setAttribute('aria-pressed', 'false');
    card.addEventListener('click', () => this.choose(index));
    card.addEventListener('dblclick', () => { this.choose(index); this.form.save(); });
    return card;
  }

  /** An automatic choice fills an empty Translation; a click replaces it. */
  choose(index, automatic = false) {
    if (this.form.text() !== this.text || this.form.languageId() !== this.languageId) return;
    this.form.useParent(this.parentSuggestion ? {...this.parentSuggestion} : null);
    if (!this.form.useTranslation(this.options[index].translation, automatic)) return;
    this.selectedIndex = index;
    this.element('codex-options').querySelectorAll('button').forEach((button, i) => {
      button.classList.toggle('selected', i === index);
      button.setAttribute('aria-pressed', String(i === index));
    });
  }

  onKey(event) {
    if (event.altKey) return;
    if (event.target?.closest?.('input, textarea, select, [contenteditable="true"]')) return;
    if (event.key === 'Enter') {
      event.preventDefault();
      this.form.save();
      return;
    }
    if (event.ctrlKey || event.metaKey) return;
    const index = Number(event.key) - 1;
    if (!(index >= 0 && index < Math.min(this.options.length, 9))) return;
    event.preventDefault();
    this.choose(index);
  }

  renderCards(cards, jobId, current, cardType) {
    const label = cardType === 'words' ? 'word' : 'phrase';
    const section = this.element(`codex-${cardType}`);
    const list = this.element(cardType === 'words' ? 'codex-word-cards' : 'codex-phrase-cards');
    const status = this.element(`codex-${cardType}-status`);
    list.replaceChildren();
    section.hidden = cards.length === 0;
    status.textContent = '';
    const rows = [];
    this.cardRows[cardType] = rows;
    let saving = false;

    const updateButtons = () => {
      if (current !== this.generation) return;
      if (cardType === 'words') this.form.useWords(this.selectedWords());
      else this.form.usePhrases(this.selectedPhrases());
      rows.forEach(row => { row.button.disabled = saving || row.saved; });
    };

    const save = async indices => {
      if (saving || !indices.length || current !== this.generation) return;
      saving = true;
      updateButtons();
      status.textContent = 'Saving…';
      try {
        const data = await readResponse(await this.win.fetch(`/translation/${cardType}`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({language_id: this.languageId, job_id: jobId, indices}),
        }));
        if (current !== this.generation) return;
        data.saved.forEach(item => {
          const row = rows[item.index];
          row.saved = true;
          row.checkbox.checked = cardType === 'words';
          row.checkbox.disabled = true;
          row.button.textContent = 'Saved';
          row.button.setAttribute('aria-label', `Saved ${label} ${item.text}`);
          row.translation.textContent = item.translation;
        });
        status.textContent = `${data.saved.length} saved`;
        this.onCardsSaved();
      } catch (error) {
        if (current === this.generation) status.textContent = error.message;
      } finally {
        saving = false;
        updateButtons();
      }
    };

    cards.forEach((card, index) => {
      const alreadySaved = cardType === 'words' && card.saved === true;
      const row = this.cardRow(card, `codex-${cardType}-select-${current}-${index}`, alreadySaved, label);
      if (alreadySaved) this.markSaved(row, label);
      row.checkbox.addEventListener('change', updateButtons);
      row.button.addEventListener('click', () => save([index]));
      rows.push(row);
      list.appendChild(row.element);
    });
    updateButtons();
  }

  markSaved(row, label) {
    row.saved = true;
    row.checkbox.checked = true;
    row.checkbox.disabled = true;
    row.button.disabled = true;
    row.button.textContent = 'Saved';
    row.button.setAttribute('aria-label', `Saved ${label} ${row.card.text}`);
  }

  selectedPhrases() {
    return this.cardRows.phrases
      .filter(row => row.checkbox.checked && !row.saved)
      .map(row => ({text: row.card.text, translation: row.card.translation}));
  }

  selectedWords() {
    return this.cardRows.words
      .filter(row => row.checkbox.checked && !row.saved)
      .map(row => ({
        text: row.card.text,
        translation: row.card.translation,
        lemma: row.card.lemma,
        is_inflected: row.card.is_inflected,
        lemma_translation: row.card.lemma_translation,
      }));
  }

  cardRow(card, id, checked, label) {
    const element = this.doc.createElement('div');
    element.className = 'codex-word';
    const checkbox = this.doc.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.id = id;
    checkbox.checked = checked;
    checkbox.setAttribute('aria-label', `Select ${card.text}`);
    const body = this.doc.createElement('label');
    body.className = 'codex-word-body';
    body.htmlFor = id;
    const title = this.doc.createElement('strong');
    title.textContent = card.text;
    const translation = this.doc.createElement('span');
    translation.className = 'codex-word-translation';
    translation.textContent = card.translation;
    body.append(title, translation);
    if (card.is_inflected && card.lemma !== card.text) {
      const parent = this.doc.createElement('span');
      parent.className = 'codex-word-parent';
      parent.textContent = `Parent: ${card.lemma} — ${card.lemma_translation}`;
      body.appendChild(parent);
    }
    const button = this.doc.createElement('button');
    button.type = 'button';
    button.className = 'btn codex-word-add';
    button.textContent = 'Add';
    button.setAttribute('aria-label', `Add ${label} ${card.text}`);
    element.append(checkbox, body, button);
    return {element, checkbox, button, translation, card, saved: false};
  }
}
