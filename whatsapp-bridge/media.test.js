import assert from 'node:assert/strict';
import { test } from 'node:test';

import { diskOk, incomingPath, mediaContent, resolveInside } from './media.js';

test('caminhos vindos do TicketFlow ficam dentro da pasta de mídia', () => {
  assert.equal(resolveInside('/m', 'out/c1/a.pdf'), '/m/out/c1/a.pdf');
  assert.equal(resolveInside('/m', '../sessions/x/creds.json'), null);
  assert.equal(resolveInside('/m', '/etc/passwd'), null);
  assert.equal(resolveInside('/m', ''), null);
  assert.equal(resolveInside('/m', 'out/../../x'), null);
});

test('o arquivo que chega leva o id, sem caracteres estranhos', () => {
  assert.equal(incomingPath('c1', '3EB0/../X'), 'in/c1/3EB0____X');
});

test('reserva de disco: abaixo de 10% livre, não baixa', () => {
  assert.equal(diskOk('/', () => ({ bavail: 20, blocks: 100 })), true);
  assert.equal(diskOk('/', () => ({ bavail: 5, blocks: 100 })), false);
  assert.equal(diskOk('/', () => { throw new Error('x'); }), false);
});

test('o conteúdo de envio de cada tipo', () => {
  const base = { file: '/m/a', fileName: 'a', caption: '*Ana:*' };
  assert.deepEqual(mediaContent({ ...base, kind: 'image', mime: 'image/png' }), {
    image: { url: '/m/a' },
    mimetype: 'image/png',
    caption: '*Ana:*',
  });
  assert.ok(mediaContent({ ...base, kind: 'image', mime: 'image/gif' }).document);
  assert.ok(mediaContent({ ...base, kind: 'video', mime: 'video/mp4' }).video);
  assert.deepEqual(mediaContent({ ...base, kind: 'audio', mime: 'audio/mpeg' }), {
    audio: { url: '/m/a' },
    mimetype: 'audio/mpeg',
  });
  const doc = mediaContent({ ...base, kind: 'document', mime: null, fileName: 'nota.pdf' });
  assert.equal(doc.fileName, 'nota.pdf');
  assert.equal(doc.mimetype, 'application/octet-stream');
});
