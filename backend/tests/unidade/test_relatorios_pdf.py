"""PDF de um modelo e relatório para o cliente (docs/14 §14.8.5 e §14.8.6): o desenho de cada
tipo de bloco, com os textos já formatados. O que entra em cada um é conferido nos testes da tela
(tests/telas/test_web_reports.py)."""

import io
from dataclasses import replace
from typing import Any

import pytest
from PIL import Image
from reportlab.lib import colors

from chamados.modules.reports import model_pdf

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
        "Gerado",
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
            logo, "Relatório de atendimento", ["Padaria", "Período"], [("Horas", "1h")],
            chamados, "Gerado em 24/10/2026",
        )  # fmt: skip
        assert conteudo.startswith(b"%PDF")


def test_altura_e_subtitulo_do_bloco() -> None:
    """A altura escolhida muda o desenho na mesma proporção da tela; o subtítulo é texto."""
    cor = colors.HexColor("#C2410C")
    serie = model_pdf.Series(cor, cor, cor)
    ponto = [("seg", 60, 0, "1h")]
    medio = model_pdf._columns(model_pdf.Chart("Horas", "columns", ponto), serie)
    alto = model_pdf._columns(model_pdf.Chart("Horas", "columns", ponto, scale=1.4), serie)
    assert alto.height == medio.height * 1.4
    pdf = model_pdf.render_model(
        "M",
        [],
        [model_pdf.Grid("T", [], [], empty="vazio", subtitle="Pessoa: Ana")],
        "",
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

    def guardar(bloco: model_pdf.Chart, cor: colors.Color) -> Any:
        usadas.append(cor)
        return desenhar(bloco, cor)

    monkeypatch.setattr(model_pdf, "_bars", guardar)
    grafico = model_pdf.Chart("Horas", "bars", [("Ana", 60, 0, "1h")], color="chart-2")
    model_pdf._chart(grafico, model_pdf._styles(), serie)
    model_pdf._chart(replace(grafico, color="chart-1"), model_pdf._styles(), serie)
    assert usadas == [azul, colors.black]  # sem a cor na paleta, a da série
