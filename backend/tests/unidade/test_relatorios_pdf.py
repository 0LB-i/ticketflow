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
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import FrameBreak, Paragraph, Table

from chamados.modules.reports import model_pdf
from chamados.modules.reports.schemas import Report, TaskRow, Totals
from chamados.modules.reports.service import TZ, Filters, ScheduleUse
from chamados.modules.system.company import Company, letterhead
from chamados.modules.system.work_hours import DEFAULT, Schedule

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
        # O PDF do modelo leva o mesmo logotipo, no cabeçalho.
        conteudo = model_pdf.render_model("M", ["Período"], [], PAGINA, SERIES, (), logo)
        assert conteudo.startswith(b"%PDF")


def test_dados_da_empresa_no_cabecalho() -> None:
    """As linhas da empresa (as que têm algo) ficam à direita do logotipo, ou sozinhas sem ele."""
    assert letterhead(None) == []
    empresa = Company(name="Padaria Pão Quente Ltda", document="11222333000181")
    assert letterhead(empresa) == ["Padaria Pão Quente Ltda", "CNPJ 11.222.333/0001-81"]
    empresa = empresa.model_copy(
        update={
            "state_registration": "ISENTO",
            "street": "Av. Paulista",
            "number": "1000",
            "district": "Bela Vista",
            "city": "São Paulo",
            "state": "SP",
            "postal_code": "01310100",
            "phone": "1133334444",
            "email": "contato@padaria.com.br",
        }
    )
    linhas = letterhead(empresa)
    # Só o nome fantasia, a razão social, o CNPJ e o e-mail.
    assert linhas == [
        "Padaria Pão Quente Ltda",
        "CNPJ 11.222.333/0001-81",
        "contato@padaria.com.br",
    ]
    linhas = letterhead(empresa.model_copy(update={"trade_name": "Pão Quente"}))
    assert linhas[:2] == ["Pão Quente", "Padaria Pão Quente Ltda"]
    imagem = io.BytesIO()
    Image.new("RGB", (200, 80), "#C2410C").save(imagem, format="PNG")
    chamados = model_pdf.Grid("", ["Chamado", "Horas"], [["#1000", "1h"]])
    for logo in (imagem.getvalue(), None):
        cabecalho = model_pdf._heading(logo, 180 * mm, linhas)[0]
        assert isinstance(cabecalho, Table)
        # O logotipo (200 x 80 cabe em 40 x 16 mm) com o respiro, e os dados no resto.
        larguras = [180 * mm] if logo is None else [40 * mm + 12, 140 * mm - 12]
        assert cabecalho._colWidths == pytest.approx(larguras)  # type: ignore[attr-defined]
        conteudo = model_pdf.render_model("M", ["Período"], [], PAGINA, SERIES, (), logo, linhas)
        assert conteudo.startswith(b"%PDF")
        conteudo = model_pdf.render_client(
            logo, "Relatório", ["Padaria"], "", [("Horas", "1h")], chamados, "", PAGINA, linhas
        )
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


def test_barras_com_muitas_pessoas() -> None:
    """Uma barra por pessoa, sem limite: em desenhos de até `BARS`, na mesma escala, que se
    dividem entre as páginas (um desenho só passava da altura da página e o PDF falhava)."""
    pontos = [(f"Pessoa {i}", 60 * i, 0, f"{i}h") for i in range(80)]
    desenhos = model_pdf._bars(model_pdf.Chart("Horas", "bars", pontos), colors.black, 500)
    assert len(desenhos) == 4
    for deitada in (False, True):
        pagina = replace(PAGINA, landscape=deitada)
        grafico = model_pdf.Chart("Horas por pessoa", "bars", pontos)
        conteudo = model_pdf.render_model("M", [], [grafico], pagina, SERIES, ())
        assert conteudo.startswith(b"%PDF")


def test_letras_fora_do_latim_basico() -> None:
    """A fonte embutida tem o sinal de menos, o Δ e as letras de outras línguas: nada cai nas
    fontes de símbolos (o ■ no lugar da letra)."""
    texto = "Łódź −12% Δ Ğ Москва →"
    conteudo = model_pdf.render_model(
        texto,
        [texto],
        [
            model_pdf.Grid(texto, [texto], [[texto]]),
            model_pdf.Chart(texto, "bars", [(texto, 1, 0, texto)]),
        ],
        replace(PAGINA, footer=texto),
        SERIES,
        (),
    )
    assert model_pdf.FONT.encode() in conteudo
    assert b"ZapfDingbats" not in conteudo and b"/Symbol" not in conteudo


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


