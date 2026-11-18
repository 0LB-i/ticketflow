#!/usr/bin/env node
// Ponte entre o TicketFlow e o WhatsApp (ticketflow-whatsapp.service). Cada número ligado é um
// "canal" (o public_id do whatsapp_channels), com a sessão da Baileys em sessions/<id>. A ponte
// atende só num socket Unix dentro de WHATSAPP_DIR: quem fala com ela é o próprio TicketFlow,
// com o mesmo usuário do sistema (sem porta e sem senha). Rotas:
//
//   GET  /channels               estado de cada canal (e o QR code em SVG, durante o pareamento)
//   POST /channels/:id/start     conecta (sem sessão salva, gera o QR code)
//   POST /channels/:id/logout    desconecta o aparelho e apaga a sessão
//   POST /channels/:id/send      { jid, text, id } envia um texto com o id que o TicketFlow gerou
//   POST /channels/:id/send-media { jid, path, kind, mime, file_name, caption, id } envia um arquivo
//                                da pasta media (o caminho é relativo a ela)
//   GET  /events?after=N&wait=S  eventos depois de N (espera até S segundos se não houver)
//   POST /events/ack             { upto } o TicketFlow guardou até este evento
//
// A estrutura segue a ponte do Hermes Agent (NousResearch, licença MIT), com a fila em disco.

import { createServer } from 'node:http';
import { createWriteStream, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, unlinkSync } from 'node:fs';
import path from 'node:path';
import { pipeline } from 'node:stream/promises';

