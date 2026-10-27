"""PDF de um modelo de relatório, o relatório para o cliente (docs/14 §14.8.5 e §14.8.6) e o
relatório de horas da API (§14.7, `render_hours`).

O desenho recebe os textos prontos, já traduzidos e formatados por quem chama (a tela,
web/reports_downloads.py, que é quem sabe o idioma e o formato das horas). A exceção é o PDF da
API (`GET /reports/pdf`), que não passa pela tela: `render_hours` monta os blocos fixos dele a
partir do `service.build`, com os textos de `HOURS_TEXTS` (os módulos não dependem de web/, onde
estão os catálogos da tela). Os gráficos são desenhados no próprio ReportLab, em vetor, como os
da tela e com as mesmas cores de série do modo claro (`Series`, web/palette.py). Fontes padrão do
PDF, sem pacotes do sistema. A página (A4 em pé ou deitado) e o rodapé de cada uma, com o número
dela, vêm em `Page`.
"""

import io
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, Literal
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from chamados.core.i18n import Locale
from chamados.modules.reports.schemas import Report
from chamados.modules.reports.service import TZ, Filters, ScheduleUse, describe_use

INK = colors.HexColor("#171717")
MUTED = colors.HexColor("#525252")
RULE = colors.HexColor("#E5E5E5")
HEAD = colors.HexColor("#F5F5F5")
MARGIN = 15 * mm
CHART_HEIGHT = 48 * mm
FOOT_SIZE = 7.5  # o corpo do rodapé de cada página
FOOT_LEADING = 9
FOOT_BASE = 10 * mm  # a linha de baixo do rodapé, a partir da borda da folha
FOOT_LINES = 3  # o texto livre do rodapé, no máximo em três linhas


@dataclass
class Page:
    """A página e o rodapé de cada uma: `generated` ("Gerado em…") à esquerda e `numbering` à
    direita ("Página {n} de {total}", com os marcadores), e, acima deles, o texto livre do
    modelo (`footer`; vazio, nada)."""

    generated: str
    numbering: str
    footer: str = ""
    landscape: bool = False

    @property
    def size(self) -> tuple[float, float]:
        return landscape(A4) if self.landscape else A4

    @property
    def width(self) -> float:
        """A largura útil (sem as margens): a dos blocos."""
        return self.size[0] - 2 * MARGIN

    def footer_lines(self) -> list[str]:
        if not self.footer.strip():
            return []
        lines = simpleSplit(_sanitize(self.footer), "Helvetica", FOOT_SIZE, self.width)
        return list(lines[:FOOT_LINES])


@dataclass
class Cards:
    title: str
    items: list[tuple[str, str, str]]  # rótulo, valor, nota (a comparação; vazia sem ela)
    big: bool = False  # o número grande (uma medida só)
    subtitle: str = ""  # o período e o filtro próprios do bloco (vazio sem eles)


@dataclass
class Chart:
    """Um gráfico: `kind` é bars, columns, stacked, line ou combo. Cada ponto é (rótulo, valor,
    parte de cima nas empilhadas ou o valor da linha nas barras + linha, valor escrito);
    `ticks`, as marcas do eixo (valor, texto); `before`, o valor do período comparado na
    posição de cada ponto (comparar; None onde não há), desenhado mais claro."""

    title: str
    kind: str
    points: list[tuple[str, int, int, str]]
    ticks: list[tuple[int, str]] = field(default_factory=list)
    legend: tuple[str, str] | None = None
    empty: str = ""
    before: list[int | None] = field(default_factory=list)
    reference: tuple[int, str] | None = None  # a linha de referência: o valor e o nome
    area: bool = False  # a linha com a área preenchida
    subtitle: str = ""
    scale: float = 1.0  # a altura escolhida no bloco, sobre a média (CHART_HEIGHT)
    color: str = "chart-1"  # o token da cor da série (`Series.named`)


@dataclass
class Grid:
    """Uma tabela: as linhas já em texto; `total`, a linha do total (sem o rótulo)."""

    title: str
    columns: list[str]
    rows: list[list[str]]
    total: list[str] | None = None
    total_label: str = ""
    empty: str = ""
    note: str = ""
    subtitle: str = ""


