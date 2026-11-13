"""Os cenários do benchmark: o que as pessoas fazem no dia a dia, cada um com a meta de tempo e a
conferência do resultado.

A conferência não confia no código que está sendo medido: ela refaz a pergunta direto no banco,
em SQL escrito à parte (o "oráculo"), inclusive as regras de visibilidade do docs/08 §8.4. Se a
regra mudar no código, o oráculo daqui muda junto.
"""

import io
import re
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi.testclient import TestClient
from httpx2 import Client, Response
from sqlalchemy import Engine, text

from chamados.core.timezone import LOCAL_TZ
from chamados.modules.system.router import TicketList

API = "/api/v1"
# RNF-01 (docs/02): p95 < 300 ms nas leituras da API com 50 mil chamados. As escritas e as telas
# ficam com a mesma meta: é o tempo que a pessoa espera depois de cada clique.
LEITURA = 300
ESCRITA = 300
EXPORTACAO = 2000
# O ZIP da aba Clientes geral: um PDF por cliente com horas no período (aqui, um dia só).
ZIP_CLIENTES = 30_000

ATIVOS = "('open', 'waiting', 'delivered')"
POR_PAGINA = TicketList().page_size  # da tela de chamados, sem configuração
# Regras 1 a 5 da visibilidade (docs/08 §8.4) para quem tem o papel agent. O admin vê tudo.
VISIVEL = """(
    t.assignee_id = :u
    OR EXISTS (SELECT 1 FROM ticket_co_assignees x WHERE x.ticket_id = t.id AND x.user_id = :u)
    OR EXISTS (SELECT 1 FROM ticket_watchers w WHERE w.ticket_id = t.id AND w.user_id = :u)
    OR t.team_id IN (SELECT team_id FROM team_members WHERE user_id = :u)
    OR (NOT EXISTS (SELECT 1 FROM categories c WHERE c.id = t.category_id AND c.is_confidential)
        AND EXISTS (SELECT 1 FROM ticket_teams tt JOIN team_members m ON m.team_id = tt.team_id
                    WHERE tt.ticket_id = t.id AND m.user_id = :u))
)"""
RESPONSAVEL = """(t.assignee_id = :u OR EXISTS (
    SELECT 1 FROM ticket_co_assignees x WHERE x.ticket_id = t.id AND x.user_id = :u))"""
OBSERVA = "EXISTS (SELECT 1 FROM ticket_watchers w WHERE w.ticket_id = t.id AND w.user_id = :u)"
DOS_MEUS_GRUPOS = "t.team_id IN (SELECT team_id FROM team_members WHERE user_id = :u)"


def contem(palavra: str) -> str:
    """O texto aparece no título, na descrição ou numa tarefa não removida (sem acentos)."""
    like = f"'%{palavra}%'"
    return f"""(unaccent(t.title) ILIKE {like} OR unaccent(t.description) ILIKE {like}
        OR EXISTS (SELECT 1 FROM ticket_comments c WHERE c.ticket_id = t.id
                   AND c.deleted_at IS NULL AND unaccent(c.body) ILIKE {like}))"""


@dataclass
class Cenario:
    nome: str
    persona: str
    fazer: Callable[[TestClient], Response]
    # Levanta AssertionError com o que veio errado.
    conferir: Callable[[Response], None]
    meta_ms: int = LEITURA


def igual(obtido: Any, esperado: Any, o_que: str) -> None:
    if obtido != esperado:
        raise AssertionError(f"{o_que}: veio {_curto(obtido)}, esperado {_curto(esperado)}")


def _curto(valor: Any) -> str:
    if isinstance(valor, list | set) and len(valor) > 6:
        itens = sorted(valor) if isinstance(valor, set) else valor
        return f"{len(valor)} itens ({', '.join(map(str, itens[:5]))}…)"
    return repr(valor)


def numeros(r: Response) -> list[int]:
    return [i["number"] for i in r.json()["items"]]


def numeros_na_tela(r: Response) -> list[int]:
    """Os chamados com link na página, na ordem, sem repetir."""
    return list(dict.fromkeys(int(n) for n in re.findall(r'href="/chamados/(\d+)"', r.text)))


