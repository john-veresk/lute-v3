// node tests/javascript/test_pretranslate.cjs
// Unknown words are translated one at a time in the background.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const context = vm.createContext({});
vm.runInContext(fs.readFileSync('lute/static/js/pretranslate.js', 'utf8'), context);
const Pretranslator = vm.runInContext('Pretranslator', context);

const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});

function makePretranslator(reply) {
  const requests = [];
  let inFlight = 0;
  let maxInFlight = 0;
  const pretranslator = new Pretranslator({
    languageId: 1,
    wait: async () => {},
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
  console.log('Pretranslation checks passed');
}
checks().catch(error => { console.error(error); process.exitCode = 1; });