@dataclass
class Heatmap:
    """O mapa de calor: as horas (rótulos de cima), cada dia (rótulo e o tom de cada hora, de 0,
    sem nada, a 5) e a legenda (tom, texto)."""

    title: str
    hours: list[str]
    days: list[tuple[str, list[int]]]
    legend: list[tuple[int, str]]
    empty: str = ""
    subtitle: str = ""
    scale: float = 1.0  # a altura das linhas, sobre a média


Block = Cards | Chart | Grid | Heatmap


@dataclass
class Series:
    """As cores dos gráficos: a série (`chart-1`, a primary, ou a cor do bloco), as horas extras
    das colunas empilhadas e a linha das barras + linha (`chart-2`) e o período comparado
    (`chart-before`); `named`, as de cada token, para a cor escolhida no bloco (`Chart.color`)."""

    first: colors.Color
    second: colors.Color
    before: colors.Color
    heat: list[colors.Color] = field(default_factory=list)  # `heat-1` a `heat-5`
    named: dict[str, colors.Color] = field(default_factory=dict)


def _sanitize(text: str) -> str:
    # As fontes padrão do PDF (WinAnsi) não têm o sinal de menos (U+2212).
    return text.replace("−", "-")


def _styles() -> dict[str, ParagraphStyle]:
    sheet = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=sheet["BodyText"], fontSize=9, leading=12, textColor=INK)
    return {
        "body": body,
        "muted": ParagraphStyle("muted", parent=body, textColor=MUTED),
        "value": ParagraphStyle("value", parent=body, fontSize=14, leading=18),
        "big": ParagraphStyle("big", parent=body, fontSize=32, leading=38),
        "h1": ParagraphStyle(
            "h1", parent=sheet["Heading1"], fontSize=16, textColor=INK, spaceAfter=2
        ),
        "h2": ParagraphStyle(
            "h2", parent=sheet["Heading2"], fontSize=11, textColor=INK, spaceBefore=10, spaceAfter=4
        ),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(_sanitize(text)), style)


def _head(block: Block, st: dict[str, ParagraphStyle]) -> list[Flowable]:
    """O título do bloco e, quando ele tem período ou filtro próprio, o subtítulo que os diz."""
    flow: list[Flowable] = [_p(block.title, st["h2"])] if block.title else []
    if block.subtitle:
        flow.append(_p(block.subtitle, st["muted"]))
    return flow


PADDING = 12  # o respiro de uma célula da tabela (6 pt de cada lado, o padrão do ReportLab)


def _widths(texts: list[list[str]], width: float, size: float) -> list[float]:
    """A largura de cada coluna pelo texto mais longo dela: as que cabem na parte igual
    (`width` / colunas) ficam com o que precisam; as outras ficam com a parte igual e dividem o
    que sobra na proporção do que passariam dela (uma coluna longa, como o título, não espreme
    uma média, como o status, abaixo das curtas). Se todas cabem, crescem na proporção."""
    columns = zip(*texts, strict=True)
    need = [max(stringWidth(c, "Helvetica", size) for c in col) + PADDING for col in columns]
    fair = width / len(need)
    over = sum(n - fair for n in need if n > fair)
    if not over:
        return [n * width / sum(need) for n in need]
    spare = width - sum(min(n, fair) for n in need)
    return [n if n <= fair else fair + (n - fair) / over * spare for n in need]


def _cell(text: str, style: ParagraphStyle, width: float) -> str | Paragraph:
    """O texto que cabe numa linha vai como texto simples (no corpo da tabela); só o que precisa
    quebrar vira Paragraph: um Paragraph por célula levava segundos numa tabela longa."""
    text = _sanitize(text)
    if "\n" not in text and stringWidth(text, style.fontName, style.fontSize) <= width - PADDING:
        return text
    return Paragraph(escape(text), style)


