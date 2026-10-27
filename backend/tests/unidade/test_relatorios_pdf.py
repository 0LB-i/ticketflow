"""PDF de um modelo, relatório para o cliente e o PDF da API (docs/14 §14.7, §14.8.5 e §14.8.6):
o desenho de cada tipo de bloco, com os textos já formatados, a página e o rodapé. O que entra em
cada um é conferido nos testes da tela (tests/telas/test_web_reports.py)."""

import io
from dataclasses import replace
from datetime import date, datetime, time
from typing import Any

import pytest
from PIL import Image
from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import stringWidth

from chamados.modules.reports import model_pdf
from chamados.modules.reports.schemas import Report, TaskRow, Totals
from chamados.modules.reports.service import TZ, Filters
from chamados.modules.system.work_hours import DEFAULT

PAGINA = model_pdf.Page("Gerado em 24/10/2026", "Página {n} de {total}")
SERIES = {
    "chart-1": "#C2410C",
    "chart-2": "#1D4ED8",
    "chart-3": "#0F766E",
    "chart-4": "#172554",
    "chart-before": "#D3785C",
}


def test_pdf_do_modelo_com_todos_os_blocos() -> None:
    pontos = [("01/10", 120, 30, "2h"), ("02/10", 0, 0, "0min"), ("03/10", 90, 0, "1h30")]
    marcas = [(240, "4h"), (120, "2h"), (0, "0min")]
    blocos: list[model_pdf.Block] = [
        model_pdf.Cards("", [("Horas", "3h30", "−12% · antes: 4h"), ("Tarefas", "3", "")]),
        model_pdf.Cards("", [("Horas", "3h30", "−12% · antes: 4h")], big=True),
        model_pdf.Chart("Horas por pessoa", "bars", [("Ana Maria de Souza Lima", 210, 0, "3h30")]),
        model_pdf.Chart("Horas por dia", "columns", pontos, ticks=marcas),
        model_pdf.Chart(
            "Empilhadas", "stacked", pontos, ticks=marcas, legend=("No exp.", "Extras")
        ),
        model_pdf.Chart("Linha", "line", pontos, ticks=marcas),
        model_pdf.Chart(
            "Barras + linha", "combo", pontos, ticks=marcas, legend=("Horas", "Horas extras")
        ),
        model_pdf.Chart(
            "Área com a média",
            "line",
            pontos,
            ticks=marcas,
            reference=(70, "Média: 1h10"),
            area=True,
        ),
        model_pdf.Chart(
            "Colunas com a mediana", "columns", pontos, ticks=marcas, reference=(90, "x")
        ),
        model_pdf.Chart("Vazio", "bars", [], empty="Nada no período."),
        model_pdf.Grid("Por pessoa", ["Pessoa", "Horas"], [["Ana", "3h30"]], ["3h30"], "Total"),
        model_pdf.Grid("Tarefas", ["Quando"], [], empty="Nenhuma tarefa no período."),
        model_pdf.Heatmap(
            "Horas por dia da semana e hora",
            [f"{h}h" for h in range(24)],
            [(dia, [(d + h) % 6 for h in range(24)]) for d, dia in enumerate(["Seg", "Ter"])],
            [(0, "Nada"), *((k, f"até {k}h") for k in range(1, 6))],
        ),
        model_pdf.Heatmap("Vazio", [], [], [], empty="Nada no período."),
    ]
    conteudo = model_pdf.render_model(
        "Mensal & <cia>",
        ["Período: 01/10/2026 a 03/10/2026"],
        blocos,
        PAGINA,
        SERIES,
        ("#EDC3B5", "#E5A490", "#DB856A", "#CF6543", "#C2410C"),
    )
    assert conteudo.startswith(b"%PDF")


def test_relatorio_para_o_cliente_com_logotipo() -> None:
    imagem = io.BytesIO()
    Image.new("RGB", (200, 80), "#C2410C").save(imagem, format="PNG")
    chamados = model_pdf.Grid("", ["Chamado", "Horas"], [["#1000", "1h"]])
    for logo in (imagem.getvalue(), None):
        conteudo = model_pdf.render_client(
            logo, "Relatório de atendimento", ["Padaria", "Período"], "Olá & <b>oi</b>\nlinha 2",
            [("Horas", "1h")], chamados, "", PAGINA,
        )  # fmt: skip
        assert conteudo.startswith(b"%PDF")


