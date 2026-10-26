"""Benchmark do TicketFlow: o tempo e a precisão do que as pessoas fazem no dia a dia, com a massa
do RNF-01 (50 mil chamados). Ver ARCHITECTURE.md §7.

    cd backend
    uv run python -m bench                      todos os cenários, 30 vezes cada
    uv run python -m bench --filtro busca       só os que têm "busca" no nome
    uv run python -m bench --refazer            gera a massa de novo antes

Roda o app no próprio processo (como os testes), sem uvicorn e sem rede: o tempo é o do app e do
banco. Cada cenário passa por um aquecimento, é medido até N vezes (p50, p95 e o máximo, em ms, e
as consultas SQL por requisição; um cenário lento para depois de 10 s, com ao menos 5 medidas) e
tem a resposta conferida contra o banco. Sai com erro se algum
passar da meta ou responder errado. O resultado fica em bench/resultados/, e a execução seguinte
mostra a diferença do p95.
"""

import argparse
import json
import math
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, text

from bench.cenarios import Cenario, Contexto, cenarios
from bench.massa import PERSONAS, SENHA, preparar
from chamados.config import Settings
from chamados.main import create_app

BENCH_DATABASE_URL = os.environ.get(
    "BENCH_DATABASE_URL", "postgresql+psycopg://chamados:chamados@localhost:5432/chamados_bench"
)
RESULTADOS = Path(__file__).parent / "resultados"
AQUECIMENTO = 3
# Um cenário lento (o PDF leva segundos) para de medir depois deste tempo, com ao menos 5 medidas.
TEMPO_MAXIMO = 10.0
MINIMO = 5


@dataclass
class Medida:
    nome: str
    meta_ms: int
    medidas: int
    p50: float
    p95: float
    maximo: float
    consultas: float
    erro: str | None

    @property
    def lento(self) -> bool:
        return self.p95 > self.meta_ms


def percentil(valores: list[float], p: float) -> float:
    """Pelo posto mais próximo: com 30 medidas, o p95 é a 29ª; com 5, a maior."""
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(p / 100 * len(ordenados)) - 1)]


def medir(cenario: Cenario, cliente: TestClient, engine: Engine, repeticoes: int) -> Medida:
    for _ in range(AQUECIMENTO):
        cenario.fazer(cliente)
    feitas = 0

    def contar(*_: Any) -> None:
        nonlocal feitas
        feitas += 1

    tempos: list[float] = []
    event.listen(engine, "before_cursor_execute", contar)
    comeco = perf_counter()
    try:
        while len(tempos) < repeticoes:
            inicio = perf_counter()
            r = cenario.fazer(cliente)
            tempos.append((perf_counter() - inicio) * 1000)
            if len(tempos) >= MINIMO and perf_counter() - comeco > TEMPO_MAXIMO:
                break
    finally:
        event.remove(engine, "before_cursor_execute", contar)
    erro = None
    try:
        if not r.is_success:
            raise AssertionError(f"HTTP {r.status_code}: {r.text[:200]}")
        cenario.conferir(r)
    except AssertionError as e:
        erro = str(e) or "conferência falhou"
    except Exception as e:  # a resposta veio num formato inesperado
        erro = f"{type(e).__name__}: {e}"
    return Medida(
        nome=cenario.nome,
        meta_ms=cenario.meta_ms,
        medidas=len(tempos),
        p50=percentil(tempos, 50),
        p95=percentil(tempos, 95),
        maximo=max(tempos),
        consultas=feitas / len(tempos),
        erro=erro,
    )


def entrar(app: Any, base: TestClient, email: str) -> TestClient:
    """Uma sessão (cookie e CSRF) por pessoa, no event loop do lifespan."""
    cliente = TestClient(app)
    cliente.portal = base.portal
    r = cliente.post("/api/v1/auth/login", json={"login": email, "password": SENHA})
    assert r.status_code == 204, r.text
    cliente.headers["X-CSRF-Token"] = cliente.cookies["tf_csrf"]
    return cliente


def anterior() -> dict[str, float]:
    """O p95 de cada cenário na última execução que o mediu (uma com --filtro mede só alguns)."""
    p95: dict[str, float] = {}
    for arquivo in sorted(RESULTADOS.glob("*.json")):
        p95 |= {c["nome"]: c["p95"] for c in json.loads(arquivo.read_text())["cenarios"]}
    return p95