class Contexto:
    """O banco do benchmark e o que os cenários precisam saber dele."""

    def __init__(self, engine: Engine, clientes: Mapping[str, Client]) -> None:
        self.engine = engine
        self.id = {
            persona: self.valor("SELECT id FROM users WHERE email = :e", e=email)
            for persona, email in {
                "admin": "admin@bench.local",
                "supervisora": "supervisora@bench.local",
                "agente": "agente@bench.local",
                "escrita": "escrita@bench.local",
            }.items()
        }
        self.suporte = str(self.valor("SELECT public_id FROM teams WHERE name = 'Suporte'"))
        self.escritas = str(self.valor("SELECT public_id FROM teams WHERE name = 'Escritas'"))
        self.cliente = str(self.valor("SELECT public_id FROM clients ORDER BY id LIMIT 1"))
        self.grande = self.valor(
            "SELECT t.number FROM tickets t JOIN ticket_comments c ON c.ticket_id = t.id "
            "GROUP BY t.number ORDER BY count(*) DESC LIMIT 1"
        )
        self.status = dict(
            self.linhas("SELECT kind, id FROM ticket_statuses WHERE is_default_for_kind")
        )
        hoje = datetime.now(LOCAL_TZ).date()
        self.hoje = hoje
        self.mes = hoje.replace(day=1)
        # Um chamado novo a cada execução, para as escritas não engordarem os da massa.
        r = clientes["escrita"].post(
            f"{API}/tickets",
            json={
                "title": "Chamado das escritas do benchmark",
                "client_id": self.cliente,
                "team_id": self.escritas,
                "assignee": "me",
            },
        )
        assert r.status_code == 201, r.text
        self.escrita = r.json()["number"]

    def linhas(self, sql: str, **params: Any) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def valor(self, sql: str, **params: Any) -> Any:
        with self.engine.connect() as conn:
            return conn.scalar(text(sql), params)

    def chamados(
        self,
        persona: str,
        onde: str = "TRUE",
        limite: int | None = 50,
        inicio: int = 0,
        antigos_primeiro: bool = False,
        **params: Any,
    ) -> list[int]:
        """Os números que a pessoa deve ver com o filtro `onde`, na ordem da lista (o mais novo
        primeiro); `antigos_primeiro` é a do teto do quadro."""
        visivel = "TRUE" if persona == "admin" else VISIVEL
        ordem = "t.created_at, t.id" if antigos_primeiro else "t.created_at DESC, t.id DESC"
        return [
            n
            for (n,) in self.linhas(
                "SELECT t.number FROM tickets t JOIN ticket_statuses s ON s.id = t.status_id "
                f"WHERE {visivel} AND {onde} ORDER BY {ordem} "
                "LIMIT :limite OFFSET :inicio",
                u=self.id[persona],
                limite=limite,
                inicio=inicio,
                **params,
            )
        ]

    def periodo(self, inicio: date, fim: date) -> tuple[datetime, datetime]:
        return datetime.combine(inicio, time(), LOCAL_TZ), datetime.combine(
            fim + timedelta(days=1), time(), LOCAL_TZ
        )

    def tarefas(self, inicio: date, fim: date, autor: str | None = None) -> tuple[int, int]:
        """Quantas tarefas e quantos minutos no período (as do autor, nos chamados que ele vê)."""
        de, ate = self.periodo(inicio, fim)
        filtro = f"c.author_id = :u AND {VISIVEL}" if autor else "TRUE"
        quantas, minutos = self.linhas(
            "SELECT count(*), coalesce(sum(c.time_spent_minutes), 0) FROM ticket_comments c "
            "JOIN tickets t ON t.id = c.ticket_id WHERE c.deleted_at IS NULL "
            f"AND c.done_at >= :de AND c.done_at < :ate AND {filtro}",
            de=de,
            ate=ate,
            u=self.id[autor] if autor else None,
        )[0]
        return quantas, minutos