def test_tabela_que_continua_na_pagina_seguinte() -> None:
    """A tabela que passa da página abre cada página seguinte com o título e "(continuação)";
    a sem título (a do relatório para o cliente) segue só com o cabeçalho das colunas."""
    pagina = replace(PAGINA, continued="{titulo} (continuação)")
    linhas = [[f"Cliente {i}", "1h"] for i in range(150)]  # três páginas
    tabela = model_pdf.Grid("Por cliente", ["Cliente", "Horas"], linhas)
    *_, partes = model_pdf._grid(tabela, model_pdf._styles(), pagina.width, pagina.continued)
    _, quebra, titulo, resto = partes.split(pagina.width, 600)
    assert quebra is FrameBreak
    assert isinstance(titulo, Paragraph) and isinstance(resto, model_pdf._Continued)
    assert titulo.getPlainText() == "Por cliente (continuação)" and resto.label is titulo
    sem_titulo = model_pdf._grid(replace(tabela, title=""), model_pdf._styles(), 500)[-1]
    assert len(sem_titulo.split(500, 600)) == 2
    conteudo = model_pdf.render_model("M", [], [tabela], pagina, SERIES, ())
    assert conteudo.startswith(b"%PDF")


def test_rotulo_das_barras_pela_largura() -> None:
    """O nome nas barras é cortado pela largura que ele ocupa, não pelo número de letras."""
    assert model_pdf._fit("Ana", 100, 8) == "Ana"
    cortado = model_pdf._fit("Nome muito comprido " * 5, 100, 8)
    assert cortado.endswith("…") and stringWidth(cortado, model_pdf.FONT, 8) <= 100


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
    precisa = stringWidth("Ana Maria, Bia", model_pdf.FONT, 9) + model_pdf.PADDING
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
    # O expediente que valeu: o da instalação, que mudou no dia 15, o de um grupo que a pessoa
    # vê, o de um que ela não vê e o próprio de uma pessoa.
    uso = ScheduleUse(
        [
            (relatorio.start, Schedule((0, 1, 2, 3, 4), time(8), time(18))),
            (date(2026, 10, 15), Schedule((0, 1, 2, 3, 4, 5), time(8), time(12))),
        ],
        teams=[("Suporte", 2), (None, 1)],
        people=["Ana"],
    )
    for idioma in ("pt-BR", "en"):
        pdf = model_pdf.render_hours(relatorio, filtros, uso, idioma, b"logo", ["Padaria"])
        assert pdf == b"%PDF"
    titulo, linhas, blocos, pagina, _, _, logo, empresa = chamadas[0]
    assert logo == b"logo"  # o logotipo dos relatórios, no cabeçalho
    assert empresa == ["Padaria"]  # e os dados da empresa
    assert titulo == "Relatório de horas"
    assert linhas == [
        "01/10/2026 a 31/10/2026 · Grupo: Todos · Pessoa: Todos · Cliente: Sem cliente ·"
        " Status: Todos",
        "Expediente: o da instalação (seg–sex 08:00–18:00; a partir de 15/10/2026, seg–sáb"
        " 08:00–12:00), o do grupo Suporte (2 pessoas), o de outro grupo (1 pessoa) e o próprio"
        " de Ana · 1 feriado(s) cadastrado(s)",
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
    assert pagina.generated.startswith("Gerado em ") and " por " not in pagina.generated
    assert pagina.numbering == "Página {n} de {total}" and not pagina.landscape
    assert pagina.continued == "{titulo} (continuação)"
    titulo, linhas, blocos, pagina, *_ = chamadas[1]
    assert titulo == "Hours report" and linhas[0].startswith("2026-10-01 to 2026-10-31 · ")
    assert linhas[1] == (
        "Working hours: the default hours (Mon–Fri 08:00–18:00; from 2026-10-15, Mon–Sat"
        " 08:00–12:00), team Suporte's hours (2 people), another team's hours (1 person) and"
        " Ana's own hours · 1 holiday(s) registered"
    )
    assert blocos[3].note == "Showing the first 200 of 250 tasks. The CSV has all of them."
    assert pagina.numbering == "Page {n} of {total}"
