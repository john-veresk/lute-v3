"use strict";

/** The browser only renders state and sends commands. All work runs on the server. */
class TranslationJobManager {
  constructor(root) {
    this.root = root;
    this.selected = new Set();
    this.startPages = new Map();
    this.state = {books: [], jobs: []};
    this.busy = false;
    this.refreshing = false;
    this.bookSignature = '';
    this.selectedTags = new Set();
    this.find('jobs-tags').addEventListener('click', event => {
      const button = event.target.closest('[data-tag]');
      if (!button) return;
      const tag = button.dataset.tag;
      if (tag === '') this.selectedTags.clear();
      else if (this.selectedTags.has(tag)) this.selectedTags.delete(tag);
      else this.selectedTags.add(tag);
      this.renderTags();
      this.renderBooks();
    });
    this.find('jobs-clear').addEventListener('click', () => {
      this.selected.clear();
      this.renderBooks();
    });
    this.find('jobs-search').addEventListener('input', () => this.renderBooks());
    this.find('jobs-books').addEventListener('change', event => {
      if (event.target.matches('[data-start-page]')) {
        this.startPages.set(Number(event.target.dataset.startPage), Number(event.target.value));
        return;
      }
      const id = Number(event.target.value);
      if (event.target.checked) this.selected.add(id);
      else this.selected.delete(id);
      this.renderSelection();
    });
    this.find('jobs-select-all').addEventListener('change', event => {
      this.visibleBooks().filter(book => !this.unavailable(book)).forEach(book => {
        if (event.target.checked) this.selected.add(book.id);
        else this.selected.delete(book.id);
      });
      this.renderBooks();
    });
    this.find('jobs-add').addEventListener('click', () => this.addBooks());
    this.find('jobs-list').addEventListener('click', event => {
      const button = event.target.closest('[data-action]');
      if (button) this.command(`/jobs/${button.closest('[data-job-id]').dataset.jobId}/${button.dataset.action}`);
    });
    this.refresh();
  }

  find(id) { return document.getElementById(id); }

  async request(url, body) {
    const options = {cache: 'no-store'};
    if (body !== undefined) Object.assign(options, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
    return data;
  }

  error(message = '') {
    const error = this.find('jobs-error');
    error.textContent = message;
    error.hidden = !message;
  }

  addBooks() {
    for (const input of this.find('jobs-books').querySelectorAll('[data-start-page]')) {
      if (this.selected.has(Number(input.dataset.startPage)) && !input.reportValidity()) return;
    }
    const start_pages = Object.fromEntries([...this.selected].map(id => [id,
      this.startPages.get(id) ?? this.state.books.find(book => book.id === id).start_page,
    ]));
    this.command('/jobs', {book_ids: [...this.selected], start_pages});
  }

  async command(url, body = {}) {
    if (this.busy) return;
    this.busy = true;
    this.updateButtons();
    try {
      await this.request(url, body);
      if (url === '/jobs') this.selected.clear();
      this.error();
    } catch (error) {
      this.error(error.message);
    } finally {
      this.busy = false;
      await this.refresh();
      this.renderSelection();
      this.updateButtons();
    }
  }

  async refresh() {
    if (this.refreshing) return;
    this.refreshing = true;
    try {
      this.state = await this.request('/jobs/state');
      if (this.connectionError) { this.error(); this.connectionError = false; }
      const signature = JSON.stringify([this.state.books, this.state.jobs.filter(job => this.active(job)).map(job => job.book_id)]);
      if (signature !== this.bookSignature) {
        this.bookSignature = signature;
        this.renderTags();
        this.renderBooks();
      }
      this.renderJobs();
      this.find('jobs-loading').hidden = true;
    } catch (error) {
      this.connectionError = true;
      this.error(`Cannot update jobs: ${error.message} Reconnecting…`);
    } finally {
      this.refreshing = false;
      clearTimeout(this.pollTimer);
      this.pollTimer = setTimeout(() => this.refresh(), 1500);
    }
  }

  active(job) { return !['complete', 'cancelled'].includes(job.status); }
  unavailable(book) { return !book.supported || this.state.jobs.some(job => job.book_id === book.id && this.active(job)); }
  renderTags() {
    const counts = new Map();
    this.state.books.forEach(book => (book.tags || []).forEach(tag => counts.set(tag, (counts.get(tag) || 0) + 1)));
    const tags = [...counts.keys()].sort((a, b) => a.localeCompare(b));
    const list = this.find('jobs-tags');
    const focus = document.activeElement?.dataset.tag;
    list.replaceChildren();
    const add = (tag, label, count, pressed) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'tag-pill';
      button.dataset.tag = tag;
      button.setAttribute('aria-pressed', String(pressed));
      button.textContent = label;
      if (count !== undefined) {
        const badge = document.createElement('span');
        badge.className = 'tag-pill-count';
        badge.textContent = count;
        button.append(badge);
      }
      list.append(button);
      if (focus === tag) button.focus();
    };
    add('', 'All tags', undefined, !this.selectedTags.size);
    tags.forEach(tag => add(tag, tag, counts.get(tag), this.selectedTags.has(tag)));
  }

