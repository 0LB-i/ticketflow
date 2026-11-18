// Fila de eventos em disco (SQLite do Node): a mensagem que chega fica gravada até o TicketFlow
// confirmar que a guardou (POST /events/ack). Se a ponte ou o TicketFlow caírem no meio, nada se
// perde: o próximo GET /events entrega de novo.

import { DatabaseSync } from 'node:sqlite';

export function openQueue(file) {
  const db = new DatabaseSync(file);
  db.exec(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
  `);
  const insert = db.prepare('INSERT INTO events (body) VALUES (?)');
  const select = db.prepare('SELECT seq, body FROM events WHERE seq > ? ORDER BY seq LIMIT ?');
  const remove = db.prepare('DELETE FROM events WHERE seq <= ?');
  const waiters = new Set();

  function wake() {
    for (const resolve of waiters) resolve();
    waiters.clear();
  }

  return {
    // Vários eventos numa transação só (o histórico chega em lotes de milhares).
    push(...events) {
      if (!events.length) return;
      db.exec('BEGIN');
      try {
        for (const event of events) insert.run(JSON.stringify(event));
        db.exec('COMMIT');
      } catch (error) {
        db.exec('ROLLBACK');
        throw error;
      }
      wake();
    },
    read(after, limit) {
      return select.all(after, limit).map(({ seq, body }) => ({ seq, ...JSON.parse(body) }));
    },
    // Espera até `ms` por um evento novo (long-poll do GET /events).
    wait(ms) {
      return new Promise((resolve) => {
        const done = () => {
          clearTimeout(timer);
          waiters.delete(done);
          resolve();
        };
        const timer = setTimeout(done, ms);
        waiters.add(done);
      });
    },
    ack(upto) {
      remove.run(upto);
    },
    close() {
      wake();
      db.close();
    },
  };
}