def massa(engine: Engine) -> str:
    with engine.connect() as conn:
        contagens = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM tickets), (SELECT count(*) FROM ticket_comments), "
                "(SELECT count(*) FROM ticket_events), (SELECT count(*) FROM users), "
                "(SELECT count(*) FROM clients), current_setting('server_version')"
            )
        ).one()
    *numeros, versao = contagens
    chamados, tarefas, eventos, pessoas, clientes = (f"{n:,}".replace(",", ".") for n in numeros)
    return (
        f"{chamados} chamados, {tarefas} tarefas, {eventos} eventos, {pessoas} pessoas, "
        f"{clientes} clientes · PostgreSQL {versao.split()[0]} · {os.cpu_count()} CPUs"
    )


def imprimir(medidas: list[Medida], antes: dict[str, float]) -> None:
    largura = max(len(m.nome) for m in medidas)
    print(
        f"\n{'cenário':<{largura}}  {'n':>3}  {'p50':>6}  {'p95':>6}  {'máx':>6}  {'meta':>5}  "
        f"{'SQL':>4}  {'p95 antes':>9}  resultado"
    )
    for m in medidas:
        if m.nome in antes and antes[m.nome] > 0:
            diferenca = f"{(m.p95 / antes[m.nome] - 1) * 100:+.0f}%"
        else:
            diferenca = "—"
        situacao = f"ERRADO: {m.erro}" if m.erro else ("LENTO" if m.lento else "ok")
        print(
            f"{m.nome:<{largura}}  {m.medidas:>3}  {m.p50:>6.0f}  {m.p95:>6.0f}  "
            f"{m.maximo:>6.0f}  {m.meta_ms:>5}  {m.consultas:>4.0f}  {diferenca:>9}  {situacao}"
        )
    lentos = sum(m.lento for m in medidas)
    errados = sum(m.erro is not None for m in medidas)
    print(
        f"\n{len(medidas)} cenários: {len(medidas) - lentos - errados} ok, {lentos} acima da meta, "
        f"{errados} com resultado errado\n(n: medidas; tempos em ms; SQL: consultas por requisição)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m bench", description=__doc__.split("\n")[0])
    parser.add_argument("--repeticoes", type=int, default=30, help="até N medidas por cenário")
    parser.add_argument("--filtro", default="", help="só os cenários com este texto no nome")
    parser.add_argument("--chamados", type=int, default=50_000, help="tamanho da massa (50000)")
    parser.add_argument("--refazer", action="store_true", help="gera a massa de novo")
    args = parser.parse_args()

    engine = create_engine(BENCH_DATABASE_URL)
    inicio = perf_counter()
    if preparar(engine, args.chamados, args.refazer):
        print(f"Massa gerada em {perf_counter() - inicio:.0f} s.")
    print(f"Massa: {massa(engine)}")

    with tempfile.TemporaryDirectory() as arquivos:
        settings = Settings(
            database_url=BENCH_DATABASE_URL,
            log_level="WARNING",
            log_format="console",
            cookie_secure=False,
            files_dir=Path(arquivos),
        )
        app = create_app(settings)
        with TestClient(app) as base:
            clientes = {p: entrar(app, base, email) for p, email in PERSONAS.items()}
            ctx = Contexto(engine, clientes)
            escolhidos = [
                c for c in cenarios(ctx, clientes) if args.filtro.casefold() in c.nome.casefold()
            ]
            app_engine = app.state.engine.sync_engine
            medidas = []
            for i, cenario in enumerate(escolhidos, 1):
                print(f"[{i}/{len(escolhidos)}] {cenario.nome}", file=sys.stderr, flush=True)
                cliente = clientes[cenario.persona]
                medidas.append(medir(cenario, cliente, app_engine, args.repeticoes))

    antes = anterior()
    imprimir(medidas, antes)
    RESULTADOS.mkdir(exist_ok=True)
    arquivo = RESULTADOS / f"{datetime.now():%Y-%m-%d-%H%M%S}.json"
    arquivo.write_text(
        json.dumps(
            {
                "quando": datetime.now().isoformat(timespec="seconds"),
                "massa": massa(engine),
                "repeticoes": args.repeticoes,
                "cenarios": [asdict(m) for m in medidas],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"Resultado guardado em {arquivo}")
    return 1 if any(m.lento or m.erro for m in medidas) else 0


if __name__ == "__main__":
    sys.exit(main())