def test_altura_e_subtitulo_do_bloco() -> None:
    """A altura escolhida muda o desenho na mesma proporção da tela; o subtítulo é texto."""
    cor = colors.HexColor("#C2410C")
    serie = model_pdf.Series(cor, cor, cor)
    ponto = [("seg", 60, 0, "1h")]
    medio = model_pdf._columns(model_pdf.Chart("Horas", "columns", ponto), serie, PAGINA.width)
    alto = model_pdf._columns(
        model_pdf.Chart("Horas", "columns", ponto, scale=1.4), serie, PAGINA.width
    )
    assert alto.height == medio.height * 1.4
    pdf = model_pdf.render_model(
        "M",
        [],
        [model_pdf.Grid("T", [], [], empty="vazio", subtitle="Pessoa: Ana")],
        PAGINA,
        SERIES,
        (),
    )
    assert pdf.startswith(b"%PDF")


def test_cor_da_serie_do_bloco(monkeypatch: pytest.MonkeyPatch) -> None:
    """O bloco guarda o nome do token; o PDF desenha com a cor dele (a do modo claro)."""
    azul = colors.HexColor("#1D4ED8")
    serie = model_pdf.Series(colors.black, colors.black, colors.black, named={"chart-2": azul})
    usadas: list[colors.Color] = []
    desenhar = model_pdf._bars

    def guardar(bloco: model_pdf.Chart, cor: colors.Color, largura: float) -> Any:
        usadas.append(cor)
        return desenhar(bloco, cor, largura)

    monkeypatch.setattr(model_pdf, "_bars", guardar)
    grafico = model_pdf.Chart("Horas", "bars", [("Ana", 60, 0, "1h")], color="chart-2")
    model_pdf._chart(grafico, model_pdf._styles(), serie, PAGINA.width)
    model_pdf._chart(replace(grafico, color="chart-1"), model_pdf._styles(), serie, PAGINA.width)
    assert usadas == [azul, colors.black]  # sem a cor na paleta, a da série


def test_pagina_deitada_e_rodape_em_cada_pagina(monkeypatch: pytest.MonkeyPatch) -> None:
    """A4 em pé ou deitado (a largura dos blocos segue a página) e, em cada página, o rodapé
    com o texto livre, o "Gerado em…" e "Página n de total"."""
    deitada = replace(PAGINA, landscape=True, footer="Uso interno & <confidencial>")
    assert deitada.size[0] > deitada.size[1] and deitada.width > PAGINA.width
    assert deitada.footer_lines() == ["Uso interno & <confidencial>"]
    assert replace(PAGINA, footer="palavra " * 200).footer_lines()[-1]  # no máximo três linhas
    assert len(replace(PAGINA, footer="palavra " * 200).footer_lines()) == 3
    rodapes: list[tuple[int, int]] = []
    desenhar = model_pdf._footer

    def guardar(canvas: Any, pagina: model_pdf.Page, numero: int, total: int) -> None:
        rodapes.append((numero, total))
        desenhar(canvas, pagina, numero, total)

    monkeypatch.setattr(model_pdf, "_footer", guardar)
    linhas = [[f"Pessoa {i}", "1h"] for i in range(120)]  # mais de uma página
    conteudo = model_pdf.render_model(
        "M", [], [model_pdf.Grid("T", ["Pessoa", "Horas"], linhas)], deitada, SERIES, ()
    )
    assert conteudo.startswith(b"%PDF")
    total = len(rodapes)
    assert total > 1 and rodapes == [(n, total) for n in range(1, total + 1)]