def _grid(block: Grid, st: dict[str, ParagraphStyle], width: float) -> list[Flowable]:
    flow = _head(block, st)
    if not block.rows:
        return [*flow, _p(block.empty, st["muted"])]
    body = st["body"]
    texts = [block.columns, *block.rows]
    if block.total is not None:
        texts.append([block.total_label, *block.total])
    widths = _widths([[_sanitize(c) for c in row] for row in texts], width, body.fontSize)
    data: list[list[str | Paragraph]] = [[_p(c, st["muted"]) for c in block.columns]]
    data += [[_cell(c, body, w) for c, w in zip(row, widths, strict=True)] for row in texts[1:]]
    table = Table(data, colWidths=widths, repeatRows=1)
    style: list[Any] = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONT", (0, 1), (-1, -1), body.fontName, body.fontSize, body.leading),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
    ]
    if block.total is not None:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 1, INK))
    table.setStyle(TableStyle(style))
    flow.append(table)
    if block.note:
        flow.append(_p(block.note, st["muted"]))
    return flow


def _cards(block: Cards, st: dict[str, ParagraphStyle], width: float) -> list[Flowable]:
    cells = [
        [
            _p(label, st["muted"]),
            _p(value, st["big" if block.big else "value"]),
            *([_p(note, st["muted"])] if note else []),
        ]
        for label, value, note in block.items
    ]
    per_row = min(4, len(cells)) or 1
    rows = [cells[i : i + per_row] for i in range(0, len(cells), per_row)]
    rows[-1] += [[]] * (per_row - len(rows[-1]))
    table = Table(rows, colWidths=[width / per_row] * per_row)
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return [*(_head(block, st) or [Spacer(1, 6)]), table]


def _rect(x: float, y: float, width: float, height: float, color: colors.Color) -> Rect:
    # As propriedades vão depois: os stubs do ReportLab tipam mal os argumentos nomeados.
    rect = Rect(x, y, width, height)
    rect.fillColor, rect.strokeWidth, rect.strokeColor = color, 0, None
    return rect


def _text(x: float, y: float, text: str, size: float = 7, color: colors.Color = MUTED,
          anchor: Literal["start", "middle", "end"] = "start") -> String:  # fmt: skip
    return String(x, y, _sanitize(text), fontName="Helvetica", fontSize=size, fillColor=color,
                  textAnchor=anchor)  # fmt: skip


def _short(text: str, size: int = 28) -> str:
    return text if len(text) <= size else text[: size - 1] + "…"


def _bars(block: Chart, primary: colors.Color, width: float) -> Drawing:
    row = 14
    label_width = 45 * mm
    area = width - label_width - 22 * mm
    top = max([1, *(p[1] for p in block.points)])
    drawing = Drawing(width, row * len(block.points) + 2)
    for i, (label, value, _, text) in enumerate(block.points):
        y = drawing.height - (i + 1) * row
        drawing.add(_text(0, y + 3, _short(label)))
        length = value / top * area
        if length > 0:
            drawing.add(_rect(label_width, y + 1, length, row - 4, primary))
        drawing.add(_text(label_width + length + 3, y + 3, text, color=INK))
    return drawing