import makeWASocket, {
  DisconnectReason,
  downloadMediaMessage,
  jidNormalizedUser,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';
import pino from 'pino';
import QRCode from 'qrcode';

import { isGroup, MEDIA_KINDS, messageEvent, receiptEvent, statusEvent } from './content.js';
import { diskOk, HISTORY_MAX, incomingPath, makeSerialQueue, mediaContent, resolveInside } from './media.js';
import { openQueue } from './queue.js';

const DIR = process.env.WHATSAPP_DIR || '/var/lib/ticketflow/whatsapp';
const SESSIONS = path.join(DIR, 'sessions');
const SOCKET = path.join(DIR, 'bridge.sock');
const MEDIA = path.join(DIR, 'media');
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MAX_WAIT_S = 30;
const BATCH = 500;

const logger = pino({ level: process.env.WHATSAPP_LOG_LEVEL || 'warn' });
mkdirSync(SESSIONS, { recursive: true, mode: 0o700 });
mkdirSync(MEDIA, { recursive: true, mode: 0o750 });
const queue = openQueue(path.join(DIR, 'queue.sqlite'));
const channels = new Map(); // id → { sock, state, qr, phone, name, stopping, retries }
// Ids das mídias enviadas daqui: o arquivo já está na pasta media, não precisa baixar de novo.
const sentHere = new Set();

function log(event, fields = {}) {
  console.log(JSON.stringify({ event, ...fields }));
}

function connectionEvent(id, channel) {
  queue.push({ type: 'connection', channel: id, state: channel.state, phone: channel.phone, name: channel.name });
}

// Downloads da mídia que chega, um de cada vez e fora do caminho das mensagens: a mensagem aparece
// na hora, e o arquivo chega depois (evento `media`). Uma ponte reiniciada no meio perde os que
// estavam na fila (a mensagem fica com "mídia não baixada").
const downloads = makeSerialQueue((error) => log('erro_ao_baixar', { error: String(error) }));

function download(id, channel, msg, event) {
  if (!MEDIA_KINDS.has(event.kind)) return;
  if (event.history && (!event.size || event.size > HISTORY_MAX)) return;
  downloads(async () => {
    if (!diskOk(DIR)) {
      log('disco_quase_cheio', { channel: id });
      return;
    }
    const relative = incomingPath(id, event.id);
    const file = path.join(MEDIA, relative);
    mkdirSync(path.dirname(file), { recursive: true });
    const stream = await downloadMediaMessage(msg, 'stream', {}, {
      logger,
      reuploadRequest: channel.sock?.updateMediaMessage,
    });
    await pipeline(stream, createWriteStream(file));
    queue.push({
      type: 'media',
      channel: id,
      jid: event.jid,
      id: event.id,
      path: relative,
      mime: event.mime,
      size: statSync(file).size,
    });
  });
}

// Nome dos grupos: a mensagem não traz o assunto; pergunta uma vez e guarda.
async function groupName(channel, jid) {
  channel.groups ??= new Map();
  if (channel.groups.has(jid)) return channel.groups.get(jid);
  try {
    const meta = await channel.sock.groupMetadata(jid);
    channel.groups.set(jid, meta.subject || null);
    return meta.subject || null;
  } catch {
    return null;
  }
}

async function start(id) {
  const existing = channels.get(id);
  // Já tem um socket ativo (conectado, conectando ou mostrando o QR code).
  if (existing?.sock && !existing.stopping) return existing;
  const dir = path.join(SESSIONS, id);
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  const { state, saveCreds } = await useMultiFileAuthState(dir);
  const channel = existing ?? { state: 'connecting', qr: null, phone: null, name: null, retries: 0 };
  Object.assign(channel, { state: 'connecting', qr: null, stopping: false });
  channels.set(id, channel);

  const sock = makeWASocket({
    auth: state,
    logger,
    browser: ['TicketFlow', 'Chrome', '120.0'],
    // O histórico vem uma vez só, no pareamento: pede tudo o que o celular mandar.
    syncFullHistory: true,
    // O celular continua recebendo as notificações.
    markOnlineOnConnect: false,
    // Sem guardar as mensagens enviadas aqui: o suficiente para o reenvio da criptografia.
    getMessage: async () => ({ conversation: '' }),
  });
  channel.sock = sock;

  // A pasta pode ter sido apagada (passkey, QR code expirado): a gravação atrasada não derruba a ponte.
  sock.ev.on('creds.update', () => {
    saveCreds().catch((error) => log('erro_ao_gravar_sessao', { channel: id, error: String(error) }));
  });

  // Passkey: depois da leitura do QR code, o WhatsApp pode exigir a passkey da conta para ligar um
  // aparelho novo (o fluxo "Shortcake", desde junho de 2026). A Baileys ainda não sabe responder
  // (Baileys#2672): sem isso, o celular pede outra leitura e a conexão expira. A ponte para e a
  // tela explica. Numa sessão que já conectou, o pedido é ignorado, como no Hermes Agent.
  sock.ws.on('CB:notification', (node) => {
    const { type, from } = node?.attrs || {};
    if (type !== 'passkey_prologue_request' || !['s.whatsapp.net', '@s.whatsapp.net'].includes(from)) return;
    if (channel.sock !== sock || channel.state === 'connected') return;
    log('passkey_exigida', { channel: id });
    channel.stopping = true;
    channel.sock = null;
    channel.state = 'passkey_required';
    channel.qr = null;
    sock.end(undefined);
    rmSync(dir, { recursive: true, force: true });
    connectionEvent(id, channel);
  });

  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      channel.qr = qr;
      channel.state = 'pairing';
    }
    if (connection === 'open') {
      channel.qr = null;
      channel.state = 'connected';
      channel.retries = 0;
      channel.phone = sock.user?.id ? jidNormalizedUser(sock.user.id).split('@')[0] : null;
      channel.name = sock.user?.name || sock.user?.verifiedName || null;
      connectionEvent(id, channel);
      log('conectado', { channel: id });
    } else if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (channel.stopping || channel.sock !== sock) return;
      channel.sock = null; // este socket acabou; o próximo start() cria outro
      if (channel.state === 'pairing' && code === DisconnectReason.timedOut) {
        // Os QR codes acabaram sem ninguém ler: para aqui, e a tela volta a oferecer o Conectar
        // (sem isso, a ponte geraria QR codes para sempre).
        channel.state = 'new';
        channel.qr = null;
        rmSync(dir, { recursive: true, force: true });
        connectionEvent(id, channel);
        log('qrcode_expirado', { channel: id });
        return;
      }
      if (code === DisconnectReason.loggedOut) {
        // Desconectado pelo celular (Aparelhos conectados → Sair): a sessão não vale mais.
        channel.state = 'logged_out';
        channel.qr = null;
        rmSync(dir, { recursive: true, force: true });
        connectionEvent(id, channel);
        log('desconectado_pelo_celular', { channel: id });
        return;
      }
      channel.state = 'disconnected';
      channel.retries += 1;
      // 515: o WhatsApp pede para reconectar logo depois do pareamento.
      const delay = code === 515 ? 1000 : Math.min(60_000, 2000 * 2 ** Math.min(channel.retries, 5));
      log('reconectando', { channel: id, code, delay });
      setTimeout(() => {
        if (channel.stopping || channel.sock) return;
        start(id).catch((error) => log('erro_ao_reconectar', { channel: id, error: String(error) }));
      }, delay);
      // O 515 do pareamento não é uma queda: não avisa.
      if (code !== 515) connectionEvent(id, channel);
    }
  });

  sock.ev.on('messages.upsert', async ({ messages }) => {
    const events = [];
    const media = [];
    for (const msg of messages || []) {
      const event = messageEvent(id, msg);
      if (!event) continue;
      if (isGroup(event.jid)) event.chat_name = await groupName(channel, event.jid);
      events.push(event);
      // O que enviamos daqui o TicketFlow já tem; o resto (inclusive o do celular), baixa.
      if (!sentHere.has(event.id)) media.push([msg, event]);
    }
    queue.push(...events);
    for (const [msg, event] of media) download(id, channel, msg, event);
  });

  // Os ticks das nossas mensagens: entregue (✓✓) e lida (✓✓ azul).
  sock.ev.on('messages.update', (updates) => {
    queue.push(...(updates || []).map((u) => statusEvent(id, u)).filter(Boolean));
  });
  // No grupo, as confirmações vêm uma por participante.
  sock.ev.on('message-receipt.update', (receipts) => {
    queue.push(...(receipts || []).map((r) => receiptEvent(id, r)).filter(Boolean));
  });

  sock.ev.on('messaging-history.set', ({ chats, contacts, messages }) => {
    const names = [];
    for (const chat of chats || []) {
      if (chat.id && chat.name) names.push({ jid: jidNormalizedUser(chat.id), name: chat.name });
    }
    for (const contact of contacts || []) {
      const name = contact.name || contact.notify || contact.verifiedName;
      const jid = contact.phoneNumber || contact.id;
      if (jid && name) names.push({ jid: jidNormalizedUser(jid), name });
    }
    const events = [];
    const media = [];
    if (names.length) events.push({ type: 'names', channel: id, names });
    for (const msg of messages || []) {
      const event = messageEvent(id, msg, { history: true });
      if (!event) continue;
      events.push(event);
      media.push([msg, event]);
    }
    queue.push(...events);
    for (const [msg, event] of media) download(id, channel, msg, event);
    log('historico_recebido', { channel: id, mensagens: messages?.length || 0 });
  });

  sock.ev.on('groups.update', (updates) => {
    const names = [];
    for (const group of updates || []) {
      if (group.id && group.subject) {
        channel.groups?.set(group.id, group.subject);
        names.push({ jid: group.id, name: group.subject });
      }
    }
    if (names.length) queue.push({ type: 'names', channel: id, names });
  });

  return channel;
}

