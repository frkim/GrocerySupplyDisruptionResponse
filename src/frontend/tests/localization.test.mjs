import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import ts from 'typescript';

const temporary = await mkdtemp(join(tmpdir(), 'grocery-locale-tests-'));
const output = join(temporary, 'localization.mjs');
await build({
  entryPoints: ['src/lib/localization.ts'], bundle: true, platform: 'node',
  format: 'esm', outfile: output, logLevel: 'silent',
});
const { TranslationStore, applyLanguage, getLocale, isLanguage, readLanguagePreference } =
  await import(pathToFileURL(output).href);
after(async () => { await rm(temporary, { recursive: true, force: true }); });

const pause = (ms = 60) => new Promise((resolve) => setTimeout(resolve, ms));
async function settled(store) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (!store.pending) return;
    await pause(10);
  }
  assert.fail('Translations did not settle.');
}

test('all language catalogs have identical keys and placeholders', async () => {
  const catalogs = await Promise.all(['fr', 'de', 'es'].map(async (language) =>
    JSON.parse(await readFile(resolve(`../../data/locales/${language}.json`), 'utf8'))));
  const keys = Object.keys(catalogs[0]).sort();
  assert.ok(keys.length > 150, 'Catalog must include the entire interface and reference content.');
  const placeholders = (value) => (value.match(/\{\w+\}/g) ?? []).sort();
  for (const catalog of catalogs) {
    assert.deepEqual(Object.keys(catalog).sort(), keys);
    for (const [source, translated] of Object.entries(catalog)) {
      assert.equal(typeof translated, 'string');
      assert.ok(translated.trim(), source);
      assert.deepEqual(placeholders(translated), placeholders(source), source);
    }
  }
});

test('every literal interface translation has a catalog entry in all languages', async () => {
  const catalogs = await Promise.all(['fr', 'de', 'es'].map(async (language) => [
    language, JSON.parse(await readFile(resolve(`../../data/locales/${language}.json`), 'utf8')),
  ]));
  const files = (await readdir('src/components')).filter((file) => file.endsWith('.tsx'));
  for (const file of files) {
    const tree = ts.createSourceFile(file, await readFile(`src/components/${file}`, 'utf8'),
      ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    function visit(node) {
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)
        && ['t', 'text'].includes(node.expression.text)
        && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) {
        for (const [language, catalog] of catalogs) {
          assert.ok(Object.hasOwn(catalog, node.arguments[0].text),
            `${language}: missing "${node.arguments[0].text}" in ${file}`);
        }
      }
      ts.forEachChild(node, visit);
    }
    visit(tree);
  }
});

test('known labels, interpolation, preference and locales are localized without a request', () => {
  const store = new TranslationStore('fr', async () => { assert.fail('Known labels must be offline.'); });
  assert.equal(store.t('Output'), 'Sortie');
  assert.ok(!store.t('{count} keys', { count: 12 }).includes('keys'));
  assert.equal(getLocale(), 'fr-FR');
  store.setLanguage('de');
  assert.equal(store.t('Output'), 'Ausgabe');
  assert.equal(getLocale(), 'de-DE');
  store.setLanguage('es');
  assert.equal(store.t('Output'), 'Salida');
  store.setLanguage('en');
  assert.equal(store.t('Output'), 'Output');
  assert.equal(store.text('Some uncatalogued business narrative.'), 'Some uncatalogued business narrative.');
  assert.equal(store.pending, false);
  assert.equal(isLanguage('GER'), false);
  const previous = globalThis.document;
  try {
    globalThis.document = { cookie: 'unrelated=1; gsdr-language=fr', documentElement: { lang: 'en' } };
    assert.equal(readLanguagePreference(), 'fr');
    applyLanguage('fr');
    assert.equal(document.documentElement.lang, 'fr');
    assert.ok(document.title.includes('approvisionnement'));
    document.cookie = 'gsdr-language=bad';
    assert.equal(readLanguagePreference(), 'en');
  } finally {
    if (previous === undefined) delete globalThis.document;
    else globalThis.document = previous;
    store.pause();
  }
});

