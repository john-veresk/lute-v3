"use strict";

/**
 * Translates the unknown words of the page in the background, one at a
 * time, so their term cards open with a saved Codex translation.
 * The server skips words that already have one.
 */
class Pretranslator {
  constructor({fetch, wait, languageId}) {
    this.fetch = fetch;
    this.wait = wait;
    this.languageId = languageId;
    this.queue = [];
    this.draining = null;
  }

  /** Replace the waiting words; the word being translated finishes first. */
  run(words) {
    const seen = new Set();
    this.queue = words.filter(word => {
      const key = word.text.toLocaleLowerCase();
      return !seen.has(key) && seen.add(key);
    });
    this.draining ||= this.drain();
    return this.draining;
  }

  async drain() {
    while (this.queue.length) await this.translate(this.queue.shift());
    this.draining = null;
  }

  async translate(word) {
    const body = JSON.stringify({language_id: this.languageId, text: word.text, context: word.context, kind: 'term', mode: 'prefetch'});
    for (let attempt = 0; attempt < 5; attempt++) {
      const response = await this.fetch('/translation/jobs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body});
      if (response.status === 429) {
        await this.wait(5000);
        continue;
      }
      if (!response.ok) return;
      const job = await response.json();
      if (job.job_id) await this.finish(job.job_id);
      return;
    }
  }

  /** Polling a completed job is what saves its translation. */
  async finish(jobId) {
    while (true) {
      const response = await this.fetch(`/translation/jobs/${jobId}`);
      if (!response.ok || (await response.json()).status !== 'pending') return;
      await this.wait(1500);
    }
  }
}