async function logout(id) {
  const channel = channels.get(id);
  if (channel) {
    channel.stopping = true;
    try {
      await channel.sock?.logout();
    } catch {
      // já estava desconectado: basta apagar a sessão
    }
    channel.sock?.end?.(undefined);
    channels.delete(id);
  }
  rmSync(path.join(SESSIONS, id), { recursive: true, force: true });
}

async function describeChannel(id, channel) {
  const qr_svg = channel.qr ? await QRCode.toString(channel.qr, { type: 'svg', margin: 1 }) : null;
  return { id, state: channel.state, phone: channel.phone, name: channel.name, qr_svg };
}

// HTTP ------------------------------------------------------------------------------------------

function send(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) });
  res.end(data);
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {};
}

async function handle(req, res) {
  const url = new URL(req.url, 'http://ponte');
  const parts = url.pathname.split('/').filter(Boolean);

  if (req.method === 'GET' && url.pathname === '/channels') {
    const list = await Promise.all([...channels].map(([id, channel]) => describeChannel(id, channel)));
    return send(res, 200, list);
  }
  if (req.method === 'GET' && url.pathname === '/events') {
    const after = Number(url.searchParams.get('after') || 0);
    const wait = Math.min(Number(url.searchParams.get('wait') || 0), MAX_WAIT_S);
    let events = queue.read(after, BATCH);
    if (!events.length && wait > 0) {
      await queue.wait(wait * 1000);
      events = queue.read(after, BATCH);
    }
    return send(res, 200, events);
  }
  if (req.method === 'POST' && url.pathname === '/events/ack') {
    const { upto } = await readJson(req);
    queue.ack(Number(upto) || 0);
    return send(res, 200, { ok: true });
  }
  if (parts[0] === 'channels' && parts.length === 3 && req.method === 'POST') {
    const [, id, action] = parts;
    if (!UUID.test(id)) return send(res, 404, { error: 'canal inválido' });
    if (action === 'start') {
      return send(res, 200, await describeChannel(id, await start(id)));
    }
    if (action === 'logout') {
      await logout(id);
      return send(res, 200, { ok: true });
    }
    if (action === 'send-media') {
      const channel = channels.get(id);
      if (!channel?.sock || channel.state !== 'connected') return send(res, 503, { error: 'desconectado' });
      const { jid, path: relative, kind, mime, file_name: fileName, caption, id: messageId } = await readJson(req);
      const file = resolveInside(MEDIA, relative);
      if (!jid || !file || !existsSync(file)) return send(res, 400, { error: 'arquivo inválido' });
      if (messageId) {
        sentHere.add(messageId);
        if (sentHere.size > 10_000) sentHere.delete(sentHere.values().next().value);
      }
      const content = mediaContent({ file, kind, mime, fileName, caption });
      const sent = await channel.sock.sendMessage(jid, content, messageId ? { messageId } : {});
      return send(res, 200, { id: sent?.key?.id ?? messageId });
    }
    if (action === 'send') {
      const channel = channels.get(id);
      if (!channel?.sock || channel.state !== 'connected') return send(res, 503, { error: 'desconectado' });
      const { jid, text, id: messageId } = await readJson(req);
      if (!jid || !text) return send(res, 400, { error: 'jid e text são obrigatórios' });
      const sent = await channel.sock.sendMessage(jid, { text }, messageId ? { messageId } : {});
      return send(res, 200, { id: sent?.key?.id ?? messageId });
    }
  }
  return send(res, 404, { error: 'não encontrado' });
}