  visibleBooks() {
    const query = this.find('jobs-search').value.toLocaleLowerCase().trim();
    const tags = [...this.selectedTags];
    return this.state.books.filter(book => `${book.title} ${book.language}`.toLocaleLowerCase().includes(query)
      && (!tags.length || tags.some(tag => (book.tags || []).includes(tag))));
  }

  renderBooks() {
    const list = this.find('jobs-books');
    list.replaceChildren();
    this.visibleBooks().forEach(book => {
      const row = document.createElement('div');
      row.className = 'jobs-book-row';
      const label = document.createElement('label');
      label.className = 'jobs-check';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.value = book.id;
      checkbox.disabled = this.unavailable(book);
      if (checkbox.disabled) this.selected.delete(book.id);
      checkbox.checked = this.selected.has(book.id);
      const text = document.createElement('span');
      text.textContent = book.title;
      const meta = document.createElement('span');
      meta.className = 'jobs-book-meta';
      meta.textContent = `${book.language}${book.archived ? ' · Archived' : ''}${book.tags?.length ? ` · ${book.tags.join(', ')}` : ''}${!book.supported ? ' · Parser unavailable' : checkbox.disabled ? ' · Already queued' : ''}`;
      text.append(meta);
      label.append(checkbox, text);
      row.append(label);
      if (!checkbox.disabled) {
        const pageLabel = document.createElement('label');
        pageLabel.className = 'jobs-start-page';
        pageLabel.textContent = 'From page';
        const page = document.createElement('input');
        page.type = 'number';
        page.required = true;
        page.min = '1';
        page.max = book.page_count;
        page.step = '1';
        page.value = this.startPages.get(book.id) ?? book.start_page;
        page.dataset.startPage = book.id;
        page.setAttribute('aria-label', `Starting page for ${book.title}`);
        pageLabel.append(page, document.createTextNode(`of ${book.page_count}`));
        row.append(pageLabel);
      }
      list.append(row);
    });
    if (!list.children.length) list.textContent = 'No matching books.';
    this.renderSelection();
  }

  renderSelection() {
    this.find('jobs-add').textContent = this.selected.size ? `Add to queue (${this.selected.size})` : 'Add to queue';
    this.find('jobs-add').disabled = this.busy || !this.selected.size;
    this.find('jobs-clear').hidden = !this.selected.size;
    this.find('jobs-selection').textContent = `${this.visibleBooks().length} books shown · ${this.selected.size} selected`;
    const visible = this.visibleBooks().filter(book => !this.unavailable(book));
    const selected = visible.filter(book => this.selected.has(book.id)).length;
    const all = this.find('jobs-select-all');
    all.disabled = !visible.length;
    all.checked = visible.length > 0 && selected === visible.length;
    all.indeterminate = selected > 0 && selected < visible.length;
  }