def _columns(block: Chart, series: Series, page_width: float) -> Drawing:
    primary = series.first
    axis = 16 * mm
    bottom = 10
    full = CHART_HEIGHT * block.scale
    height = full - bottom
    area = page_width - axis
    drawing = Drawing(page_width, full)
    top = max([1, *(value for value, _ in block.ticks)])
    for value, text in block.ticks:
        y = bottom + value / top * height
        drawing.add(Line(axis, y, page_width, y, strokeColor=RULE, strokeWidth=0.5))
        drawing.add(_text(axis - 3, y - 2, text, anchor="end"))
    count = max(1, len(block.points))
    slot = area / count
    every = max(1, -(-count // 6))  # uns seis rótulos embaixo
    line: list[float] = []
    old: list[float] = []  # a linha de antes
    second: list[float] = []  # a linha das barras + linha
    for i, (label, value, extra, _) in enumerate(block.points):
        x = axis + i * slot
        if i % every == 0:
            drawing.add(_text(x + slot / 2, 0, _short(label, 14), anchor="middle"))
        h = value / top * height
        before = block.before[i] if i < len(block.before) else None
        if block.kind == "line":
            line += [x + slot / 2, bottom + h]
            if before is not None:
                old += [x + slot / 2, bottom + before / top * height]
            continue
        width = min(slot * 0.8, 18)
        left = x + (slot - width) / 2
        if before is not None:  # a de antes à esquerda; as duas na metade da largura
            width /= 2
            if before:
                drawing.add(_rect(left, bottom, width, before / top * height, series.before))
            left += width
        if block.kind == "combo":
            second += [x + slot / 2, bottom + extra / top * height]
        if block.kind == "stacked" and value:
            lower = (value - extra) / top * height
            drawing.add(_rect(left, bottom, width, lower, primary))
            drawing.add(_rect(left, bottom + lower, width, h - lower, series.second))
        elif value:
            drawing.add(_rect(left, bottom, width, h, primary))
    if block.reference is not None:
        value, text = block.reference
        y = bottom + value / top * height
        drawing.add(
            Line(axis, y, page_width, y, strokeColor=MUTED, strokeWidth=1, strokeDashArray=[4, 3])
        )
        # O nome acima da linha; no topo do gráfico, abaixo dela, para não sair do desenho.
        drawing.add(_text(page_width, y + 2 if y + 10 < full else y - 8, text, anchor="end"))
    if line and block.area:
        fill = colors.Color(primary.red, primary.green, primary.blue, alpha=0.15)
        drawing.add(
            Polygon([line[0], bottom, *line, line[-2], bottom], fillColor=fill, strokeWidth=0)
        )
    if len(old) >= 4:
        drawing.add(
            PolyLine(old, strokeColor=series.before, strokeWidth=1.5, strokeDashArray=[3, 2])
        )
    if second:
        drawing.add(PolyLine(second, strokeColor=series.second, strokeWidth=1.5))
        for j in range(0, len(second), 2):
            drawing.add(
                Circle(second[j], second[j + 1], 1.8, fillColor=series.second, strokeWidth=0)
            )
    if line:
        drawing.add(PolyLine(line, strokeColor=primary, strokeWidth=1.5))
        for j in range(0, len(line), 2):
            drawing.add(Circle(line[j], line[j + 1], 1.8, fillColor=primary, strokeWidth=0))
    return drawing


def _chart(
    block: Chart, st: dict[str, ParagraphStyle], series: Series, width: float
) -> list[Flowable]:
    flow = _head(block, st)
    if not block.points:
        return [*flow, _p(block.empty, st["muted"])]
    series = replace(series, first=series.named.get(block.color, series.first))
    if block.kind == "bars":
        flow.append(_bars(block, series.first, width))
    else:
        flow.append(_columns(block, series, width))
    if block.legend:
        legend = Drawing(width, 12)
        x = 0.0
        second = series.second if block.kind in ("stacked", "combo") else series.before
        for color, label in zip((series.first, second), block.legend, strict=True):
            legend.add(_rect(x, 2, 7, 7, color))
            legend.add(_text(x + 10, 3, label, size=8))
            x += 10 + len(label) * 4.5 + 12
        flow.append(legend)
    return [KeepTogether(flow)]


def _heatmap(
    block: Heatmap, st: dict[str, ParagraphStyle], series: Series, width: float
) -> list[Flowable]:
    flow = _head(block, st)
    if not block.legend:
        return [*flow, _p(block.empty, st["muted"])]
    label = 10 * mm
    cell = (width - label) / len(block.hours)
    row = 5 * mm * block.scale
    tones = [colors.white, *series.heat]  # sem nada, a célula vazia, só com a borda
    drawing = Drawing(width, row * (len(block.days) + 1))
    for i, hour in enumerate(block.hours):
        if i % 3 == 0:
            drawing.add(
                _text(label + i * cell + cell / 2, drawing.height - 8, hour, anchor="middle")
            )
    for d, (name, levels) in enumerate(block.days):
        y = drawing.height - (d + 2) * row
        drawing.add(_text(0, y + 4, name))
        for i, level in enumerate(levels):
            box = _rect(label + i * cell + 0.4, y + 0.4, cell - 0.8, row - 0.8, tones[level])
            if not level:
                box.strokeColor, box.strokeWidth = RULE, 0.5
            drawing.add(box)
    legend = Drawing(width, 12)
    x = 0.0
    for level, text in block.legend:
        swatch = _rect(x, 2, 7, 7, tones[level])
        if not level:
            swatch.strokeColor, swatch.strokeWidth = RULE, 0.5
        legend.add(swatch)
        legend.add(_text(x + 10, 3, text, size=8))
        x += 10 + len(text) * 4.5 + 12
    return [KeepTogether([*flow, drawing, legend])]


def _footer(canvas: Canvas, page: Page, number: int, total: int) -> None:
    """O rodapé de uma página: o texto livre do modelo, o "Gerado em…" e o número da página."""
    canvas.saveState()
    canvas.setFont("Helvetica", FOOT_SIZE)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, FOOT_BASE, _sanitize(page.generated))
    numbering = page.numbering.replace("{n}", str(number)).replace("{total}", str(total))
    canvas.drawRightString(MARGIN + page.width, FOOT_BASE, _sanitize(numbering))
    for k, line in enumerate(reversed(page.footer_lines()), 1):
        canvas.drawString(MARGIN, FOOT_BASE + k * FOOT_LEADING, line)
    canvas.restoreState()


def _numbered(page: Page) -> type[Canvas]:
    """O canvas que guarda cada página e só a desenha no fim, quando já sabe o total (o "de 5"
    do "Página 2 de 5")."""

    class Numbered(Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self) -> None:
            self._pages.append(dict(self.__dict__))
            self._startPage()  # type: ignore[attr-defined]  # fora dos stubs do ReportLab

        def save(self) -> None:
            for number, state in enumerate(self._pages, 1):
                self.__dict__.update(state)
                _footer(self, page, number, len(self._pages))
                super().showPage()
            super().save()

    return Numbered


def _document(story: list[Flowable], title: str, page: Page) -> bytes:
    buffer = io.BytesIO()
    # O rodapé ocupa a linha do "Gerado em…" e as do texto livre, com um respiro acima.
    footer = FOOT_BASE + FOOT_LEADING * (len(page.footer_lines()) + 1) + 4 * mm
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page.size,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=max(MARGIN, footer),
        title=_sanitize(title),
    )
    doc.build(story, canvasmaker=_numbered(page))
    return buffer.getvalue()