const server = createServer((req, res) => {
  handle(req, res).catch((error) => {
    log('erro', { url: req.url, error: String(error) });
    if (!res.headersSent) send(res, 500, { error: String(error) });
  });
});
// O long-poll segura a resposta por até MAX_WAIT_S.
server.requestTimeout = (MAX_WAIT_S + 10) * 1000;

if (existsSync(SOCKET)) unlinkSync(SOCKET);
server.listen(SOCKET, () => log('ponte_iniciada', { socket: SOCKET }));

// Pareado: a sessão já tem o número (creds.me). Um pareamento abandonado no meio não volta sozinho.
function paired(id) {
  try {
    return Boolean(JSON.parse(readFileSync(path.join(SESSIONS, id, 'creds.json'), 'utf8')).me);
  } catch {
    return false;
  }
}

// Os números já pareados voltam sozinhos.
for (const id of readdirSync(SESSIONS)) {
  if (UUID.test(id) && paired(id)) {
    start(id).catch((error) => log('erro_ao_iniciar', { channel: id, error: String(error) }));
  }
}

process.on('unhandledRejection', (error) => log('erro_nao_tratado', { error: String(error) }));

function shutdown() {
  for (const channel of channels.values()) {
    channel.stopping = true;
    channel.sock?.end?.(undefined);
  }
  server.close();
  queue.close();
  process.exit(0);
}
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
