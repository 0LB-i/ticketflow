import assert from 'node:assert/strict';
import { test } from 'node:test';

import { messageEvent, statusEvent } from './content.js';

const key = (extra = {}) => ({ remoteJid: '5511999990000@s.whatsapp.net', id: 'ABC', fromMe: false, ...extra });

test('texto de uma conversa individual', () => {
  const event = messageEvent('c1', {
    key: key(),
    message: { conversation: 'Bom dia' },
    pushName: 'Maria',
    messageTimestamp: 1763460000,
  });
  assert.deepEqual(event, {
    type: 'message',
    channel: 'c1',
    id: 'ABC',
    jid: '5511999990000@s.whatsapp.net',
    from_me: false,
    sender: '5511999990000@s.whatsapp.net',
    push_name: 'Maria',
    ts: 1763460000,
    history: false,
    file_name: null,
    mime: null,
    size: null,
    status: null,
    kind: 'text',
    text: 'Bom dia',
  });
});

test('no grupo, quem mandou é o participante (pelo número, quando há o LID)', () => {
  const event = messageEvent('c1', {
    key: key({ remoteJid: '1203630@g.us', participant: '123@lid', participantAlt: '5511888880000@s.whatsapp.net' }),
    message: { extendedTextMessage: { text: 'Oi, grupo' } },
  });
  assert.equal(event.jid, '1203630@g.us');
  assert.equal(event.sender, '5511888880000@s.whatsapp.net');
  assert.equal(event.text, 'Oi, grupo');
});

test('conversa pelo LID vira a do número', () => {
  const event = messageEvent('c1', {
    key: key({ remoteJid: '999@lid', remoteJidAlt: '5511777770000@s.whatsapp.net' }),
    message: { conversation: 'x' },
  });
  assert.equal(event.jid, '5511777770000@s.whatsapp.net');
});

test('mensagem nossa (mandada pelo celular ou por aqui) não tem remetente', () => {
  const event = messageEvent('c1', { key: key({ fromMe: true }), message: { conversation: 'x' } }, { history: true });
  assert.equal(event.from_me, true);
  assert.equal(event.sender, null);
  assert.equal(event.history, true);
});

test('mídia: o tipo e a legenda', () => {
  const kinds = [
    [{ imageMessage: { caption: 'foto' } }, 'image', 'foto'],
    [{ videoMessage: {} }, 'video', null],
    [{ audioMessage: { ptt: true } }, 'voice', null],
    [{ audioMessage: {} }, 'audio', null],
    [{ stickerMessage: {} }, 'sticker', null],
  ];
  for (const [message, kind, text] of kinds) {
    const event = messageEvent('c1', { key: key(), message });
    assert.equal(event.kind, kind);
    assert.equal(event.text, text);
  }
  const doc = messageEvent('c1', {
    key: key(),
    message: { documentWithCaptionMessage: { message: { documentMessage: { fileName: 'nota.pdf', caption: 'segue' } } } },
  });
  assert.equal(doc.kind, 'document');
  assert.equal(doc.file_name, 'nota.pdf');
  assert.equal(doc.text, 'segue');
});

test('ignora status, canais, avisos do protocolo e reações', () => {
  assert.equal(messageEvent('c1', { key: key({ remoteJid: 'status@broadcast' }), message: { conversation: 'x' } }), null);
  assert.equal(messageEvent('c1', { key: key({ remoteJid: '1@newsletter' }), message: { conversation: 'x' } }), null);
  assert.equal(messageEvent('c1', { key: key(), message: { protocolMessage: {} } }), null);
  assert.equal(messageEvent('c1', { key: key(), message: { reactionMessage: { text: '👍' } } }), null);
  assert.equal(messageEvent('c1', { key: key(), message: null }), null);
});

test('mídia: o tipo e o tamanho do arquivo para baixar', () => {
  const event = messageEvent('c1', {
    key: key(),
    message: { imageMessage: { mimetype: 'image/jpeg', fileLength: { toNumber: () => 2048 } } },
  });
  assert.equal(event.mime, 'image/jpeg');
  assert.equal(event.size, 2048);
});

test('ticks: a mudança de estado das nossas mensagens', () => {
  const nossa = key({ fromMe: true, remoteJid: '999@lid', remoteJidAlt: '5511777770000@s.whatsapp.net' });
  assert.deepEqual(statusEvent('c1', { key: nossa, update: { status: 3 } }), {
    type: 'status',
    channel: 'c1',
    jid: '5511777770000@s.whatsapp.net',
    id: 'ABC',
    status: 'delivered',
  });
  assert.equal(statusEvent('c1', { key: nossa, update: { status: 4 } }).status, 'read');
  assert.equal(statusEvent('c1', { key: key(), update: { status: 4 } }), null); // a do contato
  assert.equal(statusEvent('c1', { key: nossa, update: {} }), null);
  const doCelular = messageEvent('c1', { key: nossa, message: { conversation: 'x' }, status: 2 });
  assert.equal(doCelular.status, 'sent');
});