def render_model(
    title: str,
    lines: list[str],
    blocks: list[Block],
    page: Page,
    series: dict[str, str],
    heat: tuple[str, ...],
) -> bytes:
    """O PDF de um modelo: o título, as linhas de cabeçalho (descrição, período, filtros,
    expediente), os blocos na ordem e, em cada página, o rodapé (`page`). `series`: as cores da
    paleta por token (`chart-1` a `chart-4` e `chart-before`); `heat`, as do mapa de calor."""
    st = _styles()
    width = page.width
    named = {token: colors.HexColor(c) for token, c in series.items()}
    palette = Series(
        named["chart-1"],
        named["chart-2"],
        named["chart-before"],
        [colors.HexColor(c) for c in heat],
        named,
    )
    story: list[Flowable] = [_p(title, st["h1"])]
    story += [_p(line, st["muted"]) for line in lines]
    for block in blocks:
        if isinstance(block, Cards):
            story += _cards(block, st, width)
        elif isinstance(block, Chart):
            story += _chart(block, st, palette, width)
        elif isinstance(block, Heatmap):
            story += _heatmap(block, st, palette, width)
        else:
            story += _grid(block, st, width)
    return _document(story, title, page)


def _free(text: str, style: ParagraphStyle) -> list[Flowable]:
    """Um texto livre do modelo (escapado), com as quebras de linha de quem escreveu."""
    if not text.strip():
        return []
    return [Paragraph(escape(_sanitize(text.strip())).replace("\n", "<br/>"), style)]


