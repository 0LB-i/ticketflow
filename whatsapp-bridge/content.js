// Converte uma mensagem da Baileys no evento simples que o TicketFlow grava. Puro (sem socket),
// para os testes (content.test.js).

import { getContentType, jidNormalizedUser, normalizeMessageContent } from '@whiskeysockets/baileys';

// Conversas que não são de ninguém: status, canais e listas de transmissão.
function ignoredJid(jid) {
  return jid === 'status@broadcast' || jid.endsWith('@newsletter') || jid.endsWith('@broadcast');
}

// O número de telefone quando a Baileys o conhece: com os LIDs (identificadores sem o número), o
// mesmo contato pode chegar de um jeito ou de outro, e a conversa precisa ser uma só.
export function preferPhone(jid, alt) {
  if (!jid) return null;
  if (jid.endsWith('@lid') && alt) return jidNormalizedUser(alt);
  return jidNormalizedUser(jid);
}

function timestamp(value) {
  if (value && typeof value === 'object' && typeof value.toNumber === 'function') return value.toNumber();
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : Math.floor(Date.now() / 1000);
}

// O tipo e o tamanho do arquivo, nas mensagens com mídia (a ponte baixa depois).
function media(inner) {
  const size = Number(inner?.fileLength?.toNumber?.() ?? inner?.fileLength);
  return { mime: inner?.mimetype || null, size: Number.isFinite(size) && size > 0 ? size : null };
}

// Tipo e texto de cada conteúdo; nas mídias, a legenda e o tipo e o tamanho do arquivo.
function describe(content) {
  const type = getContentType(content);
  const inner = type ? content[type] : null;
  switch (type) {
    case 'conversation':
      return { kind: 'text', text: content.conversation };
    case 'extendedTextMessage':
      return { kind: 'text', text: inner.text };
    case 'imageMessage':
      return { kind: 'image', text: inner.caption || null, ...media(inner) };
    case 'videoMessage':
      return { kind: inner.gifPlayback ? 'gif' : 'video', text: inner.caption || null, ...media(inner) };
    case 'audioMessage':
      return { kind: inner.ptt ? 'voice' : 'audio', text: null, ...media(inner) };
    case 'documentMessage':
      return { kind: 'document', text: inner.caption || null, file_name: inner.fileName || null, ...media(inner) };
    case 'documentWithCaptionMessage':
      return describe(inner.message || {});
    case 'stickerMessage':
      return { kind: 'sticker', text: null, ...media(inner) };
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
    mime: null,
    size: null,
    // A nossa mandada pelo celular já chega com o estado (os ticks).
    status: fromMe ? statusName(msg.status) : null,
    ...described,
  };
}

// Os tipos que têm arquivo para baixar.
export const MEDIA_KINDS = new Set(['image', 'video', 'gif', 'audio', 'voice', 'document', 'sticker']);

// O estado de uma mensagem nossa (proto.WebMessageInfo.Status) nos nomes do TicketFlow.
export function statusName(value) {
  switch (Number(value)) {
    case 2:
      return 'sent'; // SERVER_ACK: chegou ao servidor (✓)
    case 3:
      return 'delivered'; // DELIVERY_ACK: chegou ao celular (✓✓)
    case 4:
    case 5:
      return 'read'; // READ, PLAYED: lida ou ouvida (✓✓ azul)
    default:
      return null;
  }
}

// A mudança de estado de uma mensagem nossa (messages.update), para os ticks.
export function statusEvent(channel, { key, update }) {
  if (!key?.fromMe || !key.id || !key.remoteJid || ignoredJid(key.remoteJid)) return null;
  const status = statusName(update?.status);
  if (!status) return null;
  return { type: 'status', channel, jid: preferPhone(key.remoteJid, key.remoteJidAlt), id: key.id, status };
}

export function isGroup(jid) {
  return typeof jid === 'string' && jid.endsWith('@g.us');
}
