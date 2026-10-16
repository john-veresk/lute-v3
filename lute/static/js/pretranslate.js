"use strict";

/**
 * Translates the unknown words of the page in the background, one at a
 * time, so their term cards open with a saved Codex translation.
 * The server skips words that already have one.
 */
class Pretranslator {
  constructor({fetch, wait, languageId, onProgress = () => {}}) {
    this.fetch = fetch;
    this.wait = wait;
    this.languageId = languageId;
    this.onProgress = onProgress;
    this.queue = [];
    this.draining = null;
    this.done = 0;
    this.total = 0;
    this.generation = 0;
    this.lastError = '';
  }

  /** Replace the waiting words; the word being translated finishes first. */
  run(words) {
    const seen = new Set();
    this.queue = words.filter(word => {
      const key = word.text.toLocaleLowerCase();
      return !seen.has(key) && seen.add(key);
    });
    this.generation += 1;
    this.done = 0;
    this.total = this.queue.length;
    this.lastError = '';
    this.onProgress({done: this.done, total: this.total});
    if (this.queue.length) this.draining ||= this.drain();
    return this.draining;
  }

  /** Continue a stopped queue without losing its position or completed count. */
  retry() {
    if (this.draining || !this.queue.length) return this.draining;
    this.lastError = '';
    this.onProgress({done: this.done, total: this.total});
    this.draining = this.drain();
    return this.draining;
  }

  async drain() {
    try {
      while (this.queue.length) {
        const generation = this.generation;
        const word = this.queue.shift();
        let success = false;
        try {
          success = await this.translate(word, generation);
        } catch (error) {
          this.lastError = error.message;
        }
        if (generation !== this.generation) continue;
        if (!success) {
          this.queue.unshift(word);
          this.onProgress({done: this.done, total: this.total, error: true, message: this.lastError});
          break;
        }
        this.done += 1;
        this.onProgress({done: this.done, total: this.total});
      }
    } finally {
      this.draining = null;
    }
  }

  async translate(word, generation) {
    const body = JSON.stringify({language_id: this.languageId, text: word.text, context: word.context, kind: 'term', mode: 'prefetch'});
    let failures = 0;
    while (generation === this.generation) {
      try {
        const response = await this.fetch('/translation/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body});
        if (response.status === 429) {
          const data = await response.json();
          if (generation !== this.generation) return false;
          await this.pause(data.retry_after || 5);
          continue;
        }
        if (!response.ok) throw await this.httpError(response);
        const job = await response.json();
        if (!job.job_id) return true;
        // Even after a new selection, finish polling this job to save its result.
        const result = await this.finish(job.job_id);
        if (generation !== this.generation) return false;
        if (result.error_code === 'rate_limited') {
          await this.pause(result.retry_after || 1);
          continue;
        }
        if (result.status === 'complete') return true;
        throw new Error(result.error || 'Translation failed.');
      } catch (error) {
        if (generation !== this.generation) return false;
        this.lastError = error.message;
        if (error.retryable === false || ++failures >= 3) return false;
        await this.pause(failures === 1 ? 5 : 15, {retrying: true, message: error.message});
      }
    }
    return false;
  }

  async pause(seconds, details = {}) {
    const generation = this.generation;
    this.onProgress({done: this.done, total: this.total, paused: true, retryAfter: seconds, ...details});
    await this.wait(Math.min(120, Math.max(1, seconds)) * 1000);
    if (generation === this.generation) this.onProgress({done: this.done, total: this.total});
  }

  async httpError(response) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(data.error || `Translation request failed (HTTP ${response.status}).`);
    error.retryable = response.status >= 500 || [404, 408, 429].includes(response.status);
    return error;
  }

  /** Polling a completed job is what saves its translation. */
  async finish(jobId) {
    let failures = 0;
    while (true) {
      try {
        const response = await this.fetch(`/translation/jobs/${jobId}`);
        if (!response.ok) throw await this.httpError(response);
        const result = await response.json();
        failures = 0;
        if (result.status !== 'pending') return result;
      } catch (error) {
        if (error.retryable === false || ++failures >= 3) throw error;
      }
      await this.wait(1500);
    }
  }
}
