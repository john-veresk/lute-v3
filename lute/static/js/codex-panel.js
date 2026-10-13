"use strict";

(() => {
  const params = new URLSearchParams(window.location.search);
  let text = params.get('text') || '';
  const kind = params.get('kind') || 'term';
  let context = params.get('context') || '';
  const status = document.getElementById('codex-status');
  const options = document.getElementById('codex-options');
  const retry = document.getElementById('codex-retry');
  document.getElementById('codex-text').textContent = text.replaceAll('\u200b', '');
  const contextElement = document.getElementById('codex-context');
  contextElement.textContent = context;
  contextElement.hidden = !context;
  let generation = 0;
  let parentSuggestion = null;
  let resultOptions = [];
  let selectedIndex = 0;
  const parentSection = document.getElementById('codex-parent');
  const parentTranslation = document.getElementById('codex-parent-translation');
  const wordsSection = document.getElementById('codex-words');
  const wordCards = document.getElementById('codex-word-cards');
  const addWords = document.getElementById('codex-add-words');
  const wordsStatus = document.getElementById('codex-words-status');

  function renderWordCards(words, jobId, current) {
    wordCards.replaceChildren();
    wordsSection.hidden = words.length === 0;
    wordsStatus.textContent = '';
    const rows = [];
    let saving = false;

    async function save(indices) {
      if (saving || !indices.length || current !== generation) return;
      saving = true;
      addWords.disabled = true;
      rows.forEach(row => { row.button.disabled = true; });
      wordsStatus.textContent = 'Saving word cards…';
      try {
        const data = await readResponse(await fetch('/translation/words', {
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
          row.button.setAttribute('aria-label', `Saved word ${item.text}`);
          row.translation.textContent = item.translation;
        });
        wordsStatus.textContent = `${data.saved.length} word card(s) saved to Lute.`;
        window.parent.postMessage({event: 'LuteCodexWordCardsSaved', request_id: params.get('request_id')}, window.location.origin);
      } catch (error) {
        if (current === generation) wordsStatus.textContent = error.message;
      } finally {
        saving = false;
        addWords.disabled = rows.every(row => row.saved);
        rows.forEach(row => { row.button.disabled = row.saved; });
      }
    }

    words.forEach((word, index) => {
      const card = document.createElement('div');
      card.className = 'codex-word';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = true;
      checkbox.setAttribute('aria-label', `Select ${word.text}`);
      const body = document.createElement('div');
      body.className = 'codex-word-body';
      const title = document.createElement('strong');
      title.textContent = word.text;
      const translation = document.createElement('p');
      translation.className = 'codex-word-translation';
      translation.textContent = word.translation;
      body.append(title, translation);
      if (word.is_inflected && word.lemma !== word.text) {
        const parent = document.createElement('div');
        parent.className = 'codex-hint';
        parent.textContent = `Parent: ${word.lemma} — ${word.lemma_translation}`;
        body.appendChild(parent);
      }
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn';
      button.textContent = 'Add word';
      button.setAttribute('aria-label', `Add word ${word.text}`);
      button.addEventListener('click', () => save([index]));
      rows.push({checkbox, button, translation, saved: false});
      card.append(checkbox, body, button);
      wordCards.appendChild(card);
    });
    addWords.disabled = false;
    addWords.onclick = () => save(rows.map((row, index) => row.checkbox.checked && !row.saved ? index : -1).filter(index => index >= 0));
  }

  async function readResponse(response) {
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Translation failed. Try again.');
    return data;
  }

  function choose(option, index, automatic = false) {
    const parent = parentSuggestion ? {...parentSuggestion, translation: parentTranslation.value} : null;
    window.parent.postMessage({event: 'LuteCodexTranslation', request_id: params.get('request_id'), text, language_id: Number(params.get('language_id')), translation: option.translation, index, automatic, parent}, window.location.origin);
  }

  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== window.location.origin || event.data?.event !== 'LuteCodexTranslationSelected' || event.data.request_id !== params.get('request_id')) return;
    if (event.data.parentStatus) document.getElementById('codex-parent-status').textContent = event.data.parentStatus;
    if (event.data.index === null) return;
    selectedIndex = event.data.index;
    options.querySelectorAll('button').forEach((button, index) => {
      const selected = index === event.data.index;
      button.classList.toggle('selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
  });

  async function start() {
    const current = ++generation;
    options.replaceChildren();
    parentSection.hidden = true;
    wordsSection.hidden = true;
    parentSuggestion = null;
    retry.hidden = true;
    document.getElementById('codex-hint').hidden = true;
    status.textContent = 'Translating with Codex…';
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
      document.getElementById('codex-lemma').textContent = data.result.lemma ? `Dictionary form: ${data.result.lemma}` : '';
      const clean = value => value.replaceAll('\u200b', '').trim().toLocaleLowerCase();
      if (kind === 'term' && data.result.is_inflected && clean(data.result.lemma) !== clean(text)) {
        try {
          const query = new URLSearchParams({language_id: params.get('language_id'), text: data.result.lemma});
          const existing = await readResponse(await fetch(`/translation/parent?${query}`));
          if (current !== generation) return;
          parentSuggestion = {text: data.result.lemma, status: existing.status, existingTranslation: !!existing.translation.trim()};
          parentTranslation.value = existing.translation.trim() ? existing.translation : data.result.lemma_translation;
          parentTranslation.readOnly = parentSuggestion.existingTranslation;
          document.getElementById('codex-parent-text').textContent = data.result.lemma;
          parentSection.hidden = false;
        } catch (error) {
          document.getElementById('codex-lemma').textContent += ' — parent lookup failed; enter it manually in Parents.';
        }
      }
      resultOptions = data.result.options;
      renderWordCards(data.result.words || [], job.job_id, current);
      status.textContent = kind === 'term' ? 'Translation options' : 'Translation';
      data.result.options.forEach((option, index) => {
        const card = document.createElement(kind === 'term' ? 'button' : 'div');
        card.className = 'codex-option';
        const translation = document.createElement('strong');
        translation.textContent = option.translation;
        const explanation = document.createElement('span');
        explanation.textContent = option.explanation;
        card.append(translation, explanation);
        if (kind === 'term') {
          card.type = 'button';
          card.title = 'Use this translation';
          card.setAttribute('aria-pressed', 'false');
          card.addEventListener('click', () => choose(option, index));
        }
        options.appendChild(card);
      });
      document.getElementById('codex-hint').hidden = kind !== 'term';
      if (kind === 'term') choose(data.result.options[0], 0, true);
    } catch (error) {
      if (current !== generation) return;
      status.textContent = error.message;
      retry.hidden = false;
    }
  }
  retry.addEventListener('click', start);
  parentTranslation.addEventListener('input', () => {
    if (resultOptions.length) choose(resultOptions[selectedIndex], selectedIndex, true);
  });
  window.addEventListener('pagehide', () => { generation++; });
  if (params.has('request_id')) {
    let received = false;
    window.addEventListener('message', event => {
      if (received || event.source !== window.parent || event.origin !== window.location.origin || event.data?.event !== 'LuteCodexLookup' || event.data.request_id !== params.get('request_id')) return;
      received = true;
      text = event.data.payload.text;
      context = event.data.payload.context;
      document.getElementById('codex-text').textContent = text.replaceAll('\u200b', '');
      contextElement.textContent = context;
      contextElement.hidden = !context;
      start();
    });
    window.parent.postMessage({event: 'LuteCodexReady', request_id: params.get('request_id')}, window.location.origin);
  } else {
    start();
  }
})();