def test_largura_das_colunas_pelo_texto() -> None:
    """A coluna estreita fica com o que precisa; a larga divide o resto. Juntas, a largura toda."""
    textos = [["Quando", "Chamado", "Tempo"], ["24/10 10:00", "#1 " + "título longo " * 10, "1h"]]
    larguras = model_pdf._widths(textos, 500, 9)
    assert sum(larguras) == pytest.approx(500)
    assert larguras[1] > larguras[0] > larguras[2]
    # Uma coluna longa (o título) não espreme a média (o status) abaixo da parte igual: as sete
    # colunas do relatório para o cliente, com quem atendeu.
    linha = ["#1000", "título " * 40, "01/10/2026", "02/10/2026", "Aguardando cliente", "1h30"]
    larguras = model_pdf._widths([[*linha, "Ana Maria, Bia"]], 510, 9)
    assert sum(larguras) == pytest.approx(510)
    assert larguras[4] >= 510 / 7 > larguras[2]  # o status, não menos que a data
    precisa = stringWidth("Ana Maria, Bia", "Helvetica", 9) + model_pdf.PADDING
    assert larguras[6] == pytest.approx(precisa)  # cabe na parte igual: fica com o que precisa
    # Tudo cabe: crescem na proporção.
    assert sum(model_pdf._widths([["a", "bb"]], 500, 9)) == pytest.approx(500)


def test_pdf_da_api_com_as_200_primeiras(monkeypatch: pytest.MonkeyPatch) -> None:
    """O PDF da API é um modelo fixo: totais, por pessoa, por cliente e as tarefas fora do
    expediente (as 200 primeiras, com a nota), com os textos do idioma pedido."""
    feita = datetime(2026, 10, 20, 19, 0, tzinfo=TZ)
    tarefa = TaskRow(
        ticket_number=0,
        ticket_title="Servidor",
        client=None,
        person="Ana",
        done_at=feita,
        minutes=90,
        overtime_minutes=60,
    )
    tarefas = [tarefa.model_copy(update={"ticket_number": i}) for i in range(250)]
    relatorio = Report(
        start=date(2026, 10, 1),
        end=date(2026, 10, 31),
        work_hours=DEFAULT.model_copy(update={"start": time(8), "holidays": [date(2026, 10, 12)]}),
        totals=Totals(
            minutes=90 * 250,
            overtime_minutes=60 * 250,
            tasks=250,
            tickets_opened=3,
            tickets_closed=2,
        ),
        people=[],
        clients=[],
        days=[],
        overtime_tasks=tarefas,
    )
    chamadas: list[tuple[Any, ...]] = []

    def desenhar(*args: Any) -> bytes:
        chamadas.append(args)
        return b"%PDF"

    monkeypatch.setattr(model_pdf, "render_model", desenhar)
    filtros = Filters(start=relatorio.start, end=relatorio.end, no_client=True)
    for idioma in ("pt-BR", "en"):
        assert model_pdf.render_hours(relatorio, filtros, "Ana", idioma) == b"%PDF"
    titulo, linhas, blocos, pagina, _, _ = chamadas[0]
    assert titulo == "Relatório de horas"
    assert linhas == [
        "01/10/2026 a 31/10/2026",
        "Grupo: Todos · Pessoa: Todos · Cliente: Sem cliente · Status: Todos",
        "Expediente: seg, ter, qua, qui, sex · 08:00–18:00 · 1 feriado(s) cadastrado(s)",
    ]
    assert blocos[0].items[:2] == [("Horas", "375:00", ""), ("Horas extras", "250:00", "")]
    assert [b.title for b in blocos[1:]] == [
        "Por pessoa", "Por cliente", "Tarefas fora do expediente"
    ]  # fmt: skip
    assert blocos[1].empty == "Nada no período."
    lista = blocos[3]
    assert len(lista.rows) == 200
    assert lista.rows[0] == ["20/10/2026 19:00", "Ana", "#0 Servidor", "1:30", "1:00"]
    assert lista.note == "Mostrando as 200 primeiras de 250 tarefas. O CSV traz todas."
    assert pagina.generated.startswith("Gerado em ") and pagina.generated.endswith(" por Ana")
    assert pagina.numbering == "Página {n} de {total}" and not pagina.landscape
    titulo, linhas, blocos, pagina, _, _ = chamadas[1]
    assert titulo == "Hours report" and linhas[0] == "2026-10-01 to 2026-10-31"
    assert blocos[3].note == "Showing the first 200 of 250 tasks. The CSV has all of them."
    assert pagina.numbering == "Page {n} of {total}"
