// Arquivos do chat, na pasta `media` da ponte (WHATSAPP_DIR/media), que o TicketFlow também lê e
// grava: `in/<canal>/<id>` o que chega, `out/<conversa>/…` o que os funcionários enviam. Os caminhos
// trocados com o TicketFlow são relativos a ela.

import { statfsSync } from 'node:fs';
import path from 'node:path';

// Abaixo disto de espaço livre, a ponte não baixa mais nada: disco cheio derruba o PostgreSQL, e os
// chamados param junto. A mensagem fica com "mídia não baixada".
export const MIN_FREE = 0.1;
// No histórico do pareamento, só as mídias pequenas (o resto ficaria baixando por horas).
export const HISTORY_MAX = 5 * 1024 * 1024;

export function diskOk(dir, statfs = statfsSync) {
  try {
    const { bavail, blocks } = statfs(dir);
    return blocks > 0 && bavail / blocks >= MIN_FREE;
  } catch {
    return false;
  }
}

// Caminho relativo vindo do TicketFlow: só dentro da pasta de mídia.
export function resolveInside(root, relative) {
  if (typeof relative !== 'string' || !relative || path.isAbsolute(relative)) return null;
  const full = path.resolve(root, relative);
  return full.startsWith(path.resolve(root) + path.sep) ? full : null;
}

// O nome do arquivo de uma mensagem que chega: o id do WhatsApp, só com letras e números.
export function incomingPath(channel, id) {
  return path.join('in', channel, String(id).replace(/[^A-Za-z0-9]/g, '_'));
}

// O conteúdo do sendMessage da Baileys para cada tipo. O GIF e o SVG vão como documento (o
// WhatsApp não mostra GIF como foto), e o áudio não leva legenda.
export function mediaContent({ file, kind, mime, fileName, caption }) {
  const media = { url: file };
  const text = caption || undefined;
  if (kind === 'image' && mime !== 'image/gif' && mime !== 'image/svg+xml') {
    return { image: media, mimetype: mime, caption: text };
  }
  if (kind === 'video') return { video: media, mimetype: mime, caption: text };
  if (kind === 'audio') return { audio: media, mimetype: mime };
  return { document: media, mimetype: mime || 'application/octet-stream', fileName, caption: text };
}

// Uma fila simples: os downloads um de cada vez, sem segurar as mensagens.
export function makeSerialQueue(onError) {
  let tail = Promise.resolve();
  return (job) => {
    tail = tail.then(job).catch(onError);
    return tail;
  };
}