def render_client(
    logo: bytes | None,
    title: str,
    lines: list[str],
    intro: str,
    totals: list[tuple[str, str]],
    tickets: Grid,
    notes: str,
    page: Page,
) -> bytes:
    """O relatório para o cliente: o logotipo da instalação, o título, o cliente e o período, o
    texto de abertura, os totais, os chamados e as observações. Nada de organização interna
    (quem chama já deixou de fora)."""
    st = _styles()
    width = page.width
    head: list[Flowable] = [_p(title, st["h1"]), *(_p(line, st["body"]) for line in lines)]
    story: list[Flowable]
    if logo:
        image = ImageReader(io.BytesIO(logo))
        natural, tall = image.getSize()
        scale = min(40 * mm / natural, 18 * mm / tall)
        picture = Image(io.BytesIO(logo), width=natural * scale, height=tall * scale)
        header = Table([[picture, head]], colWidths=[45 * mm, width - 45 * mm])
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story = [header]
    else:
        story = head
    if intro.strip():
        story += [Spacer(1, 8), *_free(intro, st["body"])]
    story += _cards(Cards("", [(label, value, "") for label, value in totals]), st, width)
    story += [Spacer(1, 4), *_grid(tickets, st, width)]
    if notes.strip():
        story += [Spacer(1, 8), *_free(notes, st["body"])]
    return _document(story, title, page)


# --- O PDF da API (§14.7) --------------------------------------------------------------------

# Os textos do PDF da API, no idioma do `locale` (ou do Accept-Language). Ficam aqui, e não nos
# catálogos da tela (web/locales), porque os módulos não dependem de web/; são poucos e só deste
# PDF.
HOURS_TEXTS: dict[Locale, dict[str, str]] = {
    "pt-BR": {
        "title": "Relatório de horas",
        "period": "{start} a {end}",
        "team": "Grupo",
        "person": "Pessoa",
        "client": "Cliente",
        "status": "Status",
        "all": "Todos",
        "work_hours": "Expediente",
        "holidays": "{n} feriado(s) cadastrado(s)",
        "generated": "Gerado em {when} por {who}",
        "page": "Página {n} de {total}",
        "hours": "Horas",
        "overtime": "Horas extras",
        "tasks": "Tarefas",
        "opened": "Chamados registrados",
        "closed": "Chamados concluídos",
        "by_person": "Por pessoa",
        "by_client": "Por cliente",
        "overtime_tasks": "Tarefas fora do expediente",
        "no_client": "Sem cliente",
        "when": "Quando",
        "ticket": "Chamado",
        "time": "Tempo",
        "outside": "Fora do expediente",
        "empty": "Nada no período.",
        "cut": "Mostrando as {n} primeiras de {total} tarefas. O CSV traz todas.",
        "weekdays": "seg,ter,qua,qui,sex,sáb,dom",
    },
    "en": {
        "title": "Hours report",
        "period": "{start} to {end}",
        "team": "Team",
        "person": "Person",
        "client": "Client",
        "status": "Status",
        "all": "All",
        "work_hours": "Working hours",
        "holidays": "{n} holiday(s) registered",
        "generated": "Generated on {when} by {who}",
        "page": "Page {n} of {total}",
        "hours": "Hours",
        "overtime": "Overtime",
        "tasks": "Tasks",
        "opened": "Tickets opened",
        "closed": "Tickets closed",
        "by_person": "By person",
        "by_client": "By client",
        "overtime_tasks": "Tasks outside working hours",
        "no_client": "No client",
        "when": "When",
        "ticket": "Ticket",
        "time": "Time",
        "outside": "Outside working hours",
        "empty": "Nothing in this period.",
        "cut": "Showing the first {n} of {total} tasks. The CSV has all of them.",
        "weekdays": "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
    },
}
# O "Expediente usado" do PDF da API (`service.describe_use`), com as chaves do catálogo da tela
# (relatorios.expedientes.*).
USE_TEXTS: dict[Locale, dict[str, str]] = {
    "pt-BR": {
        "instalacao": "o da instalação ({horario})",
        "aPartir": "a partir de {data}, {horario}",
        "grupo1": "o do grupo {grupo} (1 pessoa)",
        "grupoN": "o do grupo {grupo} ({n} pessoas)",
        "outroGrupo1": "o de outro grupo (1 pessoa)",
        "outroGrupoN": "o de outro grupo ({n} pessoas)",
        "proprio1": "o próprio de {nomes}",
        "proprioN": "o próprio de {n} pessoas ({nomes})",
        "mais": "mais {n}",
        "e": "{inicio} e {fim}",
    },
    "en": {
        "instalacao": "the default hours ({horario})",
        "aPartir": "from {data}, {horario}",
        "grupo1": "team {grupo}'s hours (1 person)",
        "grupoN": "team {grupo}'s hours ({n} people)",
        "outroGrupo1": "another team's hours (1 person)",
        "outroGrupoN": "another team's hours ({n} people)",
        "proprio1": "{nomes}'s own hours",
        "proprioN": "own hours for {n} people ({nomes})",
        "mais": "{n} more",
        "e": "{inicio} and {fim}",
    },
}
HOURS_LISTED = 200  # as tarefas fora do expediente no PDF, como a lista da tela


