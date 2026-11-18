// Converte uma mensagem da Baileys no evento simples que o TicketFlow grava. Puro (sem socket),
// para os testes (content.test.js).

import { areJidsSameUser, getContentType, jidNormalizedUser, normalizeMessageContent } from '@whiskeysockets/baileys';

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
    // A nossa mandada pelo celular (ou do histórico) já chega com o estado (os ticks); no
    // histórico, às vezes só nas confirmações de quem recebeu (userReceipt).
    status: fromMe ? statusName(msg.status) ?? receiptsStatus(msg.userReceipt) : null,
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

// Uma confirmação do WhatsApp (o nó <receipt>), lida direto, sem o filtro da Baileys: ela repassa
// como "lida" também as leituras dos nossos próprios aparelhos (o celular sincronizando a mensagem
// mandada daqui), e o tick ficava azul antes de o destinatário ler. Fica só a de outra pessoa:
// sem tipo = entregue; read ou played = lida. Os ids são das mensagens a que ela se refere.
export function receiptOf(node, me = []) {
  const { from, participant, type } = node?.attrs || {};
  if (!from || ignoredJid(from) || !node.attrs.id) return null;
  const status = type === undefined || type === '' ? 'delivered' : ['read', 'played'].includes(type) ? 'read' : null;
  if (!status) return null; // read-self, played-self, sender, retry, inactive…
  const group = from.endsWith('@g.us');
  const reader = group ? participant : from;
  if (!reader || me.some((jid) => jid && areJidsSameUser(reader, jid))) return null;
  const ids = [node.attrs.id];
  const list = Array.isArray(node.content) ? node.content.find((c) => c?.tag === 'list') : null;
  for (const item of Array.isArray(list?.content) ? list.content : []) {
    if (item?.tag === 'item' && item.attrs?.id) ids.push(item.attrs.id);
  }
  return { jid: jidNormalizedUser(from), group, reader: jidNormalizedUser(reader), status, ids };
}

// O estado pelas confirmações de quem recebeu: lida (ou ouvida) por alguém, ou só entregue.
function receiptsStatus(receipts) {
  if (!Array.isArray(receipts) || !receipts.length) return null;
  if (receipts.some((r) => Number(r?.readTimestamp) || Number(r?.playedTimestamp))) return 'read';
  if (receipts.some((r) => Number(r?.receiptTimestamp))) return 'delivered';
  return null;
}

export function isGroup(jid) {
  return typeof jid === 'string' && jid.endsWith('@g.us');
}
