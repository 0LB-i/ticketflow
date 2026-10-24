"""Teste de carga: 5 pessoas usando o sistema ao mesmo tempo, num uvicorn de verdade. Ver
ARCHITECTURE.md §7.1.

    cd backend
    uv run python -m bench.carga                       1 e 4 workers, 30 s cada
    uv run python -m bench.carga --workers 1,2,4 --segundos 60

Sobe o uvicorn com N workers num socket Unix, sem porta, para não colidir com o serviço, no banco
do benchmark (a massa do `python -m bench`), e o derruba no fim. Cada pessoa repete a rotina dela
sem pausa entre os cliques, o pior caso: a admin gera o relatório de 12 meses (pesado) e as
outras usam listas, busca, quadro, o chamado e registram tarefas. Mostra o tempo de cada ação com
cada número de workers; o que importa é quanto as ações leves esperam pela pesada.

O cliente, os workers e o PostgreSQL dividem as CPUs da máquina: numa de 2 CPUs, 4 workers
rendem menos do que no servidor.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from httpx2 import Client, HTTPTransport, Limits, Response, TransportError
from sqlalchemy import create_engine, delete

from bench.__main__ import BENCH_DATABASE_URL, percentil
from bench.cenarios import API, LEITURA, Contexto
from bench.massa import PERSONAS, SENHA, preparar
from chamados.modules.identity.models import LoginIpFailure

BACKEND = Path(__file__).parents[1]
PESADA = "relatório de 12 meses"

Acao = tuple[str, Callable[[Client], Response]]


def rotinas(ctx: Contexto) -> dict[str, list[Acao]]:
    """O que cada uma das 5 pessoas faz, em ciclo."""
    ano = {"start": (ctx.hoje - timedelta(days=365)).isoformat(), "end": ctx.hoje.isoformat()}
    return {
        "admin": [(PESADA, lambda c: c.get(f"{API}/reports", params=ano))],
        "supervisora": [
            ("tela Quadro", lambda c: c.get("/quadro")),
            ("tela Chamados, aba Todos", lambda c: c.get("/chamados", params={"aba": "todos"})),
            ("contadores das abas", lambda c: c.get(f"{API}/tickets/counts")),
        ],
        "agente": [
            ("tela Chamados, aba padrão", lambda c: c.get("/chamados")),
            ("tela do chamado", lambda c: c.get(f"/chamados/{ctx.grande}")),
            (
                "tela Chamados, busca",
                lambda c: c.get("/chamados", params={"aba": "todos", "q": "impressora"}),
            ),
        ],
        "pessoa01": [
            ("lista Todos (API)", lambda c: c.get(f"{API}/tickets")),
            ("busca (API)", lambda c: c.get(f"{API}/tickets", params={"q": "xilofone"})),
            ("detalhe (API)", lambda c: c.get(f"{API}/tickets/{ctx.grande}")),
        ],
        "escrita": [
            (
                "registrar tarefa",
                lambda c: c.post(
                    f"{API}/tickets/{ctx.escrita}/comments",
                    json={"body": "Troquei o toner.", "time_spent_minutes": 15},
                ),
            ),
            ("tela do chamado", lambda c: c.get(f"/chamados/{ctx.escrita}")),
        ],
    }


def cliente(socket: str, email: str) -> Client:
    """Uma conexão nova a cada requisição, como o nginx faz com o uvicorn (sem keepalive no
    upstream): cada requisição vai ao worker que estiver livre, e não sempre ao mesmo."""
    transporte = HTTPTransport(uds=socket, limits=Limits(max_keepalive_connections=0))
    c = Client(transport=transporte, base_url="http://bench", timeout=120)
    r = c.post(f"{API}/auth/login", json={"login": email, "password": SENHA})
    assert r.status_code == 204, r.text
    c.headers["X-CSRF-Token"] = c.cookies["tf_csrf"]
    return c


def subir(workers: int, socket: str, arquivos: str, log: Path) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "DATABASE_URL": BENCH_DATABASE_URL,
        "LOG_LEVEL": "WARNING",
        "LOG_FORMAT": "console",
        "COOKIE_SECURE": "false",
        "APP_BASE_URL": "http://bench",
        "FILES_DIR": arquivos,
    }
    comando = [
        sys.executable, "-m", "uvicorn", "chamados.main:create_app", "--factory",
        "--uds", socket, "--workers", str(workers), "--no-access-log", "--log-level", "warning",
    ]  # fmt: skip
    with log.open("wb") as saida:
        # O comando é fixo, sem nada de fora.
        processo = subprocess.Popen(comando, cwd=BACKEND, env=env, stdout=saida, stderr=saida)  # noqa: S603
    limite = time.monotonic() + 60
    while time.monotonic() < limite:
        if processo.poll() is not None:
            raise RuntimeError(f"o uvicorn parou:\n{log.read_text()[-2000:]}")
        try:
            with Client(transport=HTTPTransport(uds=socket), base_url="http://bench") as c:
                if c.get("/api/health").status_code == 200:
                    return processo
        except TransportError:  # o socket ainda não existe
            pass
        time.sleep(0.2)
    processo.kill()
    raise RuntimeError(f"o uvicorn não respondeu em 60 s:\n{log.read_text()[-2000:]}")


def descer(processo: subprocess.Popen[bytes]) -> None:
    processo.terminate()
    try:
        processo.wait(timeout=30)
    except subprocess.TimeoutExpired:
        processo.kill()
        processo.wait()


def medir(workers: int, segundos: float) -> dict[str, list[float]]:
    """Os tempos (ms) de cada ação, com as 5 pessoas ao mesmo tempo; a chave "erros" conta as
    respostas que não foram 2xx."""
    with tempfile.TemporaryDirectory() as pasta:
        socket = f"{pasta}/bench.sock"
        processo = subir(workers, socket, pasta, Path(pasta) / "uvicorn.log")
        try:
            engine = create_engine(BENCH_DATABASE_URL)
            # Pelo socket Unix não há IP: todas as pessoas contam como o mesmo no limite de login,
            # que fica no banco de uma execução para a outra.
            with engine.begin() as conn:
                conn.execute(delete(LoginIpFailure))
            clientes = {p: cliente(socket, f"{p}@bench.local") for p in [*PERSONAS, "pessoa01"]}
            ctx = Contexto(engine, clientes)
            tempos: dict[str, list[float]] = defaultdict(list)
            erros: list[str] = []
            trava = threading.Lock()
            comeco = threading.Barrier(len(clientes))

            def pessoa(nome: str, acoes: list[Acao]) -> None:
                c = clientes[nome]
                for _, fazer in acoes:  # aquecimento: uma volta, sem medir
                    fazer(c)
                comeco.wait()
                fim = time.monotonic() + segundos
                while time.monotonic() < fim:
                    for rotulo, fazer in acoes:
                        inicio = time.perf_counter()
                        r = fazer(c)
                        ms = (time.perf_counter() - inicio) * 1000
                        with trava:
                            tempos[rotulo].append(ms)
                            if not r.is_success:
                                erros.append(f"{rotulo}: HTTP {r.status_code}")

            linhas = [
                threading.Thread(target=pessoa, args=(nome, acoes))
                for nome, acoes in rotinas(ctx).items()
            ]
            for t in linhas:
                t.start()
            for t in linhas:
                t.join()
            if erros:
                tempos["erros"] = [float(len(erros))]
                print(f"  {len(erros)} erros, ex.: {erros[0]}", file=sys.stderr)
            return tempos
        finally:
            descer(processo)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m bench.carga", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--workers", default="1,4", help="números de workers a comparar (1,4)")
    parser.add_argument("--segundos", type=float, default=30, help="duração de cada medida (30)")
    args = parser.parse_args()
    configuracoes = [int(w) for w in args.workers.split(",")]

    preparar(create_engine(BENCH_DATABASE_URL), 50_000, refazer=False)
    resultados = {}
    for workers in configuracoes:
        print(f"{workers} worker(s), {args.segundos:.0f} s…", file=sys.stderr, flush=True)
        resultados[workers] = medir(workers, args.segundos)

    rotulos = sorted({r for t in resultados.values() for r in t if r != "erros"})
    largura = max(len(r) for r in rotulos)
    cabecalho = "".join(f"  {f'{w} worker(s): n · p50 · p95':>30}" for w in configuracoes)
    print(f"\n5 pessoas ao mesmo tempo, sem pausa entre os cliques ({os.cpu_count()} CPUs)")
    print(f"{'ação':<{largura}}{cabecalho}")
    for rotulo in [PESADA, *(r for r in rotulos if r != PESADA)]:
        celulas = ""
        for w in configuracoes:
            t = resultados[w].get(rotulo, [])
            celula = f"{len(t)} · {percentil(t, 50):.0f} · {percentil(t, 95):.0f}" if t else "—"
            celulas += f"  {celula:>30}"
        print(f"{rotulo:<{largura}}{celulas}")
    print(f"\n{'leves (todas menos a pesada)':<{largura}}", end="")
    for w in configuracoes:
        leves = [ms for r, t in resultados[w].items() if r not in (PESADA, "erros") for ms in t]
        resumo = f"p95 {percentil(leves, 95):.0f} ms, {len(leves) / args.segundos:.1f}/s"
        print(f"  {resumo:>30}", end="")
    print(f"\n(tempos em ms; meta das leves: p95 < {LEITURA} ms)")
    return 1 if any("erros" in t for t in resultados.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
