"""A massa de dados do benchmark: uma empresa com o tamanho do RNF-01 (docs/02), gerada em SQL.

Fica no banco `chamados_bench` e só é refeita quando as migrações, esta massa ou o número de
chamados mudam (a marca fica no comentário da tabela alembic_version, como no banco de teste).
`random()` com `setseed`: a mesma massa a cada vez.

As escritas do benchmark ficam com a pessoa e o grupo "Escritas", fora dos cenários de leitura.

O que é plantado de propósito (para conferir a busca): "xilofone" no título de 3 chamados e numa
tarefa de outros 2, "Açaizeiro" na descrição de 2 e o cliente "Zebulom" em 4.
"""

import hashlib
from pathlib import Path

from alembic import command
from sqlalchemy import Engine, text

from chamados.cli import alembic_config
from chamados.modules.identity.passwords import hash_password

# Mude ao alterar a massa: o próximo benchmark a refaz.
VERSAO = "2"
MIGRACOES = Path(__file__).parents[1] / "migrations"
SENHA = "uma senha longa de benchmark"
PERSONAS = {
    "admin": "admin@bench.local",
    "supervisora": "supervisora@bench.local",
    "agente": "agente@bench.local",
    "escrita": "escrita@bench.local",
}

OBJETOS = (
    "Impressora|Notebook|VPN|E-mail|Sistema ERP|Senha|Rede|Telefone|Monitor|Teclado|Servidor|"
    "Backup|Certificado digital|Planilha|Nota fiscal|Wi-Fi|Câmera|Acesso ao sistema|Licença|Office"
)
PROBLEMAS = (
    "não funciona|sem acesso|muito lento|travando|com erro|fora do ar|não liga|sem sinal|"
    "pedindo atualização|bloqueado|não sincroniza|sem conexão"
)
LUGARES = (
    "no financeiro|na recepção|no estoque|na diretoria|na filial Centro|no galpão|na loja 2|"
    "no RH|no comercial|na expedição"
)
FRASES = (
    "Verifiquei os cabos e reiniciei o equipamento.|Troquei o toner da impressora.|"
    "Atualizei o driver e testei com o usuário.|Liguei para o cliente, sem resposta.|"
    "Aguardando a peça do fornecedor.|Reconfigurei o perfil de rede.|"
    "Restaurei o arquivo do backup da noite.|Criei o acesso e mandei a senha provisória.|"
    "Fiz a visita técnica e deixei funcionando.|Abri chamado no fabricante."
)