def _hours(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


def _day(d: date, locale: Locale) -> str:
    return d.strftime("%d/%m/%Y" if locale == "pt-BR" else "%Y-%m-%d")


def _moment(dt: datetime, locale: Locale) -> str:
    local = dt.astimezone(TZ)
    return f"{_day(local.date(), locale)} {local:%H:%M}"


def render_hours(report: Report, f: Filters, use: ScheduleUse, who: str, locale: Locale) -> bytes:
    """O PDF de `GET /reports/pdf`, um modelo fixo com o conteúdo de sempre: o período, os
    filtros e o expediente usado no cabeçalho (`use`), os totais, por pessoa, por cliente e as
    tarefas fora do expediente (as `HOURS_LISTED` primeiras, com a nota), em A4 em pé."""
    t = HOURS_TEXTS[locale]
    wh = report.work_hours
    work = describe_use(
        use,
        lambda key, **values: USE_TEXTS[locale][key].format(**values),
        t["weekdays"].split(","),
        lambda day: _day(day, locale),
    )
    if wh.holidays:
        work += f" · {t['holidays'].format(n=len(wh.holidays))}"
    filters = " · ".join(
        f"{t[k]}: {', '.join(v) or t['all']}"
        for k, v in (
            ("team", [x.name for x in f.teams]),
            ("person", [x.display_name for x in f.people]),
            ("client", [x.label for x in f.clients] + ([t["no_client"]] if f.no_client else [])),
            ("status", [x.name for x in f.statuses]),
        )
    )
    tot = report.totals
    listed = report.overtime_tasks[:HOURS_LISTED]
    total = len(report.overtime_tasks)
    blocks: list[Block] = [
        Cards(
            "",
            [
                (t["hours"], _hours(tot.minutes), ""),
                (t["overtime"], _hours(tot.overtime_minutes), ""),
                (t["tasks"], str(tot.tasks), ""),
                (t["opened"], str(tot.tickets_opened), ""),
                (t["closed"], str(tot.tickets_closed), ""),
            ],
        ),
        Grid(
            t["by_person"],
            [t["person"], t["hours"], t["overtime"], t["tasks"], t["closed"]],
            [
                [
                    r.name,
                    _hours(r.minutes),
                    _hours(r.overtime_minutes),
                    str(r.tasks),
                    str(r.tickets_closed),
                ]
                for r in report.people
            ],
            empty=t["empty"],
        ),
        Grid(
            t["by_client"],
            [t["client"], t["hours"], t["opened"], t["closed"]],
            [
                [
                    r.name or t["no_client"],
                    _hours(r.minutes),
                    str(r.tickets_opened),
                    str(r.tickets_closed),
                ]
                for r in report.clients
            ],
            empty=t["empty"],
        ),
        Grid(
            t["overtime_tasks"],
            [t["when"], t["person"], t["ticket"], t["time"], t["outside"]],
            [
                [
                    _moment(r.done_at, locale),
                    r.person,
                    f"#{r.ticket_number} {r.ticket_title}",
                    _hours(r.minutes),
                    _hours(r.overtime_minutes),
                ]
                for r in listed
            ],
            empty=t["empty"],
            note=t["cut"].format(n=len(listed), total=total) if total > len(listed) else "",
        ),
    ]
    lines = [
        t["period"].format(start=_day(report.start, locale), end=_day(report.end, locale)),
        filters,
        f"{t['work_hours']}: {work}",
    ]
    page = Page(
        t["generated"].format(when=_moment(datetime.now(TZ), locale), who=who),
        t["page"],
    )
    # As cores não importam: o PDF da API não tem gráficos.
    black = {token: "#000000" for token in ("chart-1", "chart-2", "chart-before")}
    return render_model(t["title"], lines, blocks, page, black, ())
