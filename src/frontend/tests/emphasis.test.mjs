import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { build } from 'esbuild';

const temporary = await mkdtemp(join(tmpdir(), 'grocery-emphasis-tests-'));
const output = join(temporary, 'emphasis.mjs');
await build({
  entryPoints: ['src/lib/emphasis.ts'], bundle: true, platform: 'node',
  format: 'esm', outfile: output, logLevel: 'silent',
});
const { emphasize } = await import(pathToFileURL(output).href);
after(async () => { await rm(temporary, { recursive: true, force: true }); });

const strong = (text) => emphasize(text).filter((s) => s.strong).map((s) => s.text);

test('segments always reassemble into the original text', () => {
  const source = 'Unmitigated exposure is approximately EUR 1,234,567, comprising 4,200 cases at 35.0% shortfall.';
  assert.equal(emphasize(source).map((s) => s.text).join(''), source);
  assert.deepEqual(emphasize(''), []);
  assert.deepEqual(emphasize(undefined), []);
});

test('bolds money, percentages, quantities, options and critical words', () => {
  assert.deepEqual(
    strong('Fresh eggs is short by 35.0% against a demand surge of 22.5%. Distribution centres hold 12,400 cases at 3.2 days of average cover.'),
    ['35.0%', '22.5%', '12,400 cases', '3.2 days'],
  );
  assert.deepEqual(
    strong('Unmitigated four-week exposure is approximately EUR 1,234,567, comprising EUR 900,000 of lost margin.'),
    ['EUR 1,234,567', 'EUR 900,000'],
  );
  assert.deepEqual(
    strong('Option B was approved by the executive gate. Limits take effect immediately; decision window under twenty-four hours.'),
    ['Option B', 'approved', 'immediately', 'twenty-four hours'],
  );
});

test('works on translated French text with narrow no-break spaces', () => {
  assert.deepEqual(
    strong('L’exposition atteint environ 1\u202f234\u202f567\u00a0EUR, soit 35,0\u00a0% de pénurie et 4\u202f200 caisses. L’option B est approuvée.'),
    ['1\u202f234\u202f567\u00a0EUR', '35,0\u00a0%', '4\u202f200 caisses', 'option B', 'approuvée'],
  );
});

test('does not bold words that merely contain a keyword or plain counts', () => {
  assert.deepEqual(strong('Uncritical review of 4 stores and 12 products, optional adoption.'), []);
  assert.deepEqual(strong('Options rank A, B, C, D.'), []);
});

test('explicit Markdown bold from live models takes precedence over heuristics', () => {
  const segments = emphasize('Shortfall is 35% and the **decision is due in 24 hours**.');
  assert.deepEqual(segments, [
    { text: 'Shortfall is 35% and the ', strong: false },
    { text: 'decision is due in 24 hours', strong: true },
    { text: '.', strong: false },
  ]);
});