def _pagina_profunda(ctx: Contexto, inicio: int) -> Callable[[TestClient], Response]:
    """A página que começa em `inicio`: o cursor vem de percorrer as anteriores uma vez."""
    cursor: list[str | None] = []

    def fazer(c: TestClient) -> Response:
        if not cursor:
            proximo = None
            for _ in range(inicio // 200):
                r = c.get(f"{API}/tickets", params={"limit": 200, "cursor": proximo})
                proximo = r.json()["next_cursor"]
            cursor.append(proximo)
        return c.get(f"{API}/tickets", params={"cursor": cursor[0]})

    return fazer


def _todas_as_paginas(c: TestClient) -> list[int]:
    vistos: list[int] = []
    proximo = None
    while True:
        r = c.get(f"{API}/tickets", params={"limit": 200, "cursor": proximo})
        vistos += numeros(r)
        proximo = r.json()["next_cursor"]
        if not proximo:
            return vistos


def _relatorio(ctx: Contexto, inicio: date, persona: str | None = None) -> Callable[..., None]:
    def conferir(r: Response) -> None:
        totais = r.json()["totals"]
        quantas, minutos = ctx.tarefas(inicio, ctx.hoje, persona)
        igual(totais["tasks"], quantas, "tarefas")
        igual(totais["minutes"], minutos, "minutos")
        if persona is None:
            de, ate = ctx.periodo(inicio, ctx.hoje)
            abertos = ctx.valor(
                "SELECT count(*) FROM tickets WHERE created_at >= :de AND created_at < :ate",
                de=de,
                ate=ate,
            )
            igual(totais["tickets_opened"], abertos, "chamados registrados")

    return conferir


def _compromissos(ctx: Contexto, persona: str, inicio: date, fim: date) -> set[str]:
    """Os compromissos de que a pessoa participa que tocam os dias de `inicio` a `fim`."""
    de, ate = ctx.periodo(inicio, fim)
    return {
        str(i)
        for (i,) in ctx.linhas(
            "SELECT a.public_id FROM appointments a JOIN appointment_attendees x "
            "ON x.appointment_id = a.id WHERE x.user_id = :u AND a.starts_at < :ate "
            "AND a.ends_at > :de",
            u=ctx.id[persona],
            de=de,
            ate=ate,
        )
    }


def compromissos_na_tela(r: Response) -> set[str]:
    return set(re.findall(r"editar=([0-9a-f-]{36})", r.text))


def cenarios(ctx: Contexto, clientes: dict[str, TestClient]) -> list[Cenario]:
    mes = {"start": ctx.mes.isoformat(), "end": ctx.hoje.isoformat()}
    ano = {"start": (ctx.hoje - timedelta(days=365)).isoformat(), "end": ctx.hoje.isoformat()}
    impressora = contem("impressor")
    # Alterna entre Aguardando e Pendente.
    alternar = {"proximo": ctx.status["waiting"]}

    def mudar_status(c: TestClient) -> Response:
        status_id = alternar["proximo"]
        alternar["proximo"] = (
            ctx.status["open"] if status_id == ctx.status["waiting"] else ctx.status["waiting"]
        )
        return c.patch(f"{API}/tickets/{ctx.escrita}", json={"status_id": status_id})

    def conferir_status(r: Response) -> None:
        igual(
            r.json()["status"]["id"],
            ctx.valor("SELECT status_id FROM tickets WHERE number = :n", n=ctx.escrita),
            "status no banco",
        )

    def conferir_registrados(r: Response) -> None:
        """O cartão dos registrados no mês, contra o banco (com o ponto do milhar)."""
        de, ate = ctx.periodo(ctx.mes, ctx.hoje)
        abertos = ctx.valor(
            "SELECT count(*) FROM tickets WHERE created_at >= :de AND created_at < :ate",
            de=de,
            ate=ate,
        )
        igual(f">{abertos:,}</a></dd>".replace(",", ".") in r.text, True, "chamados registrados")

    def conferir_todas_as_paginas(r: Response) -> None:
        igual(numeros(r), ctx.chamados("agente"), "primeira página")
        vistos = _todas_as_paginas(clientes["agente"])
        esperados = ctx.chamados("agente", limite=None)
        igual(len(vistos), len(set(vistos)), "chamados sem repetir ao paginar")
        igual(vistos, esperados, "todas as páginas")

    def conferir_tarefa(r: Response) -> None:
        igual(
            ctx.valor(
                "SELECT time_spent_minutes FROM ticket_comments WHERE public_id = :id",
                id=r.json()["id"],
            ),
            45,
            "tempo gravado",
        )

    def conferir_registro(r: Response) -> None:
        numero = r.json()["number"]
        igual(
            ctx.valor("SELECT title FROM tickets WHERE number = :n", n=numero),
            "Impressora do benchmark sem toner",
            "título gravado",
        )

    def conferir_csv(r: Response) -> None:
        igual(len(r.text.strip().splitlines()) - 1, ctx.tarefas(ctx.mes, ctx.hoje)[0], "linhas")

    def conferir_quadro(r: Response) -> None:
        # Concluídos e cancelados só os do mês; o teto é de 500 cartões.
        proximo = (ctx.mes + timedelta(days=32)).replace(day=1)
        de, ate = ctx.periodo(ctx.mes, proximo - timedelta(days=1))
        esperado = ctx.chamados(
            "supervisora",
            f"({RESPONSAVEL} OR t.team_id = (SELECT id FROM teams WHERE name = 'Suporte')) AND "
            "(s.kind NOT IN ('closed', 'canceled') "
            "OR (s.kind = 'closed' AND t.closed_at >= :de AND t.closed_at < :ate) "
            "OR (s.kind = 'canceled' AND t.canceled_at >= :de AND t.canceled_at < :ate))",
            limite=500,
            antigos_primeiro=True,
            de=de,
            ate=ate,
        )
        igual(set(numeros_na_tela(r)), set(esperado), "cartões")

    def conferir_opcoes(r: Response) -> None:
        esperado = [
            nome
            for (nome,) in ctx.linhas(
                "SELECT name FROM clients WHERE is_active AND (unaccent(name) ILIKE '%padaria%' "
                "OR unaccent(trade_name) ILIKE '%padaria%') "
                "ORDER BY lower(coalesce(name, trade_name, city)), id LIMIT 50"
            )
        ]
        igual([i["label"] for i in r.json()["items"]], esperado, "clientes")

    domingo = ctx.hoje - timedelta(days=(ctx.hoje.weekday() + 1) % 7)

    def conferir_semana(r: Response) -> None:
        igual(
            compromissos_na_tela(r),
            _compromissos(ctx, "agente", domingo, domingo + timedelta(days=6)),
            "compromissos",
        )

    def conferir_mes(r: Response) -> None:
        # No mês, até 3 por dia (o resto fica no "+N"): os da tela são do agente e do mês.
        primeiro = ctx.mes - timedelta(days=35)
        ultimo = ctx.mes + timedelta(days=42)
        na_tela = compromissos_na_tela(r)
        igual(bool(na_tela), True, "há compromissos na tela")
        igual(na_tela - _compromissos(ctx, "agente", primeiro, ultimo), set(), "de outra pessoa")

    def conferir_aviso(r: Response) -> None:
        acesos = ctx.valor(
            "SELECT count(*) FROM appointment_attendees x JOIN appointments a "
            "ON a.id = x.appointment_id WHERE x.user_id = :u AND x.alert_seen_at IS NULL "
            "AND NOT a.all_day AND a.starts_at <= now() + interval '15 minutes' "
            "AND a.ends_at > now()",
            u=ctx.id["agente"],
        )
        achado = re.search(r'data-avisos="(\d+)"', r.text)
        igual(int(achado[1]) if achado else None, acesos, "avisos")

    # A presença pergunta pelas tarefas de outras pessoas desde o registro do chamado.
    desde = ctx.valor("SELECT created_at FROM tickets WHERE number = :n", n=ctx.grande)

    def conferir_presenca(r: Response) -> None:
        novas = ctx.valor(
            "SELECT count(*) FROM ticket_comments c JOIN tickets t ON t.id = c.ticket_id "
            "WHERE t.number = :n AND c.created_at > :desde AND c.author_id <> :u "
            "AND c.deleted_at IS NULL",
            n=ctx.grande,
            desde=desde,
            u=ctx.id["agente"],
        )
        achado = re.search(r"(\d+) tarefas? novas?", r.text)
        igual(int(achado[1]) if achado else 0, novas, "tarefas novas")

    def conferir_admin_clientes(r: Response) -> None:
        ativos = ctx.valor("SELECT count(*) FROM clients WHERE is_active")
        na_tela = set(re.findall(r'href="/admin/clientes/([0-9a-f-]{36})"', r.text))
        igual(len(na_tela), min(200, ativos), "clientes na tela")

    def conferir_detalhar(r: Response) -> None:
        de, ate = ctx.periodo(ctx.mes, ctx.hoje)
        esperado = ctx.chamados(
            "admin", "t.created_at >= :de AND t.created_at < :ate", limite=None, de=de, ate=ate
        )
        # A tela lista até 200 (os mais recentes) e diz quantos são.
        achado = re.search(r"Chamados encontrados: ([\d.]+)\.", r.text)
        igual(int(achado[1].replace(".", "")) if achado else None, len(esperado), "quantos")
        na_tela = set(numeros_na_tela(r))
        igual(len(na_tela), min(200, len(esperado)), "chamados na tela")
        igual(na_tela - set(esperado), set(), "registrados fora do mês")

    ontem = ctx.hoje - timedelta(days=1)

    def conferir_zip(r: Response) -> None:
        # Os clientes com horas em tarefas de ontem; com o período na URL, de todos os status.
        de, ate = ctx.periodo(ontem, ontem)
        com_horas = ctx.valor(
            "SELECT count(*) FROM (SELECT t.client_id FROM ticket_comments c "
            "JOIN tickets t ON t.id = c.ticket_id "
            "WHERE c.deleted_at IS NULL AND t.client_id IS NOT NULL "
            "AND c.done_at >= :de AND c.done_at < :ate "
            "GROUP BY t.client_id HAVING sum(c.time_spent_minutes) > 0) x",
            de=de,
            ate=ate,
        )
        with zipfile.ZipFile(io.BytesIO(r.content)) as arquivo:
            nomes = arquivo.namelist()
            pdfs = sum(arquivo.read(n)[:5] == b"%PDF-" for n in nomes)
        igual(len(nomes), com_horas, "PDFs no ZIP (um por cliente com horas)")
        igual(pdfs, len(nomes), "arquivos que são PDF")

    def registrar_compromisso(c: TestClient) -> Response:
        return c.post(
            "/agenda/novo",
            data={
                "csrf_token": c.cookies["tf_csrf"],
                "titulo": "Compromisso do benchmark",
                "inicio_data": ctx.hoje.isoformat(),
                "inicio_hora": "09:00",
                "fim_data": ctx.hoje.isoformat(),
                "fim_hora": "10:00",
                "chamado": str(ctx.escrita),
                "visao": "semana",
                "data": ctx.hoje.isoformat(),
            },
        )

    def conferir_compromisso(r: Response) -> None:
        igual(
            compromissos_na_tela(r),
            _compromissos(ctx, "escrita", domingo, domingo + timedelta(days=6)),
            "a semana depois de gravar",
        )

    return [
        # --- listas (API) ---
        Cenario(
            "api · lista Todos (admin)",
            "admin",
            lambda c: c.get(f"{API}/tickets"),
            lambda r: igual(numeros(r), ctx.chamados("admin"), "página"),
        ),
        Cenario(
            "api · lista Todos, a partir do 10.000º (admin)",
            "admin",
            _pagina_profunda(ctx, 10_000),
            lambda r: igual(numeros(r), ctx.chamados("admin", inicio=10_000), "página"),
        ),
        Cenario(
            "api · lista Todos, e todas as páginas (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets"),
            conferir_todas_as_paginas,
        ),
        Cenario(
            "api · lista Meus (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets", params={"view": "mine"}),
            lambda r: igual(
                numeros(r),
                ctx.chamados("agente", f"{RESPONSAVEL} AND s.kind IN {ATIVOS}"),
                "página",
            ),
        ),
        Cenario(
            "api · lista Aguardando (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets", params={"view": "waiting"}),
            lambda r: igual(
                numeros(r),
                ctx.chamados("agente", f"{DOS_MEUS_GRUPOS} AND s.kind IN ('waiting', 'delivered')"),
                "página",
            ),
        ),
        Cenario(
            "api · lista Observando (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets", params={"view": "watching"}),
            lambda r: igual(
                numeros(r), ctx.chamados("agente", f"{OBSERVA} AND s.kind IN {ATIVOS}"), "página"
            ),
        ),
        Cenario(
            "api · lista do grupo, só Pendentes (supervisora)",
            "supervisora",
            lambda c: c.get(f"{API}/tickets", params={"team": ctx.suporte, "status": "open"}),
            lambda r: igual(
                numeros(r),
                ctx.chamados(
                    "supervisora",
                    "t.team_id = (SELECT id FROM teams WHERE name = 'Suporte') AND s.kind = 'open'",
                ),
                "página",
            ),
        ),
        Cenario(
            "api · contadores das abas (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets/counts"),
            lambda r: igual(
                r.json(),
                {
                    "mine": len(
                        ctx.chamados("agente", f"{RESPONSAVEL} AND s.kind IN {ATIVOS}", None)
                    ),
                    "waiting": len(
                        ctx.chamados(
                            "agente",
                            f"{DOS_MEUS_GRUPOS} AND s.kind IN ('waiting', 'delivered')",
                            None,
                        )
                    ),
                    "watching": len(
                        ctx.chamados("agente", f"{OBSERVA} AND s.kind IN {ATIVOS}", None)
                    ),
                    "all": len(ctx.chamados("agente", f"s.kind IN {ATIVOS}", None)),
                },
                "contadores",
            ),
        ),
        # --- busca ---
        Cenario(
            "api · busca palavra comum: impressora (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets", params={"q": "impressora"}),
            lambda r: igual(numeros(r), ctx.chamados("agente", impressora), "página"),
        ),
        Cenario(
            "api · busca palavra rara: xilofone (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets", params={"q": "xilofone"}),
            lambda r: igual(numeros(r), ctx.chamados("agente", contem("xilofone")), "achados"),
        ),
        Cenario(
            "api · busca palavra rara: xilofone (admin)",
            "admin",
            lambda c: c.get(f"{API}/tickets", params={"q": "xilofone"}),
            lambda r: igual(numeros(r), ctx.chamados("admin", contem("xilofone")), "achados"),
        ),
        Cenario(
            "api · busca sem acento: acaizeiro (admin)",
            "admin",
            lambda c: c.get(f"{API}/tickets", params={"q": "acaizeiro"}),
            lambda r: igual(numeros(r), ctx.chamados("admin", contem("acaizeiro")), "achados"),
        ),
        Cenario(
            "api · busca pelo cliente: zebulom (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets", params={"q": "zebulom"}),
            lambda r: igual(
                numeros(r),
                ctx.chamados(
                    "agente", "t.client_id = (SELECT id FROM clients WHERE trade_name = 'Zebulom')"
                ),
                "achados",
            ),
        ),
        Cenario(
            "api · busca pelo número (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets", params={"q": f"#{ctx.grande}"}),
            lambda r: igual(ctx.grande in numeros(r), True, "o chamado está entre os achados"),
        ),
        # --- um chamado ---
        Cenario(
            "api · detalhe do chamado com 150 tarefas (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets/{ctx.grande}"),
            lambda r: igual(
                r.json()["time_spent_minutes"],
                ctx.valor(
                    "SELECT coalesce(sum(time_spent_minutes), 0) FROM ticket_comments c "
                    "JOIN tickets t ON t.id = c.ticket_id "
                    "WHERE t.number = :n AND c.deleted_at IS NULL",
                    n=ctx.grande,
                ),
                "tempo gasto",
            ),
        ),
        Cenario(
            "api · tarefas do chamado com 150 tarefas (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets/{ctx.grande}/comments"),
            lambda r: igual(
                len(r.json()["items"]),
                ctx.valor(
                    "SELECT count(*) FROM ticket_comments c JOIN tickets t ON t.id = c.ticket_id "
                    "WHERE t.number = :n AND c.deleted_at IS NULL",
                    n=ctx.grande,
                ),
                "tarefas",
            ),
        ),
        Cenario(
            "api · histórico do chamado com 150 tarefas (agente)",
            "agente",
            lambda c: c.get(f"{API}/tickets/{ctx.grande}/events"),
            lambda r: igual(
                len(r.json()["items"]),
                ctx.valor(
                    "SELECT count(*) FROM ticket_events e JOIN tickets t ON t.id = e.ticket_id "
                    "WHERE t.number = :n",
                    n=ctx.grande,
                ),
                "eventos",
            ),
        ),
        Cenario(
            "api · clientes para escolher: padaria (agente)",
            "agente",
            lambda c: c.get(f"{API}/clients/options", params={"q": "padaria"}),
            conferir_opcoes,
        ),
        # --- relatórios ---
        Cenario(
            "api · relatório do mês (admin)",
            "admin",
            lambda c: c.get(f"{API}/reports", params=mes),
            _relatorio(ctx, ctx.mes),
        ),
        Cenario(
            "api · relatório dos últimos 12 meses (admin)",
            "admin",
            lambda c: c.get(f"{API}/reports", params=ano),
            _relatorio(ctx, ctx.hoje - timedelta(days=365)),
        ),
        Cenario(
            "api · relatório do mês, as próprias horas (agente)",
            "agente",
            lambda c: c.get(f"{API}/reports", params=mes),
            _relatorio(ctx, ctx.mes, "agente"),
        ),
        # --- telas: 25 por página (o padrão); na aba Todos, só os em andamento ---
        Cenario(
            "tela · Chamados, aba padrão (agente)",
            "agente",
            lambda c: c.get("/chamados"),
            lambda r: igual(
                numeros_na_tela(r),
                ctx.chamados("agente", f"{RESPONSAVEL} AND s.kind IN {ATIVOS}", POR_PAGINA),
                "chamados na tela",
            ),
        ),
        Cenario(
            "tela · Chamados, aba Todos (admin)",
            "admin",
            lambda c: c.get("/chamados", params={"aba": "todos"}),
            lambda r: igual(
                numeros_na_tela(r),
                ctx.chamados("admin", f"s.kind IN {ATIVOS}", POR_PAGINA),
                "chamados na tela",
            ),
        ),
        Cenario(
            "tela · Chamados, busca: impressora (agente)",
            "agente",
            lambda c: c.get("/chamados", params={"aba": "todos", "q": "impressora"}),
            lambda r: igual(
                numeros_na_tela(r),
                ctx.chamados("agente", f"{impressora} AND s.kind IN {ATIVOS}", POR_PAGINA),
                "chamados na tela",
            ),
        ),
        Cenario(
            "tela · chamado com 150 tarefas (agente)",
            "agente",
            lambda c: c.get(f"/chamados/{ctx.grande}"),
            lambda r: igual(f"#{ctx.grande}" in r.text, True, "o número na página"),
        ),
        Cenario(
            "tela · Quadro (supervisora)",
            "supervisora",
            lambda c: c.get("/quadro"),
            conferir_quadro,
        ),
        Cenario(
            # A página sem os números (os blocos vêm em /relatorios/blocos, pedidos por ela).
            "tela · Relatórios (admin)",
            "admin",
            lambda c: c.get("/relatorios"),
            lambda r: igual('hx-get="/relatorios/blocos' in r.text, True, "o pedido dos números"),
        ),
        Cenario(
            "tela · Relatórios, blocos (admin)",
            "admin",
            lambda c: c.get("/relatorios/blocos"),
            conferir_registrados,
        ),
        Cenario(
            # Todos os conjuntos de chamados (o em aberto no fim é o mais largo), duas vezes.
            "tela · Relatórios, Chamados com Comparar (admin)",
            "admin",
            lambda c: c.get("/relatorios/blocos", params={"aba": "chamados", "comparar": "1"}),
            conferir_registrados,
        ),
        Cenario(
            "tela · clientes para escolher: padaria (agente)",
            "agente",
            lambda c: c.get("/clientes/opcoes", params={"q": "padaria"}),
            lambda r: igual("Padaria" in r.text, True, "clientes na página"),
        ),
        Cenario(
            "tela · Relatórios, detalhar os registrados no mês (admin)",
            "admin",
            lambda c: c.get("/relatorios/chamados", params={"aba": "chamados", "medida": "opened"}),
            conferir_detalhar,
        ),
        Cenario(
            # Só quem é de um grupo que cuida dos clientes: o Escritas, na massa.
            "tela · Clientes, a lista (agente)",
            "escrita",
            lambda c: c.get("/admin/clientes"),
            conferir_admin_clientes,
        ),
        # --- agenda ---
        Cenario(
            "tela · Agenda, mês (agente)",
            "agente",
            lambda c: c.get("/agenda"),
            conferir_mes,
        ),
        Cenario(
            "tela · Agenda, semana (agente)",
            "agente",
            lambda c: c.get("/agenda", params={"visao": "semana", "data": ctx.hoje.isoformat()}),
            conferir_semana,
        ),
        Cenario(
            "tela · Agenda, chamados para escolher: impressora (agente)",
            "agente",
            lambda c: c.get("/agenda/chamados", params={"q": "impressora"}),
            lambda r: igual(
                [int(n) for n in re.findall(r'data-id="(\d+)"', r.text)],
                ctx.chamados("agente", impressora, 20),
                "chamados",
            ),
        ),
        # --- o que cada aba aberta pergunta sozinha: somam com o número de pessoas e de abas ---
        Cenario(
            "tela · aviso da agenda, a cada 60 s (agente)",
            "agente",
            lambda c: c.get("/agenda/aviso"),
            conferir_aviso,
        ),
        Cenario(
            "tela · presença no chamado com 150 tarefas, a cada 20 s (agente)",
            "agente",
            lambda c: c.get(
                f"/chamados/{ctx.grande}/presenca", params={"desde": desde.isoformat()}
            ),
            conferir_presenca,
        ),
        # --- escritas ---
        # As escritas são da pessoa do grupo Escritas: não mudam as filas dos cenários acima.
        Cenario(
            "api · registrar chamado (agente)",
            "escrita",
            lambda c: c.post(
                f"{API}/tickets",
                json={
                    "title": "Impressora do benchmark sem toner",
                    "client_id": ctx.cliente,
                    "team_id": ctx.escritas,
                    "assignee": "me",
                },
            ),
            conferir_registro,
            ESCRITA,
        ),
        Cenario(
            "api · registrar tarefa com tempo (agente)",
            "escrita",
            lambda c: c.post(
                f"{API}/tickets/{ctx.escrita}/comments",
                json={"body": "Troquei o toner.", "time_spent_minutes": 45},
            ),
            conferir_tarefa,
            ESCRITA,
        ),
        Cenario(
            "api · mudar o status (agente)",
            "escrita",
            mudar_status,
            conferir_status,
            ESCRITA,
        ),
        Cenario(
            "tela · registrar compromisso e voltar à semana (agente)",
            "escrita",
            registrar_compromisso,
            conferir_compromisso,
            ESCRITA,
        ),
        # --- exportações ---
        Cenario(
            "api · relatório do mês em PDF (admin)",
            "admin",
            lambda c: c.get(f"{API}/reports/pdf", params=mes),
            lambda r: igual(r.content[:5], b"%PDF-", "início do arquivo"),
            EXPORTACAO,
        ),
        Cenario(
            "api · tarefas do mês em CSV (admin)",
            "admin",
            lambda c: c.get(f"{API}/reports/csv", params={**mes, "table": "tasks"}),
            conferir_csv,
            EXPORTACAO,
        ),
        Cenario(
            "tela · Clientes geral, ZIP de ontem (admin)",
            "admin",
            lambda c: c.get(
                "/relatorios/clientes-geral/zip",
                params={
                    "periodo": "personalizado",
                    "de": ontem.isoformat(),
                    "ate": ontem.isoformat(),
                },
            ),
            conferir_zip,
            ZIP_CLIENTES,
        ),
    ]