  renderJobs() {
    const list = this.find('jobs-list');
    const opened = new Set([...list.querySelectorAll('details[open]')].map(el => el.closest('[data-job-id]').dataset.jobId));
    const focused = document.activeElement?.closest('[data-action]');
    const focus = focused ? [focused.closest('[data-job-id]').dataset.jobId, focused.dataset.action] : null;
    list.replaceChildren();
    const waiting = this.state.jobs.filter(job => ['queued', 'paused', 'error'].includes(job.status));
    const active = this.state.jobs.filter(job => this.active(job));
    const history = this.state.jobs.filter(job => !this.active(job)).reverse();
    const complete = this.state.jobs.filter(job => job.status === 'complete').length;
    this.find('jobs-summary').textContent = `${active.length} active · ${complete} completed`;
    this.find('jobs-empty').hidden = this.state.jobs.length > 0;
    [...active, ...history].forEach(job => {
      const card = this.find('job-card-template').content.firstElementChild.cloneNode(true);
      card.dataset.jobId = job.id;
      card.dataset.status = job.status;
      const field = name => card.querySelector(`[data-field="${name}"]`);
      field('title').textContent = job.title;
      if (job.book_id) field('title').href = `/read/${job.book_id}`;
      const statuses = {queued: 'Queued', running: 'Translating', waiting: 'Retrying', paused: 'Paused', error: 'Failed', complete: 'Completed', cancelled: 'Cancelled'};
      let status = statuses[job.status] || job.status;
      if (job.status === 'waiting' && job.retry_at) status += ` in ${Math.max(0, Math.ceil((Date.parse(job.retry_at) - Date.now()) / 1000))} s`;
      field('status').textContent = status;
      const settings = job.settings;
      field('settings').textContent = `${settings.source} → ${settings.target_label || settings.target} · ${settings.cli === 'cursor' ? 'Cursor Agent' : 'Codex CLI'} · ${settings.model || 'CLI default'}${settings.effort ? ` · ${settings.effort}` : ''} · From page ${job.start_page}`;
      const progress = field('progress');
      progress.max = job.total || 1;
      progress.value = job.status === 'complete' ? progress.max : job.done;
      const percent = job.total ? Math.round(job.done / job.total * 100) : job.status === 'complete' ? 100 : 0;
      field('counts').textContent = job.prepared ? `${job.done} / ${job.total} words · ${job.translated} translated · ${job.skipped} skipped` : 'Waiting to scan unknown words';
      field('percent').textContent = `${percent}%`;
      field('current').textContent = job.current_word ? `Page ${job.current_page} · ${job.current_word}` : job.status === 'complete' ? 'All unknown words processed.' : '';
      field('error').textContent = job.error;
      field('error').hidden = !job.error;
      field('times').textContent = [`Created: ${this.time(job.created_at)}`, job.started_at && `Started: ${this.time(job.started_at)}`, job.finished_at && `Finished: ${this.time(job.finished_at)}`, `Updated: ${this.time(job.updated_at)}`, `Errors: ${job.error_count}`].filter(Boolean).join(' · ');
      field('context').textContent = job.current_context;
      for (const error of job.errors || []) {
        const item = document.createElement('li');
        item.textContent = `${this.time(error.at)} · ${error.word || 'Preparation'} · ${error.message}`;
        field('errors').append(item);
      }
      const index = waiting.findIndex(item => item.id === job.id);
      const actions = {pause: ['queued', 'running', 'waiting'].includes(job.status), resume: ['paused', 'error'].includes(job.status), cancel: this.active(job), up: index > 0, down: index >= 0 && index < waiting.length - 1};
      card.querySelectorAll('[data-action]').forEach(button => {
        button.hidden = !actions[button.dataset.action];
        button.disabled = this.busy;
        if (button.dataset.action === 'resume' && job.status === 'error') button.textContent = 'Retry';
      });
      card.querySelector('details').open = opened.has(String(job.id));
      list.append(card);
    });
    if (focus) list.querySelector(`[data-job-id="${focus[0]}"] [data-action="${focus[1]}"]:not([hidden])`)?.focus();
  }

  updateButtons() {
    this.root.querySelectorAll('[data-action]').forEach(button => { button.disabled = this.busy; });
    this.renderSelection();
  }

  time(value) { return value ? new Date(value).toLocaleString() : '—'; }
}

new TranslationJobManager(document.getElementById('translation-jobs'));
