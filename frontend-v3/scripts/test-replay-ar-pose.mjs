import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/services/replayArPose.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
  .outputText.replace("from 'three'", `from '${import.meta.resolve('three')}'`);
const { replayArPose, replayPoseBracket } = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const payload = (t = [0, 0, 0]) => ({
  R: [[1,0,0],[0,1,0],[0,0,1]], t, K: [1000,1000,960,540],
  imgWH: [1920,1080], chevrons: [], marker: false, metres_per_unit: 1,
});
const sample = (timestamp, ar_world = payload()) => ({ timestamp, ar_world,
  current_floor: 'floor1', method: 'PnP' });

test('1.5 second replay interpolates camera translation at midpoint', () => {
  const a = sample(0), b = sample(1.5, payload([-2,0,0]));
  const result = replayArPose(a, b, .75);
  assert.deepEqual(result.t, [-1, -0, -0]);
  assert.deepEqual(a.ar_world.t, [0,0,0]);
  assert.equal(result.chevrons, a.ar_world.chevrons);
});

test('rotation uses a rigid midpoint and preserves world camera centre', () => {
  const a = sample(0, payload([-2,0,0]));
  const b = sample(1.5, {...payload([0,0,2]), R: [[0,0,1],[0,1,0],[-1,0,0]]});
  const r = replayArPose(a, b, .75);
  const expected = Math.SQRT1_2;
  assert.ok(Math.abs(r.R[0][0] - expected) < 1e-10);
  assert.ok(Math.abs(r.R[0][2] - expected) < 1e-10);
  assert.ok(Math.abs(r.t[0] + 2*expected) < 1e-10);
  assert.ok(Math.abs(r.t[2] - 2*expected) < 1e-10);
});

test('bridges only plausible buffered gaps and rejects excessive gaps or floors', () => {
  const a = sample(0);
  assert.equal(replayArPose(a, null, .75), null);
  assert.ok(replayArPose(a, sample(3, payload([-3, 0, 0])), 1.5));
  assert.equal(replayArPose(a, sample(3, payload([-20, 0, 0])), 1.5), null);
  assert.equal(replayArPose(a, sample(3.2), .75), null);
  assert.equal(replayArPose(a, {...sample(1.5), current_floor:'floor2'}, .75), null);
  assert.equal(replayArPose(a, {...sample(1.5), method:'HOLD_LAST_FIX'}, .75), null);
});

test('does not use future fixes or a held pose as current camera', () => {
  assert.equal(replayArPose(sample(1.5), sample(3), 1), null);
  assert.equal(replayArPose({...sample(0), method:'HOLD_LAST_FIX'}, sample(1.5), .1), null);
  const a = sample(0);
  assert.equal(replayArPose(a, sample(1.5), 0), a.ar_world);
});

test('pose bracket skips HOLD events inside a buffered replay gap', () => {
  const left = sample(36.02);
  const held = {...sample(37.52), method: 'HOLD_LAST_FIX', ar_world: null};
  const right = sample(39.02, payload([-3, 0, 0]));
  const [a, b] = replayPoseBracket([left, held, right], 37.8);
  assert.equal(a, left);
  assert.equal(b, right);
  assert.ok(replayArPose(a, b, 37.8));
});
