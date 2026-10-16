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
    this.onProgress({done: this.done, total: this.total});
    if (this.queue.length) this.draining ||= this.drain();
    return this.draining;
  }

  async drain() {
    try {
      while (this.queue.length) {
        const generation = this.generation;
        let success = false;
        try {
          success = await this.translate(this.queue.shift(), generation);
        } catch (error) {
          // Network/JSON errors also leave the word unprocessed.
        }
        if (generation !== this.generation) continue;
        if (!success) {
          this.onProgress({done: this.done, total: this.total, error: true});
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
    while (generation === this.generation) {
      const response = await this.fetch('/translation/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body});
      if (response.status === 429) {
        const data = await response.json();
        await this.pause(data.retry_after || 5);
        continue;
      }
      if (!response.ok) return false;
      const job = await response.json();
      if (!job.job_id) return true;
      const result = await this.finish(job.job_id);
      if (generation !== this.generation) return false;
      if (result.error_code === 'rate_limited') {
        await this.pause(result.retry_after || 1);
        continue;
      }
      return result.status === 'complete';
    }
    return false;
  }

  async pause(seconds) {
    this.onProgress({done: this.done, total: this.total, paused: true});
    await this.wait(Math.min(120, Math.max(1, seconds)) * 1000);
  }

  /** Polling a completed job is what saves its translation. */
  async finish(jobId) {
    while (true) {
      const response = await this.fetch(`/translation/jobs/${jobId}`);
      if (!response.ok) return {status: 'error'};
      const result = await response.json();
      if (result.status !== 'pending') return result;
      await this.wait(1500);
    }
  }
}
