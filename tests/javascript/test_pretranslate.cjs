// node tests/javascript/test_pretranslate.cjs
// Unknown words are translated one at a time in the background.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync('lute/static/js/pretranslate.js', 'utf8'), context);
const Pretranslator = vm.runInContext('Pretranslator', context);

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});

function makePretranslator(reply, onProgress, wait = async () => {}) {
  const requests = [];
  let inFlight = 0;
  let maxInFlight = 0;
  const pretranslator = new Pretranslator({
    languageId: 1,
    wait,
    onProgress,
    fetch: async (url, options) => {
      const body = options && JSON.parse(options.body);
      requests.push({url, body});
      const result = await reply(url, body, requests);
      if (url === '/translation/jobs' && result.status === 202) maxInFlight = Math.max(maxInFlight, ++inFlight);
      if (url.startsWith('/translation/jobs/') && (await result.json()).status !== 'pending') inFlight--;
      return result;
    },
  });
  return {pretranslator, requests, maxInFlight: () => maxInFlight};
}

const words = [
  {text: 'Kissa', context: 'Kissa nukkuu.'},
  {text: 'nukkuu', context: 'Kissa nukkuu.'},
  {text: 'kissa', context: 'Iso kissa.'},
];

async function checks() {
  const polls = {};
  const basic = makePretranslator(async (url, body) => {
    if (url === '/translation/jobs') return body.text === 'nukkuu' ? response({job_id: null}) : response({job_id: body.text}, 202);
    polls[url] = (polls[url] || 0) + 1;
    return response({status: polls[url] < 3 ? 'pending' : 'complete'});
  });
  await basic.pretranslator.run(words);
  const submitted = basic.requests.filter(r => r.url === '/translation/jobs').map(r => r.body);
  assert.deepEqual(submitted.map(body => body.text), ['Kissa', 'nukkuu'], 'each word once, in page order');
  assert.deepEqual(JSON.parse(JSON.stringify(submitted[0])), {
    language_id: 1, text: 'Kissa', context: 'Kissa nukkuu.', kind: 'term', mode: 'prefetch',
  }, 'stored translations are skipped by the server');
  assert.equal(polls['/translation/jobs/Kissa'], 3, 'polling continues until the translation is saved');
  assert.equal(polls['/translation/jobs/nukkuu'], undefined, 'nothing to poll for a stored word');
  assert.equal(basic.maxInFlight(), 1, 'one background translation at a time');

  let busy = 1;
  const retry = makePretranslator(async url => {
    if (url === '/translation/jobs' && busy-- > 0) return response({error: 'busy'}, 429);
    if (url === '/translation/jobs') return response({job_id: 'job'}, 202);
    return response({status: 'complete'});
  });
  await retry.pretranslator.run([words[0]]);
  assert.equal(retry.requests.filter(r => r.url === '/translation/jobs').length, 2, 'a busy Codex is retried later');

  const throttleProgress = [];
  const pauses = [];
  let throttles = 2;
  const throttled = makePretranslator(async (url, body) => {
    if (url === '/translation/jobs') return response({job_id: body.text}, 202);
    return throttles-- > 0
      ? response({status: 'error', error_code: 'rate_limited', retry_after: throttles ? 30 : 120})
      : response({status: 'complete'});
  }, event => throttleProgress.push({...event}), async ms => pauses.push(ms));
  await throttled.pretranslator.run([words[0]]);
  assert.deepEqual(pauses, [30000, 120000], 'a CLI 429 pauses before retrying the same word');
  assert.deepEqual(throttled.requests.filter(r => r.body).map(r => r.body.text), ['Kissa', 'Kissa', 'Kissa']);
  assert.deepEqual(throttleProgress.map(p => p.done), [0, 0, 0, 0, 0, 1], 'errors and cooldown do not advance progress');
  assert.equal(throttleProgress[1].paused, true);
  assert.equal(throttleProgress[1].retryAfter, 30, 'the UI can explain the server cooldown');
  assert.equal(throttleProgress.at(-2).paused, undefined, 'the pause clears when requests resume');

  const refusedPauses = [];
  let refused = true;
  const refusedJob = makePretranslator(async url => {
    if (url === '/translation/jobs' && refused) {
      refused = false;
      return response({error_code: 'rate_limited', retry_after: 60}, 429);
    }
    return url === '/translation/jobs' ? response({job_id: 'job'}, 202) : response({status: 'complete'});
  }, undefined, async ms => refusedPauses.push(ms));
  await refusedJob.pretranslator.run([words[0]]);
  assert.deepEqual(refusedPauses, [60000], 'submission honors the server cooldown');

  for (const failure of ['cli', 'http', 'network']) {
    const failedProgress = [];
    const failedPauses = [];
    const failed = makePretranslator(async url => {
      if (failure === 'network') throw new Error('offline');
      if (failure === 'http') return response({}, 500);
      return url === '/translation/jobs' ? response({job_id: 'failed'}, 202) : response({status: 'error'});
    }, event => failedProgress.push({...event}), async ms => failedPauses.push(ms));
    await failed.pretranslator.run(words);
    assert.deepEqual(failedPauses, [5000, 15000], `${failure} retries before stopping`);
    assert.equal(failed.pretranslator.done, 0, `${failure} does not count as a processed word`);
    assert.equal(failedProgress.at(-1).error, true, `${failure} is reported as a failed translation`);
    assert.ok(failedProgress.at(-1).message, 'the error includes a reason');
    assert.equal(failed.pretranslator.queue[0].text, 'Kissa', 'keep the failed word for retry');
    assert.equal(failed.pretranslator.draining, null, 'failure allows a later run');
  }

  for (const failure of ['cli', 'http', 'network']) {
    let fail = true;
    const recovered = makePretranslator(async url => {
      if (fail && (failure !== 'cli' || url !== '/translation/jobs')) {
        fail = false;
        if (failure === 'network') throw new Error('offline');
        return failure === 'http' ? response({}, 503) : response({status: 'error', error: 'CLI disconnected'});
      }
      return url === '/translation/jobs' ? response({job_id: 'job'}, 202) : response({status: 'complete'});
    });
    await recovered.pretranslator.run(words);
    assert.equal(recovered.pretranslator.done, 2, `${failure}: a temporary failure does not stop the queue`);
  }

  let pollFailures = 2;
  const polling = makePretranslator(async url => {
    if (url === '/translation/jobs') return response({job_id: 'job'}, 202);
    if (pollFailures-- > 0) return response({}, 503);
    return response({status: 'complete'});
  });
  await polling.pretranslator.run([words[0]]);
  assert.equal(polling.requests.filter(r => r.body).length, 1, 'polling failures keep the same job instead of submitting another translation');
  assert.equal(polling.pretranslator.done, 1);

  const invalid = makePretranslator(async () => response({error: 'Invalid language'}, 400));
  await invalid.pretranslator.run(words);
  assert.equal(invalid.requests.length, 1, 'invalid requests are not automatically retried');
  assert.equal(invalid.pretranslator.lastError, 'Invalid language');

  let broken = true;
  const resumable = makePretranslator(async (url, body) => {
    if (url === '/translation/jobs') return response({job_id: body.text}, 202);
    return response({status: broken && url.endsWith('/nukkuu') ? 'error' : 'complete'});
  });
  await resumable.pretranslator.run(words);
  assert.equal(resumable.pretranslator.done, 1);
  broken = false;
  await resumable.pretranslator.retry();
  assert.equal(resumable.pretranslator.done, 2, 'retry preserves the completed count');
  assert.equal(resumable.pretranslator.total, 2);
  assert.equal(resumable.requests.filter(r => r.body?.text === 'Kissa').length, 1, 'retry does not restart finished words');

  let releaseManual;
  let savedManually = false;
  const manual = makePretranslator(async (url, body) => {
    if (url === '/translation/jobs') return response({job_id: savedManually && body.text === 'Kissa' ? null : body.text}, 202);
    return response({status: savedManually ? 'complete' : 'error'});
  }, undefined, () => new Promise(resolve => { releaseManual = resolve; }));
  const manualRun = manual.pretranslator.run(words);
  await new Promise(resolve => setImmediate(resolve));
  savedManually = true;
  releaseManual();
  await manualRun;
  assert.equal(manual.pretranslator.done, 2, 'a manual translation saved during a background retry is skipped and the queue continues');
  assert.equal(manual.requests.filter(r => r.url === '/translation/jobs/Kissa').length, 1);

  let releaseRetry;
  const replacingRetry = makePretranslator(async (url, body) => {
    if (url === '/translation/jobs') return response({job_id: body.text}, 202);
    return response({status: url.endsWith('/Kissa') ? 'error' : 'complete'});
  }, undefined, () => new Promise(resolve => { releaseRetry = resolve; }));
  const abandoned = replacingRetry.pretranslator.run(words);
  await new Promise(resolve => setImmediate(resolve));
  const replaced = replacingRetry.pretranslator.run([{text: 'koira', context: 'Koira.'}]);
  releaseRetry();
  await Promise.all([abandoned, replaced]);
  assert.deepEqual(replacingRetry.requests.filter(r => r.body).map(r => r.body.text), ['Kissa', 'koira'], 'a new reading position supersedes the failed word during retry');

  let pausedRelease;
  let oldThrottled = true;
  const pausePaging = makePretranslator(async (url, body) => {
    if (url === '/translation/jobs') return response({job_id: body.text}, 202);
    if (oldThrottled) {
      oldThrottled = false;
      return response({status: 'error', error_code: 'rate_limited', retry_after: 30});
    }
    return response({status: 'complete'});
  }, undefined, () => new Promise(resolve => { pausedRelease = resolve; }));
  const pausedPage = pausePaging.pretranslator.run(words);
  await new Promise(resolve => setImmediate(resolve));
  const changedPage = pausePaging.pretranslator.run([{text: 'koira', context: 'Koira.'}]);
  pausedRelease();
  await Promise.all([pausedPage, changedPage]);
  assert.deepEqual(pausePaging.requests.filter(r => r.body).map(r => r.body.text), ['Kissa', 'koira'], 'paging during cooldown discards the old word');

  let release;
  const paging = makePretranslator(async (url, body) => {
    if (url === '/translation/jobs') return response({job_id: body.text}, 202);
    if (url === '/translation/jobs/Kissa') await new Promise(resolve => { release = resolve; });
    return response({status: 'complete'});
  });
  const first = paging.pretranslator.run(words);
  await new Promise(resolve => setImmediate(resolve));
  const second = paging.pretranslator.run([{text: 'koira', context: 'Koira.'}]);
  release();
  await Promise.all([first, second]);
  const texts = paging.requests.filter(r => r.url === '/translation/jobs').map(r => r.body.text);
  assert.deepEqual(texts, ['Kissa', 'koira'], 'a new page replaces the waiting words after the current one finishes');

  const progress = [];
  const tracked = makePretranslator(async (url, body) => {
    if (url === '/translation/jobs') return response({job_id: body.text}, 202);
    return response({status: 'complete'});
  }, event => progress.push(`${event.done}/${event.total}`));
  await tracked.pretranslator.run(words);
  assert.deepEqual(progress, ['0/2', '1/2', '2/2'], 'each unique word on the page advances the progress');

  const pageProgress = [];
  let releaseProgress;
  const pagingProgress = makePretranslator(async (url) => {
    if (url === '/translation/jobs') return response({job_id: 'job'}, 202);
    if (pageProgress.length === 1) await new Promise(resolve => { releaseProgress = resolve; });
    return response({status: 'complete'});
  }, event => pageProgress.push(`${event.done}/${event.total}`));
  const oldPage = pagingProgress.pretranslator.run([words[0]]);
  await new Promise(resolve => setImmediate(resolve));
  const newPage = pagingProgress.pretranslator.run([{text: 'koira', context: 'Koira.'}, {text: 'koira', context: 'Iso koira.'}]);
  releaseProgress();
  await Promise.all([oldPage, newPage]);
  assert.deepEqual(pageProgress, ['0/1', '0/1', '1/1'], 'a new page starts over and ignores the word already in flight');

  console.log('Pretranslation checks passed');
}
checks().catch(error => { console.error(error); process.exitCode = 1; });
