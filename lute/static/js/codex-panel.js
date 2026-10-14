"use strict";

(() => {
  const params = new URLSearchParams(window.location.search);
  let text = params.get('text') || '';
  const kind = params.get('kind') || 'term';
  let context = params.get('context') || '';
  const status = document.getElementById('codex-status');
  const options = document.getElementById('codex-options');
  const translate = document.getElementById('codex-start');
  const retry = document.getElementById('codex-retry');
  const skeleton = document.getElementById('codex-skeleton');
  const savebar = document.getElementById('codex-savebar');
  const contextElement = document.getElementById('codex-context');
  let generation = 0;
  let parentSuggestion = null;
  let resultOptions = [];
  let selectedIndex = 0;
  const parentSection = document.getElementById('codex-parent');
  const parentOptions = document.getElementById('codex-parent-options');
  const timer = document.getElementById('codex-timer');
  let timerInterval = null;
  let timerStarted = 0;
  const cardGroups = {
    words: {label: 'word', section: document.getElementById('codex-words'), cards: document.getElementById('codex-word-cards'), add: document.getElementById('codex-add-words'), status: document.getElementById('codex-words-status')},
    phrases: {label: 'phrase', section: document.getElementById('codex-phrases'), cards: document.getElementById('codex-phrase-cards'), add: document.getElementById('codex-add-phrases'), status: document.getElementById('codex-phrases-status')},
  };

  const withoutZeroWidth = value => value.replaceAll('\u200b', '');

  /** Split the sentence around the first case-insensitive match of the term. */
  function splitContext(sentence, term) {
    const plain = withoutZeroWidth(sentence);
    const target = withoutZeroWidth(term).trim();
    const index = target ? plain.toLocaleLowerCase().indexOf(target.toLocaleLowerCase()) : -1;
    if (index < 0) return [plain, '', ''];
    return [plain.slice(0, index), plain.slice(index, index + target.length), plain.slice(index + target.length)];
  }

  function showLookup() {
    document.getElementById('codex-text').textContent = withoutZeroWidth(text);
    const parts = splitContext(context, text);
    ['before', 'word', 'after'].forEach((name, index) => {
      document.getElementById(`codex-context-${name}`).textContent = parts[index];
    });
    contextElement.hidden = !context;
    savebar.hidden = kind !== 'term';
  }

  function updateTimer() {
    if (timer) timer.textContent = `${((performance.now() - timerStarted) / 1000).toFixed(1)} s`;
  }

  function startTimer() {
    if (!timer) return;
    clearInterval(timerInterval);
    timerStarted = performance.now();
    updateTimer();
    timerInterval = setInterval(updateTimer, 100);
  }

  function stopTimer() {
    if (timerInterval === null) return;
    updateTimer();
    clearInterval(timerInterval);
    timerInterval = null;
  }

  function renderCards(cards, jobId, current, cardType) {
    const group = cardGroups[cardType];
    group.cards.replaceChildren();
    group.section.hidden = cards.length === 0;
    group.status.textContent = '';
    const rows = [];
    let saving = false;

    function updateButtons() {
      if (current !== generation) return;
      group.add.disabled = saving || !rows.some(row => row.checkbox.checked && !row.saved);
      rows.forEach(row => { row.button.disabled = saving || row.saved; });
    }

    async function save(indices) {
      if (saving || !indices.length || current !== generation) return;
      saving = true;
      updateButtons();
      group.status.textContent = 'Saving…';
      try {
        const data = await readResponse(await fetch(`/translation/${cardType}`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({language_id: Number(params.get('language_id')), job_id: jobId, indices}),
        }));
        if (current !== generation) return;
        data.saved.forEach(item => {
          const row = rows[item.index];
          row.saved = true;
          row.checkbox.checked = false;
          row.checkbox.disabled = true;
          row.button.textContent = 'Saved';
          row.button.setAttribute('aria-label', `Saved ${group.label} ${item.text}`);
          row.translation.textContent = item.translation;
        });
        group.status.textContent = `${data.saved.length} saved`;
        window.parent.postMessage({event: 'LuteCodexWordCardsSaved', request_id: params.get('request_id')}, window.location.origin);
      } catch (error) {
        if (current === generation) group.status.textContent = error.message;
      } finally {
        saving = false;
        updateButtons();
      }
    }

    cards.forEach((word, index) => {
      const card = document.createElement('div');
      card.className = 'codex-word';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.id = `codex-${cardType}-select-${current}-${index}`;
      checkbox.checked = cardType === 'words';
      checkbox.setAttribute('aria-label', `Select ${word.text}`);
      checkbox.addEventListener('change', updateButtons);
      const body = document.createElement('label');
      body.className = 'codex-word-body';
      body.htmlFor = checkbox.id;
      const title = document.createElement('strong');
      title.textContent = word.text;
      const translation = document.createElement('span');
      translation.className = 'codex-word-translation';
      translation.textContent = word.translation;
      body.append(title, translation);
      if (word.is_inflected && word.lemma !== word.text) {
        const parent = document.createElement('span');
        parent.className = 'codex-word-parent';
        parent.textContent = `Parent: ${word.lemma} — ${word.lemma_translation}`;
        body.appendChild(parent);
      }
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn codex-word-add';
      button.textContent = 'Add';
      button.setAttribute('aria-label', `Add ${group.label} ${word.text}`);
      button.addEventListener('click', () => save([index]));
      rows.push({checkbox, button, translation, saved: false});
      card.append(checkbox, body, button);
      group.cards.appendChild(card);
    });
    updateButtons();
    group.add.onclick = () => save(rows.map((row, index) => row.checkbox.checked && !row.saved ? index : -1).filter(index => index >= 0));
  }

  async function readResponse(response) {
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Translation failed. Try again.');
    return data;
  }

  function choose(option, index, automatic = false) {
    const parent = parentSuggestion ? {...parentSuggestion} : null;
    window.parent.postMessage({event: 'LuteCodexTranslation', request_id: params.get('request_id'), text, language_id: Number(params.get('language_id')), translation: option.translation, index, automatic, parent}, window.location.origin);
  }

  function saveTerm() {
    window.parent.postMessage({event: 'LuteCodexSave', request_id: params.get('request_id')}, window.location.origin);
  }

  function updateParentSelection() {
    parentOptions.querySelectorAll('button').forEach(button => {
      const selected = button.dataset.translation === parentSuggestion?.translation;
      button.classList.toggle('selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    document.getElementById('codex-parent-choice').textContent = parentSuggestion?.translation || '';
  }

  function parentChanged() {
    if (!parentSuggestion) return;
    parentSuggestion.translationSelected = true;
    updateParentSelection();
    if (resultOptions.length) choose(resultOptions[selectedIndex], selectedIndex, true);
  }

  function renderParentOptions(choices, existingTranslation) {
    const cards = [...choices];
    if (existingTranslation.trim() && !cards.some(option => option.translation === existingTranslation)) {
      cards.unshift({translation: existingTranslation, explanation: 'Saved in your vocabulary.'});
    }
    cards.forEach(option => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'codex-option';
      card.title = 'Use this meaning for the base form';
      card.dataset.translation = option.translation;
      const translation = document.createElement('strong');
      translation.textContent = option.translation;
      const explanation = document.createElement('span');
      explanation.textContent = option.explanation;
      card.append(translation, explanation);
      card.addEventListener('click', () => {
        parentSuggestion.translation = option.translation;
        parentChanged();
      });
      parentOptions.appendChild(card);
    });
    updateParentSelection();
  }

  function renderOption(option, index) {
    const card = document.createElement(kind === 'term' ? 'button' : 'div');
    card.className = 'codex-option';
    const translation = document.createElement('strong');
    translation.textContent = option.translation;
    const explanation = document.createElement('span');
    explanation.textContent = option.explanation;
    if (kind === 'term') {
      const key = document.createElement('span');
      key.className = 'codex-key';
      key.textContent = index < 9 ? String(index + 1) : '';
      card.append(key, translation, explanation);
      card.type = 'button';
      card.title = 'Click to use, double-click to use and save';
      card.setAttribute('aria-pressed', 'false');
      card.addEventListener('click', () => choose(option, index));
      card.addEventListener('dblclick', () => { choose(option, index); saveTerm(); });
    } else {
      card.append(translation, explanation);
    }
    return card;
  }

  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== window.location.origin || event.data?.event !== 'LuteCodexTranslationSelected' || event.data.request_id !== params.get('request_id')) return;
    if (event.data.index === null) return;
    selectedIndex = event.data.index;
    options.querySelectorAll('button').forEach((button, index) => {
      const selected = index === event.data.index;
      button.classList.toggle('selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
  });

  window.addEventListener('keydown', event => {
    if (kind !== 'term' || event.altKey) return;
    if (event.target?.closest?.('input, textarea, select, [contenteditable="true"]')) return;
    if (event.key === 'Enter') {
      event.preventDefault();
      saveTerm();
      return;
    }
    if (event.ctrlKey || event.metaKey) return;
    const index = Number(event.key) - 1;
    if (!(index >= 0 && index < Math.min(resultOptions.length, 9))) return;
    event.preventDefault();
    choose(resultOptions[index], index);
  });

  async function start() {
    const current = ++generation;
    translate.hidden = true;
    options.replaceChildren();
    parentOptions.replaceChildren();
    parentSection.hidden = true;
    parentSection.open = false;
    Object.values(cardGroups).forEach(group => { group.section.hidden = true; });
    parentSuggestion = null;
    resultOptions = [];
    selectedIndex = 0;
    retry.hidden = true;
    skeleton.hidden = false;
    status.textContent = 'Translating…';
    startTimer();
    try {
      const job = await readResponse(await fetch('/translation/jobs', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({language_id: Number(params.get('language_id')), text, context, kind}),
      }));
      const deadline = Date.now() + 8 * 90 * 1000;
      let data;
      do {
        data = await readResponse(await fetch(`/translation/jobs/${job.job_id}`));
        if (current !== generation) return;
        if (data.status === 'error') throw new Error(data.error);
        if (data.status === 'complete') break;
        if (Date.now() > deadline) throw new Error('Translation timed out. Try again.');
        await new Promise(resolve => setTimeout(resolve, 700));
      } while (true);
      const clean = value => withoutZeroWidth(value).trim().toLocaleLowerCase();
      const isNewLemma = data.result.lemma && clean(data.result.lemma) !== clean(text);
      document.getElementById('codex-lemma').textContent = isNewLemma ? data.result.lemma : '';
      if (kind === 'term' && data.result.is_inflected && isNewLemma) {
        try {
          const query = new URLSearchParams({language_id: params.get('language_id'), text: data.result.lemma});
          const existing = await readResponse(await fetch(`/translation/parent?${query}`));
          if (current !== generation) return;
          parentSuggestion = {
            text: data.result.lemma,
            status: existing.status,
            existingTranslation: !!existing.translation.trim(),
            translation: existing.translation.trim() ? existing.translation : data.result.lemma_translation,
          };
          document.getElementById('codex-parent-text').textContent = data.result.lemma;
          renderParentOptions(data.result.lemma_options || [{translation: data.result.lemma_translation, explanation: ''}], existing.translation);
          parentSection.hidden = false;
        } catch (error) {
          document.getElementById('codex-lemma').textContent += ' (base form lookup failed; add it in Parents)';
        }
      }
      resultOptions = data.result.options;
      renderCards(data.result.words || [], job.job_id, current, 'words');
      renderCards(data.result.phrases || [], job.job_id, current, 'phrases');
      status.textContent = '';
      data.result.options.forEach((option, index) => options.appendChild(renderOption(option, index)));
      if (kind === 'term') choose(data.result.options[0], 0, true);
    } catch (error) {
      if (current !== generation) return;
      status.textContent = error.message;
      retry.hidden = false;
    } finally {
      if (current === generation) {
        skeleton.hidden = true;
        stopTimer();
      }
    }
  }
  translate.addEventListener('click', start);
  retry.addEventListener('click', start);
  document.getElementById('codex-save').addEventListener('click', saveTerm);
  window.addEventListener('pagehide', () => { generation++; stopTimer(); });
  if (params.has('request_id')) {
    let received = false;
    window.addEventListener('message', event => {
      if (received || event.source !== window.parent || event.origin !== window.location.origin || event.data?.event !== 'LuteCodexLookup' || event.data.request_id !== params.get('request_id')) return;
      received = true;
      text = event.data.payload.text;
      context = event.data.payload.context;
      showLookup();
      if (event.data.payload.autostart === false) {
        status.textContent = 'Already translated.';
        translate.hidden = false;
      } else {
        start();
      }
    });
    window.parent.postMessage({event: 'LuteCodexReady', request_id: params.get('request_id')}, window.location.origin);
  } else {
    showLookup();
    start();
  }
})();