test('dynamic visible text is batched, deduplicated, cached and translated', async () => {
  const calls = [];
  const store = new TranslationStore('fr', async (language, texts) => {
    calls.push({ language, texts });
    return texts.map((text) => `traduit:${text}`);
  });
  const source = 'A new supplier offers additional capacity today.';
  assert.equal(store.text(source), source);
  store.text(source);
  store.text('Another fresh report arrived this morning.');
  await settled(store);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].texts.length, 2);
  assert.equal(store.text(source), `traduit:${source}`);
  assert.equal(store.text(`  ${source}\n`), `  traduit:${source}\n`);
  await pause();
  assert.equal(calls.length, 1);
  store.pause();
});

test('display JSON translates prose but never changes source values, IDs, keys or decision payloads', async () => {
  const calls = [];
  const store = new TranslationStore('fr', async (_, texts) => {
    calls.push(...texts);
    return texts.map((text) => `traduit:${text}`);
  });
  const original = {
    optionId: 'A', runId: 'run-123', supplierId: 'SUP-004', impactedSkus: ['SKU-EGG-01'],
    costEur: 1200, confidence: 0.92, approved: false,
    title: 'A new emergency sourcing option.',
    actions: ['Obtain additional certified supply.'],
    url: 'https://example.invalid/source', toolName: 'get_inventory', approver: 'Jane Doe',
  };
  const unchanged = JSON.stringify(original);
  store.json(original);
  await settled(store);
  const display = store.json(original);
  assert.ok(display.includes('traduit:A new emergency sourcing option.'));
  assert.ok(display.includes('SUP-004'));
  assert.ok(display.includes('SKU-EGG-01'));
  assert.ok(display.includes('1200'));
  assert.ok(display.includes('0.92'));
  assert.ok(display.includes('false'));
  for (const identity of ['A', 'run-123', 'SUP-004', 'SKU-EGG-01', 'get_inventory', 'Jane Doe']) {
    assert.ok(!calls.includes(identity), `Identity ${identity} must never reach translation.`);
  }
  assert.equal(JSON.stringify(original), unchanged);
  assert.equal(original.optionId, 'A');
  store.setLanguage('en');
  assert.deepEqual(JSON.parse(store.json(original)), original);
  store.pause();
});

test('language switches ignore stale responses and never mix cached languages', async () => {
  let finishFrench;
  const store = new TranslationStore('fr', (language, texts) => {
    if (language === 'fr') return new Promise((resolve) => { finishFrench = resolve; });
    return Promise.resolve(texts.map((text) => `de:${text}`));
  });
  const source = 'A distinct live narrative.';
  store.text(source);
  await pause();
  store.setLanguage('de');
  store.text(source);
  finishFrench(['This stale French response must not appear.']);
  await settled(store);
  assert.equal(store.text(source), `de:${source}`);
  store.setLanguage('en');
  assert.equal(store.text(source), source);
  store.pause();
});

test('sustained failures are explicit, stop automatic requests and support deliberate retry', async () => {
  let calls = 0;
  let healthy = false;
  const store = new TranslationStore('es', async (_, texts) => {
    calls += 1;
    if (!healthy) throw new Error('Simulated translation service outage.');
    return texts.map((text) => `es:${text}`);
  });
  const source = 'A live report that is not in the catalog.';
  store.text(source);
  await settled(store);
  assert.equal(store.error, 'Translation unavailable. Showing original text.');
  assert.equal(store.text(source), source);
  const attempts = calls;
  assert.ok(attempts >= 3, 'Transient failures must be retried before giving up.');
  store.text('A second report while the service is unavailable.');
  await pause();
  assert.equal(calls, attempts, 'A confirmed outage must stop automatic requests.');
  healthy = true;
  store.retry();
  await settled(store);
  assert.equal(store.error, null);
  assert.equal(store.text(source), `es:${source}`);
  assert.equal(calls, attempts + 1);
  store.pause();
});

