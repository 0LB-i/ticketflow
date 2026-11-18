// Converte uma mensagem da Baileys no evento simples que o TicketFlow grava. Puro (sem socket),
// para os testes (content.test.js).

import { getContentType, jidNormalizedUser, normalizeMessageContent } from '@whiskeysockets/baileys';

// Conversas que não são de ninguém: status, canais e listas de transmissão.
function ignoredJid(jid) {
  return jid === 'status@broadcast' || jid.endsWith('@newsletter') || jid.endsWith('@broadcast');
}

// O número de telefone quando a Baileys o conhece: com os LIDs (identificadores sem o número), o
// mesmo contato pode chegar de um jeito ou de outro, e a conversa precisa ser uma só.
function preferPhone(jid, alt) {
  if (!jid) return null;
  if (jid.endsWith('@lid') && alt) return jidNormalizedUser(alt);
  return jidNormalizedUser(jid);
}

function timestamp(value) {
  if (value && typeof value === 'object' && typeof value.toNumber === 'function') return value.toNumber();
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : Math.floor(Date.now() / 1000);
}

// Tipo e texto de cada conteúdo. Mídia: a fase 3 baixa o arquivo; por enquanto vai só a legenda.
function describe(content) {
  const type = getContentType(content);
  const inner = type ? content[type] : null;
  switch (type) {
    case 'conversation':
      return { kind: 'text', text: content.conversation };
    case 'extendedTextMessage':
      return { kind: 'text', text: inner.text };
    case 'imageMessage':
      return { kind: 'image', text: inner.caption || null };
    case 'videoMessage':
      return { kind: inner.gifPlayback ? 'gif' : 'video', text: inner.caption || null };
    case 'audioMessage':
      return { kind: inner.ptt ? 'voice' : 'audio', text: null };
    case 'documentMessage':
      return { kind: 'document', text: inner.caption || null, file_name: inner.fileName || null };
    case 'documentWithCaptionMessage':
      return describe(inner.message || {});
    case 'stickerMessage':
      return { kind: 'sticker', text: null };
    case 'locationMessage':
    case 'liveLocationMessage':
      return { kind: 'location', text: inner.name || inner.address || null };
    case 'contactMessage':
      return { kind: 'contact', text: inner.displayName || null };
    case 'contactsArrayMessage':
      return { kind: 'contact', text: inner.displayName || null };
    case 'pollCreationMessage':
    case 'pollCreationMessageV2':
    case 'pollCreationMessageV3':
      return { kind: 'poll', text: inner.name || null };
    // Avisos internos do protocolo (apagar, editar, chaves, reações): fases seguintes.
    case 'protocolMessage':
    case 'reactionMessage':
    case 'senderKeyDistributionMessage':
    case 'messageContextInfo':
    case undefined:
      return null;
    default:
      return { kind: 'other', text: null };
  }
}

export function messageEvent(channel, msg, { history = false } = {}) {
  const key = msg?.key;
  if (!key?.remoteJid || !key.id || ignoredJid(key.remoteJid)) return null;
  const content = normalizeMessageContent(msg.message);
  if (!content) return null;
  const described = describe(content);
  if (!described) return null;
  const jid = preferPhone(key.remoteJid, key.remoteJidAlt);
  const group = jid.endsWith('@g.us');
  const fromMe = Boolean(key.fromMe);
  return {
    type: 'message',
    channel,
    id: key.id,
    jid,
    from_me: fromMe,
    // Quem mandou no grupo; na conversa individual, o próprio contato (ou nós).
    sender: group ? preferPhone(key.participant, key.participantAlt) : fromMe ? null : jid,
    push_name: msg.pushName || null,
    ts: timestamp(msg.messageTimestamp),
    history,
    file_name: null,
    ...described,
  };
}

export function isGroup(jid) {
  return typeof jid === 'string' && jid.endsWith('@g.us');
}
