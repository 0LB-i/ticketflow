import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { test } from 'node:test';

import { openQueue } from './queue.js';

test('os eventos ficam até a confirmação e sobrevivem a reabrir a fila', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'fila-'));
  try {
    const file = path.join(dir, 'queue.sqlite');
    let queue = openQueue(file);
    queue.push({ type: 'a' }, { type: 'b' });
    queue.push({ type: 'c' });
    assert.deepEqual(queue.read(0, 10).map((e) => e.type), ['a', 'b', 'c']);
    assert.deepEqual(queue.read(1, 10).map((e) => e.type), ['b', 'c']);
    queue.ack(2);
    queue.close();

    queue = openQueue(file);
    const rest = queue.read(0, 10);
    assert.deepEqual(rest.map((e) => [e.seq, e.type]), [[3, 'c']]);
    queue.close();
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('wait() acorda quando chega um evento', async () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'fila-'));
  try {
    const queue = openQueue(path.join(dir, 'queue.sqlite'));
    const started = Date.now();
    setTimeout(() => queue.push({ type: 'x' }), 50);
    await queue.wait(5000);
    assert.ok(Date.now() - started < 2000);
    assert.equal(queue.read(0, 10).length, 1);
    queue.close();
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
