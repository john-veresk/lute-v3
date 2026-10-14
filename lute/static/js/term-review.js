/* Transient flashcards: only a deliberate level choice writes to Lute. */
class LuteTermReview {
  constructor(root, configuration) {
    this.root = root;
    this.ids = [...new Set(configuration.term_ids)];
    for (let i = this.ids.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [this.ids[i], this.ids[j]] = [this.ids[j], this.ids[i]];
    }
    this.index = 0;
    this.rated = 0;
    this.skipped = 0;
    this.unavailable = 0;
    this.untranslated = configuration.untranslated;
    this.card = null;
    this.revealed = false;
    this.busy = false;
    this.levels = [...root.querySelectorAll('[data-review-status]')];
    this.el('show-answer').addEventListener('click', () => this.showAnswer());
    this.el('skip').addEventListener('click', () => this.skip());
    this.el('retry').addEventListener('click', () => this.loadCurrent());
    this.levels.forEach(button => button.addEventListener('click', () => this.rate(Number(button.dataset.reviewStatus))));
    document.addEventListener('keydown', event => this.handleKey(event));
    this.loadCurrent();
  }

  el(name) { return this.root.querySelector(`#review-${name}`); }

  setBusy(busy) {
    this.busy = busy;
    this.root.querySelectorAll('button').forEach(button => { button.disabled = busy; });
    this.el('card').setAttribute('aria-busy', String(busy));
  }

  clearError() {
    this.el('error').hidden = true;
    this.el('error').textContent = '';
    this.el('retry').hidden = true;
  }

  showError(message, retry = false) {
    this.el('error').textContent = message;
    this.el('error').hidden = false;
    this.el('retry').hidden = !retry;
  }

  async loadCurrent() {
    if (this.busy) return;
    this.clearError();
    this.card = null;
    this.revealed = false;
    this.el('answer').hidden = true;
    this.el('show-answer').hidden = true;
    this.el('word').textContent = '';
    this.el('language').textContent = '';
    this.el('meanings').replaceChildren();
    this.el('loading').hidden = false;
    this.setBusy(true);
    try {
      while (this.index < this.ids.length) {
        this.el('progress').textContent = `Card ${this.index + 1} of ${this.ids.length}`;
        this.el('progress-bar').value = this.index;
        const response = await fetch(`/term/review/card/${this.ids[this.index]}`, {cache: 'no-store'});
        if ([404, 410, 422].includes(response.status)) {
          this.index++;
          this.unavailable++;
          continue;
        }
        if (!response.ok) throw new Error('Unable to load the card. Retry or skip this term.');
        this.card = await response.json();
        this.el('word').textContent = this.card.text;
        this.el('word').dir = this.card.direction;
        this.el('language').textContent = this.card.language;
        this.el('show-answer').hidden = false;
        return;
      }
      this.finish();
    } catch (error) {
      this.showError('Unable to load the card. Retry or skip this term.', true);
    } finally {
      this.el('loading').hidden = true;
      this.setBusy(false);
      if (this.card) this.el('show-answer').focus();
    }
  }

  showAnswer() {
    if (this.busy || !this.card || this.revealed) return;
    this.revealed = true;
    const meanings = this.el('meanings');
    meanings.replaceChildren();
    this.card.meanings.forEach(meaning => {
      if (meaning.parent) {
        const parent = document.createElement('p');
        parent.className = 'review-parent';
        parent.textContent = meaning.parent;
        parent.dir = this.card.direction;
        meanings.appendChild(parent);
      }
      const translation = document.createElement('p');
      translation.className = 'review-meaning';
      translation.textContent = meaning.translation;
      translation.dir = 'auto';
      meanings.appendChild(translation);
    });
    const current = this.levels.find(button => Number(button.dataset.reviewStatus) === this.card.status);
    this.el('current-status').textContent = `Current level: ${current?.textContent.trim() ?? this.card.status}`;
    this.levels.forEach(button => button.setAttribute('aria-pressed', String(button === current)));
    this.el('show-answer').hidden = true;
    this.el('answer').hidden = false;
    (current ?? this.levels[0])?.focus();
  }

  async rate(status) {
    if (this.busy || !this.card || !this.revealed) return;
    if (!this.levels.some(button => Number(button.dataset.reviewStatus) === status)) return;
    this.clearError();
    this.setBusy(true);
    try {
      const response = await fetch('/term/ajax_edit_from_index', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({term_id: this.card.id, update_type: 'status', values: status}),
      });
      if (!response.ok) throw new Error('Unable to save');
      await response.json();
    } catch (error) {
      this.showError('Could not save the level. Choose a level again to retry, or skip this term.');
      this.setBusy(false);
      return;
    }
    this.rated++;
    this.index++;
    this.setBusy(false);
    await this.loadCurrent();
  }

  skip() {
    if (this.busy || this.index >= this.ids.length) return;
    this.skipped++;
    this.index++;
    this.loadCurrent();
  }

  handleKey(event) {
    if (event.repeat || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    if (event.target?.closest('input, textarea, select, [contenteditable="true"]')) return;
    if (event.code === 'Space' || event.key === ' ') {
      // Suppress native button activation, including a focused level button.
      event.preventDefault();
      this.showAnswer();
    } else if (/^[1-5]$/.test(event.key)) {
      event.preventDefault();
      this.rate(Number(event.key));
    } else if (event.code === 'KeyW' || event.key?.toLowerCase() === 'w') {
      event.preventDefault();
      this.rate(99);
    }
  }

  finish() {
    this.el('card').hidden = true;
    this.el('navigation').hidden = true;
    this.el('help').hidden = true;
    this.el('progress-bar').value = this.ids.length;
    this.el('progress').textContent = `${this.ids.length} of ${this.ids.length} cards completed`;
    this.el('complete').hidden = false;
    this.el('complete-title').textContent = this.ids.length ? 'Practice complete' : 'No terms to practice';
    this.el('summary').textContent = this.ids.length
      ? `${this.rated} reviewed · ${this.skipped} skipped · ${this.unavailable} unavailable.`
      : 'Save translations for some terms, or change the term filters and try again.';
    this.el('complete-title').focus();
  }
}

const reviewRoot = document.querySelector('[data-term-review]');
if (reviewRoot && document.getElementById('review-queue')) {
  new LuteTermReview(reviewRoot, JSON.parse(document.getElementById('review-queue').textContent));
}