test('large batches respect API limits and large prose remains complete', async () => {
  const calls = [];
  const store = new TranslationStore('fr', async (_, texts) => {
    calls.push(texts);
    return texts.map((text) => `fr:${text}`);
  });
  for (let index = 0; index < 55; index += 1) store.text(`Distinct business report number ${index}.`);
  const long = 'Long unfamiliar narrative with complete words. '.repeat(600);
  store.text(long);
  await settled(store);
  for (const texts of calls) {
    assert.ok(texts.length <= 24);
    assert.ok(texts.every((text) => text.length <= 12000));
    assert.ok(texts.reduce((total, text) => total + text.length, 0) <= 40000);
  }
  assert.equal(store.text(long).replaceAll('fr:', ''), long);
  store.pause();
});

test('StrictMode-style pause/resume does not strand queued translations', async () => {
  const store = new TranslationStore('fr', async (_, texts) => texts.map((text) => `fr:${text}`));
  const source = 'Queued translation before effect cleanup.';
  store.text(source);
  store.pause();
  store.resume();
  await settled(store);
  assert.equal(store.text(source), `fr:${source}`);
  store.pause();
});

test('one rejected batch never strands the texts queued behind it', async () => {
  const calls = [];
  const store = new TranslationStore('fr', async (_, texts) => {
    calls.push(texts);
    if (calls.length === 1) throw new Error('Simulated rejected batch.');
    return texts.map((text) => `fr:${text}`);
  });
  const sources = Array.from({ length: 30 }, (_, index) => `Live mitigation scenario ${index} narrative.`);
  sources.forEach((source) => store.text(source));
  await settled(store);
  for (const source of sources) {
    assert.equal(store.text(source), `fr:${source}`, `${source} must not stay in English.`);
  }
  assert.equal(store.error, null);
  store.pause();
});

test('texts the provider cannot translate are retried alone and never cached as English', async () => {
  const calls = [];
  let recovered = false;
  const store = new TranslationStore('fr', async (_, texts) => {
    calls.push(texts);
    const translations = texts.map((text) => `fr:${text}`);
    if (recovered) return { translations };
    recovered = true;
    return { translations: texts.map((text, index) => (index === 1 ? text : `fr:${text}`)),
      untranslated: [1] };
  });
  const sources = ['A first live narrative.', 'A rejected live narrative.', 'A third live narrative.'];
  sources.forEach((source) => store.text(source));
  await settled(store);
  assert.deepEqual(calls[0], sources);
  assert.deepEqual(calls[1], ['A rejected live narrative.'], 'Rejected text must be isolated.');
  for (const source of sources) assert.equal(store.text(source), `fr:${source}`);
  assert.equal(store.error, null);
  store.pause();
});

test('a text the provider always rejects is reported without blocking the rest', async () => {
  const store = new TranslationStore('fr', async (_, texts) => ({
    translations: texts.map((text) => (text.startsWith('Rejected') ? text : `fr:${text}`)),
    untranslated: texts.flatMap((text, index) => (text.startsWith('Rejected') ? [index] : [])),
  }));
  store.text('Rejected live narrative with protected tokens.');
  store.text('A translatable live narrative.');
  await settled(store);
  assert.equal(store.text('A translatable live narrative.'), 'fr:A translatable live narrative.');
  assert.equal(store.text('Rejected live narrative with protected tokens.'),
    'Rejected live narrative with protected tokens.');
  assert.equal(store.error, 'Translation unavailable. Showing original text.');
  store.pause();
});

test('slow agent output translates over several concurrent requests', async () => {
  let inFlight = 0;
  let peak = 0;
  const calls = [];
  const store = new TranslationStore('fr', async (_, texts) => {
    inFlight += 1;
    peak = Math.max(peak, inFlight);
    calls.push(texts);
    await pause(40);
    inFlight -= 1;
    return texts.map((text) => `fr:${text}`);
  });
  const sources = Array.from({ length: 120 }, (_, index) =>
    `Execution detail narrative number ${index} describing the agent output in full. `.repeat(6));
  sources.forEach((source) => store.text(source));
  await settled(store);
  assert.ok(peak > 1 && peak <= 4, `Expected bounded concurrency, saw ${peak}.`);
  for (const texts of calls) {
    assert.ok(texts.length === 1
      || texts.reduce((total, text) => total + text.length, 0) <= 4000);
  }
  for (const source of sources) assert.equal(store.text(source), `fr:${source}`);
  store.pause();
});

