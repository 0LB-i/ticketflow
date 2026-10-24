"""PDF de um modelo e relatório para o cliente (docs/14 §14.8.5 e §14.8.6): o desenho de cada
tipo de bloco, com os textos já formatados. O que entra em cada um é conferido nos testes da tela
(tests/telas/test_web_reports.py)."""

import io

from PIL import Image

from chamados.modules.reports import model_pdf


def test_pdf_do_modelo_com_todos_os_blocos() -> None:
    pontos = [("01/10", 120, 30, "2h"), ("02/10", 0, 0, "0min"), ("03/10", 90, 0, "1h30")]
    marcas = [(240, "4h"), (120, "2h"), (0, "0min")]
    blocos: list[model_pdf.Block] = [
        model_pdf.Cards("", [("Horas", "3h30", "−12% · antes: 4h"), ("Tarefas", "3", "")]),
        model_pdf.Chart("Horas por pessoa", "bars", [("Ana Maria de Souza Lima", 210, 0, "3h30")]),
        model_pdf.Chart("Horas por dia", "columns", pontos, ticks=marcas),
        model_pdf.Chart(
            "Empilhadas", "stacked", pontos, ticks=marcas, legend=("No exp.", "Extras")
        ),
        model_pdf.Chart("Linha", "line", pontos, ticks=marcas),
        model_pdf.Chart("Vazio", "bars", [], empty="Nada no período."),
        model_pdf.Grid("Por pessoa", ["Pessoa", "Horas"], [["Ana", "3h30"]], ["3h30"], "Total"),
        model_pdf.Grid("Tarefas", ["Quando"], [], empty="Nenhuma tarefa no período."),
    ]
    conteudo = model_pdf.render_model(
        "Mensal & <cia>", ["Período: 01/10/2026 a 03/10/2026"], blocos, "Gerado", "#C2410C"
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