# Cada passo numa transação só; :n é o número de chamados e as listas de palavras vão como
# parâmetros (:objetos, :frases…), separadas por |.
PASSOS = [
    "SET LOCAL max_parallel_workers_per_gather = 0",
    "SELECT setseed(0.42)",
    # --- pessoas e grupos: 60 pessoas (RNF-02 fala em 50) em 8 grupos ---
    """
    INSERT INTO users (email, full_name, display_name, role_id, password_hash)
    SELECT p.email, p.nome, p.nome, (SELECT id FROM roles WHERE code = p.papel), :hash
    FROM (VALUES (1, 'admin@bench.local', 'Admin Bench', 'admin'),
                 (2, 'supervisora@bench.local', 'Sueli Supervisora', 'agent'),
                 (3, 'agente@bench.local', 'Abel Agente', 'agent'),
                 (4, 'escrita@bench.local', 'Edu Escritas', 'agent')) p(o, email, nome, papel)
    ORDER BY p.o
    """,
    """
    INSERT INTO users (email, full_name, display_name, role_id, password_hash)
    SELECT format('pessoa%s@bench.local', lpad(i::text, 2, '0')), format('Pessoa %s', i),
           format('Pessoa %s', i), (SELECT id FROM roles WHERE code = 'agent'), :hash
    FROM generate_series(1, 57) i
    """,
    """
    INSERT INTO teams (name)
    SELECT unnest(ARRAY['Suporte', 'Infraestrutura', 'Sistemas', 'Redes', 'Telefonia', 'Campo',
                        'Compras', 'Financeiro', 'Escritas'])
    """,
    # Os grupos da massa (a migração já cria o Administradores), na ordem: o Suporte é o 0.
    """
    CREATE TEMP TABLE bt ON COMMIT DROP AS
    SELECT id, row_number() OVER (ORDER BY id) - 1 AS k FROM teams
    WHERE name IN ('Suporte', 'Infraestrutura', 'Sistemas', 'Redes', 'Telefonia', 'Campo',
                   'Compras', 'Financeiro')
    """,
    # Cada pessoa num grupo (a primeira de cada um, menos o Suporte, supervisiona); uma em cada
    # cinco também em outro. No Suporte, a supervisora e o agente.
    """
    WITH t AS (SELECT id, k FROM bt),
         p AS (SELECT id, row_number() OVER (ORDER BY id) AS i FROM users
               WHERE email LIKE 'pessoa%')
    INSERT INTO team_members (team_id, user_id, role)
    SELECT t.id, p.id, CASE WHEN p.i <= 8 AND t.k > 0 THEN 'supervisor' ELSE 'member' END
    FROM p JOIN t ON t.k = (p.i - 1) % 8
    UNION ALL
    SELECT t.id, p.id, 'member' FROM p JOIN t ON t.k = (p.i + 3) % 8 WHERE p.i % 5 = 0
    UNION ALL
    SELECT (SELECT id FROM teams WHERE name = 'Suporte'), id,
           CASE email WHEN 'supervisora@bench.local' THEN 'supervisor' ELSE 'member' END
    FROM users WHERE email IN ('supervisora@bench.local', 'agente@bench.local')
    UNION ALL
    SELECT (SELECT id FROM teams WHERE name = 'Escritas'), id, 'member'
    FROM users WHERE email = 'escrita@bench.local'
    """,
    """
    CREATE TEMP TABLE eq ON COMMIT DROP AS
    SELECT t.id, t.k,
           (SELECT array_agg(user_id ORDER BY user_id) FROM team_members m
            WHERE m.team_id = t.id) AS membros
    FROM bt t
    """,
    # --- clientes: 3 mil, e o Zebulom ---
    """
    INSERT INTO clients (kind, name, trade_name, document, postal_code, city, state)
    SELECT CASE WHEN i % 4 = 0 THEN 'person' ELSE 'company' END,
           (ARRAY['Padaria', 'Mercado', 'Clínica', 'Escritório', 'Construtora', 'Farmácia',
                  'Auto Peças', 'Escola', 'Hotel', 'Transportadora'])[1 + i % 10]
           || ' ' || (ARRAY['Central', 'do Vale', 'São Jorge', 'Nova Era', 'Progresso',
                            'Bela Vista', 'Horizonte', 'Aliança'])[1 + (i / 10) % 8]
           || ' ' || i,
           NULL, lpad(i::text, 14, '0'), '01310100', 'São Paulo', 'SP'
    FROM generate_series(1, 3000) i
    """,
    """
    INSERT INTO clients (kind, name, trade_name, document, postal_code, city, state)
    VALUES ('company', 'Zebulom Comércio Ltda', 'Zebulom', '99999999000199', '01310100',
            'São Paulo', 'SP')
    """,
    # --- categorias: 11 raízes, 3 filhas cada, 2 netas cada; o RH é confidencial ---
    """
    INSERT INTO categories (name, default_type, is_confidential)
    SELECT n, CASE WHEN k % 3 = 0 THEN 'request' ELSE 'incident' END, n = 'RH'
    FROM unnest(ARRAY['Impressão', 'Computadores', 'Rede', 'E-mail', 'ERP', 'Telefonia',
                      'Acessos', 'Servidores', 'Compras de TI', 'Segurança', 'RH'])
         WITH ORDINALITY r(n, k)
    """,
    """
    INSERT INTO categories (parent_id, name, is_confidential)
    SELECT c.id, s.n, c.is_confidential FROM categories c
    CROSS JOIN unnest(ARRAY['Instalação', 'Defeito', 'Dúvida']) s(n)
    WHERE c.parent_id IS NULL
    """,
    """
    INSERT INTO categories (parent_id, name, is_confidential)
    SELECT c.id, s.n, c.is_confidential FROM categories c
    JOIN categories p ON p.id = c.parent_id AND p.parent_id IS NULL
    CROSS JOIN unnest(ARRAY['Urgente', 'Normal']) s(n)
    """,
    """
    CREATE TEMP TABLE folhas ON COMMIT DROP AS
    SELECT array_agg(id ORDER BY id) FILTER (WHERE NOT is_confidential) AS comuns,
           array_agg(id ORDER BY id) FILTER (WHERE is_confidential) AS confidenciais
    FROM categories c WHERE NOT EXISTS (SELECT 1 FROM categories f WHERE f.parent_id = c.id)
    """,
    # --- chamados: 3 anos; de dois em dois com o mesmo created_at (o desempate da paginação) ---
    """
    CREATE TEMP TABLE g ON COMMIT DROP AS
    SELECT i,
           now() - make_interval(secs => ((:n - i) / 2) * (3 * 365 * 86400.0 * 2 / :n)::float8)
               AS criado,
           CASE WHEN random() < 0.3 THEN 0 ELSE 1 + floor(random() * 7)::int END AS equipe,
           random() AS r_resp, random() AS r_status, random() AS r_fim,
           CASE WHEN random() < 0.1 THEN NULL
                WHEN random() < 0.25 THEN 1 + floor(random() * 50)::int
                ELSE 1 + floor(random() * 3000)::int END AS cliente,
           random() < 0.02 AS confidencial, random() AS r_cat,
           1 + floor(random() * 20)::int AS o, 1 + floor(random() * 12)::int AS p,
           1 + floor(random() * 10)::int AS l, 1 + floor(random() * 10)::int AS f,
           random() AS r_desc, random() AS r_contato
    FROM generate_series(1, :n) i
    """,
    "ALTER TABLE g ADD COLUMN kind text",
    """
    UPDATE g SET kind = CASE
        WHEN criado > now() - interval '30 days' THEN
            CASE WHEN r_status < 0.45 THEN 'open' WHEN r_status < 0.6 THEN 'waiting'
                 WHEN r_status < 0.7 THEN 'delivered' WHEN r_status < 0.95 THEN 'closed'
                 ELSE 'canceled' END
        ELSE CASE WHEN r_status < 0.02 THEN 'open' WHEN r_status < 0.03 THEN 'waiting'
                  WHEN r_status < 0.04 THEN 'delivered' WHEN r_status < 0.94 THEN 'closed'
                  ELSE 'canceled' END
    END
    """,
    """
    INSERT INTO tickets (title, description, type, created_by_id, client_id, beneficiary_name,
                         team_id, assignee_id, category_id, status_id, resolution_code_id,
                         reopened_count, started_at, created_at, updated_at, first_assigned_at,
                         closed_at, canceled_at)
    SELECT
        (string_to_array(:objetos, '|'))[g.o] || ' '
            || (string_to_array(:problemas, '|'))[g.p] || ' '
            || (string_to_array(:lugares, '|'))[g.l],
        CASE WHEN g.r_desc < 0.01 THEN repeat((string_to_array(:frases, '|'))[g.f] || ' ', 80)
             ELSE (string_to_array(:frases, '|'))[g.f] END,
        CASE WHEN g.r_cat < 0.3 THEN 'request' WHEN g.r_cat < 0.4 THEN 'task'
             ELSE 'incident' END,
        resp.id, g.cliente,
        CASE WHEN g.r_contato < 0.7 THEN format('Contato %s', 1 + floor(g.r_contato * 500))
        END,
        eq.id, resp.id,
        CASE WHEN g.confidencial
             THEN fo.confidenciais[1 + floor(g.r_cat * cardinality(fo.confidenciais))::int]
             ELSE fo.comuns[1 + floor(g.r_cat * cardinality(fo.comuns))::int] END,
        s.id,
        CASE WHEN g.kind = 'closed' THEN 1 + floor(g.r_fim * 4)::int END,
        CASE WHEN g.kind = 'closed' AND g.r_fim < 0.03 THEN 1 ELSE 0 END,
        g.criado, g.criado, coalesce(fim.em, g.criado), g.criado,
        CASE WHEN g.kind = 'closed' THEN fim.em END,
        CASE WHEN g.kind = 'canceled' THEN fim.em END
    FROM g
    JOIN eq ON eq.k = g.equipe
    CROSS JOIN folhas fo
    JOIN ticket_statuses s ON s.kind = g.kind AND s.is_default_for_kind
    CROSS JOIN LATERAL (SELECT eq.membros[1 + floor(g.r_resp * cardinality(eq.membros))::int]
                        AS id) resp
    CROSS JOIN LATERAL (
        SELECT CASE WHEN g.kind IN ('closed', 'canceled')
                    THEN least(now(), g.criado + make_interval(secs => 1800 + g.r_fim ^ 2 * 864000))
               END AS em) fim
    ORDER BY g.i
    """,
    # Os chamados de cada grupo; um em dez passou por outro grupo antes (regra 2).
    """
    INSERT INTO ticket_teams (ticket_id, team_id, first_at)
    SELECT id, team_id, created_at FROM tickets
    """,
    """
    INSERT INTO ticket_teams (ticket_id, team_id, first_at)
    SELECT t.id, outro.id, t.created_at - interval '1 hour'
    FROM tickets t JOIN eq atual ON atual.id = t.team_id
    CROSS JOIN LATERAL (SELECT 1 + floor(random() * 7)::int + 0 * t.id AS salto) x
    JOIN eq outro ON outro.k = (atual.k + x.salto) % 8
    WHERE random() < 0.1
    """,
    """
    INSERT INTO ticket_watchers (ticket_id, user_id, added_by, added_at)
    SELECT t.id, w.id, t.created_by_id, t.created_at
    FROM tickets t
    CROSS JOIN LATERAL (
        SELECT u.id FROM users u WHERE u.email LIKE '%@bench.local' AND u.id <> t.assignee_id
        ORDER BY random() + 0 * t.id LIMIT 1) w
    WHERE random() < 0.15
    """,
    """
    INSERT INTO ticket_co_assignees (ticket_id, user_id, added_at)
    SELECT t.id, eq.membros[1 + floor(random() * cardinality(eq.membros))::int], t.created_at
    FROM tickets t JOIN eq ON eq.id = t.team_id
    WHERE random() < 0.04
    ON CONFLICT DO NOTHING
    """,
    "DELETE FROM ticket_co_assignees x USING tickets t "
    "WHERE t.id = x.ticket_id AND t.assignee_id = x.user_id",
    # --- tarefas: de 0 a 8 por chamado (~200 mil), entre o registro e a conclusão ---
    """
    INSERT INTO ticket_comments (ticket_id, author_id, body, time_spent_minutes, created_at,
                                 done_at, deleted_at)
    SELECT ticket_id, author_id, body, minutos, least(feita + interval '2 minutes', now()), feita,
           CASE WHEN r_apagada < 0.02 THEN least(feita + interval '1 hour', now()) END
    FROM (
        SELECT t.id AS ticket_id,
               CASE WHEN random() < 0.8 THEN t.assignee_id
                    ELSE eq.membros[1 + floor(random() * cardinality(eq.membros))::int] END
                   AS author_id,
               (string_to_array(:frases, '|'))[1 + floor(random() * 10)::int] AS body,
               CASE WHEN random() < 0.85 THEN 15 * (1 + floor(random() * 16)::int) END AS minutos,
               t.created_at
                   + (coalesce(t.closed_at, t.canceled_at, now()) - t.created_at) * random()
                   AS feita,
               random() AS r_apagada
        FROM tickets t JOIN eq ON eq.id = t.team_id
        CROSS JOIN LATERAL generate_series(1, floor(random() * 9 + 0 * t.id)::int) k
    ) c
    """,
    # --- histórico: o registro e a mudança de status ---
    """
    INSERT INTO ticket_events (ticket_id, event_type, actor_user_id, payload, created_at)
    SELECT t.id, 'ticket.created', t.created_by_id,
           jsonb_build_object('team', jsonb_build_object('id', e.public_id, 'name', e.name),
                              'assignee', jsonb_build_object('id', u.public_id,
                                                             'name', u.display_name)),
           t.created_at
    FROM tickets t JOIN teams e ON e.id = t.team_id JOIN users u ON u.id = t.assignee_id
    """,
    """
    INSERT INTO ticket_events (ticket_id, event_type, actor_user_id, payload, created_at)
    SELECT t.id, 'ticket.status_changed', t.assignee_id,
           jsonb_build_object('from', jsonb_build_object('id', p.id, 'name', p.name),
                              'to', jsonb_build_object('id', s.id, 'name', s.name)),
           coalesce(t.closed_at, t.canceled_at,
                    t.created_at + (now() - t.created_at) * random())
    FROM tickets t JOIN ticket_statuses s ON s.id = t.status_id
    JOIN ticket_statuses p ON p.kind = 'open' AND p.is_default_for_kind
    WHERE s.kind <> 'open'
    """,
    # O responsável abriu 85% dos chamados depois da última tarefa; os outros têm novidade.
    """
    INSERT INTO ticket_reads (ticket_id, user_id, read_at)
    SELECT t.id, t.assignee_id,
           coalesce((SELECT max(c.created_at) FROM ticket_comments c WHERE c.ticket_id = t.id),
                    t.created_at)
    FROM tickets t WHERE random() < 0.85
    """,
    # --- o chamado grande: o mais recente em aberto do agente, com 150 tarefas e 40 eventos ---
    """
    CREATE TEMP TABLE grande ON COMMIT DROP AS
    SELECT t.id, t.created_at FROM tickets t JOIN ticket_statuses s ON s.id = t.status_id
    WHERE s.kind = 'open'
      AND t.assignee_id = (SELECT id FROM users WHERE email = 'agente@bench.local')
    ORDER BY t.created_at DESC LIMIT 1
    """,
    """
    INSERT INTO ticket_comments (ticket_id, author_id, body, time_spent_minutes, created_at,
                                 done_at)
    SELECT g.id, (SELECT id FROM users WHERE email = 'agente@bench.local'),
           (string_to_array(:frases, '|'))[1 + k % 10], 15 + (k % 4) * 15,
           g.created_at + (now() - g.created_at) * (k / 151.0),
           g.created_at + (now() - g.created_at) * (k / 151.0)
    FROM grande g CROSS JOIN generate_series(1, 150) k
    """,
    """
    INSERT INTO ticket_events (ticket_id, event_type, actor_user_id, payload, created_at)
    SELECT g.id, 'ticket.status_changed', (SELECT id FROM users WHERE email = 'agente@bench.local'),
           jsonb_build_object('from', jsonb_build_object('id', a.id, 'name', a.name),
                              'to', jsonb_build_object('id', b.id, 'name', b.name)),
           g.created_at + (now() - g.created_at) * (k / 41.0)
    FROM grande g CROSS JOIN generate_series(1, 40) k
    JOIN ticket_statuses a ON a.kind = CASE WHEN k % 2 = 1 THEN 'open' ELSE 'waiting' END
                          AND a.is_default_for_kind
    JOIN ticket_statuses b ON b.kind = CASE WHEN k % 2 = 1 THEN 'waiting' ELSE 'open' END
                          AND b.is_default_for_kind
    """,
    # --- o que a busca precisa achar ---
    """
    CREATE TEMP TABLE alvo ON COMMIT DROP AS
    SELECT t.id, t.team_id, t.assignee_id,
           row_number() OVER (PARTITION BY t.team_id, t.assignee_id = a.id ORDER BY t.id) AS k
    FROM tickets t CROSS JOIN (SELECT id FROM users WHERE email = 'agente@bench.local') a
    """,
    # xilofone no título: um do agente, um de outra pessoa do Suporte, um da Infraestrutura.
    """
    UPDATE tickets SET title = title || ' xilofone' WHERE id IN (
        SELECT a.id FROM alvo a JOIN teams e ON e.id = a.team_id
        WHERE a.k = 100 AND (e.name IN ('Suporte', 'Infraestrutura')))
    """,
    # xilofone numa tarefa (não removida): de um chamado do Suporte e de um das Redes.
    """
    UPDATE ticket_comments SET body = body || ' xilofone' WHERE id IN (
        SELECT DISTINCT ON (e.name) c.id FROM ticket_comments c JOIN alvo a ON a.id = c.ticket_id
        JOIN teams e ON e.id = a.team_id
        WHERE a.k >= 200 AND e.name IN ('Suporte', 'Redes') AND c.deleted_at IS NULL
          AND a.assignee_id <> (SELECT id FROM users WHERE email = 'agente@bench.local')
        ORDER BY e.name, a.k, c.id)
    """,
    """
    UPDATE tickets SET description = description || ' Fica perto do Açaizeiro.' WHERE id IN (
        SELECT id FROM alvo WHERE k = 300 ORDER BY id LIMIT 2)
    """,
    """
    UPDATE tickets SET client_id = (SELECT id FROM clients WHERE trade_name = 'Zebulom')
    WHERE id IN (SELECT id FROM alvo WHERE k IN (400, 401) ORDER BY id LIMIT 4)
    """,
]


def _assinatura() -> str:
    h = hashlib.sha256(VERSAO.encode())
    for arquivo in sorted(MIGRACOES.rglob("*.py")):
        h.update(arquivo.read_bytes())
    return h.hexdigest()


def preparar(engine: Engine, chamados: int, refazer: bool) -> bool:
    """Deixa a massa pronta; devolve True se precisou gerá-la."""
    marca = f"bench {_assinatura()} {chamados}"
    with engine.connect() as conn:
        atual = conn.scalar(text("SELECT obj_description(to_regclass('alembic_version'))"))
    if atual == marca and not refazer:
        return False

    url = engine.url.render_as_string(hide_password=False)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    command.upgrade(alembic_config(url), "head")
    params = {
        "n": chamados,
        "hash": hash_password(SENHA),
        "objetos": OBJETOS,
        "problemas": PROBLEMAS,
        "lugares": LUGARES,
        "frases": FRASES,
    }
    with engine.begin() as conn:
        for passo in PASSOS:
            conn.execute(text(passo), params)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("VACUUM ANALYZE")
        conn.exec_driver_sql(f"COMMENT ON TABLE alembic_version IS '{marca}'")
    return True