test('prefetched agent output is translated before display without a translating status', async () => {
  const calls = [];
  const store = new TranslationStore('fr', async (_, texts) => {
    calls.push(texts);
    return texts.map((text) => `fr:${text}`);
  });
  const narrative = 'Prefetched narrative about the supplier delay.';
  const structured = { summary: 'Prefetched structured summary.', optionId: 'OPT-A' };
  store.prefetch([narrative, structured, undefined, null]);
  assert.equal(store.pending, false, 'Background prefetch must not show a translating status.');
  await pause(150);
  const sent = calls.flat();
  assert.ok(sent.includes(narrative));
  assert.ok(sent.includes('Prefetched structured summary.'));
  assert.ok(!sent.includes('OPT-A'), 'Identity fields are never sent.');
  const requests = calls.length;
  assert.equal(store.text(narrative), `fr:${narrative}`);
  assert.ok(Object.values(JSON.parse(store.json(structured)))
    .includes('fr:Prefetched structured summary.'));
  await pause(100);
  assert.equal(calls.length, requests, 'Opening prefetched content needs no new request.');
  store.pause();
});

test('visible text is translated ahead of queued prefetch', async () => {
  const calls = [];
  const store = new TranslationStore('fr', async (_, texts) => {
    calls.push(texts);
    return texts.map((text) => `fr:${text}`);
  });
  store.prefetch(['Background narrative one.', 'Background narrative two.']);
  store.text('Visible narrative on screen.');
  store.text('Background narrative two.');
  await settled(store);
  await pause(150);
  assert.deepEqual(calls[0], ['Visible narrative on screen.', 'Background narrative two.']);
  assert.deepEqual(calls.flat().sort(), [
    'Background narrative one.', 'Background narrative two.', 'Visible narrative on screen.',
  ]);
  store.pause();
});

test('prefetch in English sends no request', async () => {
  const store = new TranslationStore('en', async () => assert.fail('English needs no translation.'));
  store.prefetch(['An English narrative.', { summary: 'English summary.' }]);
  await pause(100);
  store.pause();
});

test('prefetch keeps one request slot free for visible text', async () => {
  let inFlight = 0;
  let peak = 0;
  const store = new TranslationStore('fr', async (_, texts) => {
    inFlight += 1;
    peak = Math.max(peak, inFlight);
    await pause(40);
    inFlight -= 1;
    return texts.map((text) => `fr:${text}`);
  });
  store.prefetch(Array.from({ length: 40 }, (_, index) =>
    `Background agent narrative number ${index}. `.repeat(100)));
  await pause(600);
  assert.ok(peak >= 1 && peak <= 3, `Prefetch used ${peak} slots.`);
  store.pause();
});
test('unparsable tool payloads are shown as raw data instead of being translated', async () => {
  const calls = [];
  const store = new TranslationStore('fr', async (_, texts) => {
    calls.push(texts);
    return texts.map((text) => `fr:${text}`);
  });
  const truncated = '[{"id": "INV-DC-NORTH-01", "partitionKey": "inventory", "region": "NORTH"';
  const wrapped = 'RESPONSE OPTIONS:\n[{"optionId": "A", "title": "Emergency Import"}';
  assert.equal(store.json(truncated), truncated);
  assert.equal(store.json(wrapped), wrapped);
  assert.equal(store.text('A plain sentence about the shortage.'),
    'A plain sentence about the shortage.');
  await settled(store);
  assert.deepEqual(calls.flat(), ['A plain sentence about the shortage.']);
  store.pause();
});