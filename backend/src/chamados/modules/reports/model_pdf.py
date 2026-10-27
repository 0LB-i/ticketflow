"""PDF de um modelo de relatório e o relatório para o cliente (docs/14 §14.8.5 e §14.8.6).

Este módulo só desenha: os textos chegam prontos, já traduzidos e formatados por quem chama (a
tela, web/reports.py, que é quem sabe o idioma e o formato das horas). Os gráficos são desenhados
no próprio ReportLab, em vetor, como os da tela e com as mesmas cores de série do modo claro
(`Series`, web/palette.py). Fontes padrão do PDF, sem pacotes do sistema.
"""

import io
from dataclasses import dataclass, field, replace
from typing import Any, Literal
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
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

INK = colors.HexColor("#171717")
MUTED = colors.HexColor("#525252")
RULE = colors.HexColor("#E5E5E5")
HEAD = colors.HexColor("#F5F5F5")
WIDTH = A4[0] - 30 * mm
CHART_HEIGHT = 48 * mm


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


def _grid(block: Grid, st: dict[str, ParagraphStyle]) -> list[Flowable]:
    flow = _head(block, st)
    if not block.rows:
        return [*flow, _p(block.empty, st["muted"])]
    data = [[_p(c, st["muted"]) for c in block.columns]]
    data += [[_p(c, st["body"]) for c in row] for row in block.rows]
    if block.total is not None:
        data.append([_p(block.total_label, st["body"]), *(_p(c, st["body"]) for c in block.total)])
    first = WIDTH * (0.4 if len(block.columns) > 2 else 0.6)
    rest = (WIDTH - first) / max(1, len(block.columns) - 1)
    table = Table(data, colWidths=[first] + [rest] * (len(block.columns) - 1), repeatRows=1)
    style: list[Any] = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if block.total is not None:
        style.append(("LINEABOVE", (0, -1), (-1, -1), 1, INK))
    table.setStyle(TableStyle(style))
    flow.append(table)
    if block.note:
        flow.append(_p(block.note, st["muted"]))
    return flow


def _cards(block: Cards, st: dict[str, ParagraphStyle]) -> list[Flowable]:
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
    table = Table(rows, colWidths=[WIDTH / per_row] * per_row)
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


def _bars(block: Chart, primary: colors.Color) -> Drawing:
    row = 14
    label_width = 45 * mm
    area = WIDTH - label_width - 22 * mm
    top = max([1, *(p[1] for p in block.points)])
    drawing = Drawing(WIDTH, row * len(block.points) + 2)
    for i, (label, value, _, text) in enumerate(block.points):
        y = drawing.height - (i + 1) * row
        drawing.add(_text(0, y + 3, _short(label)))
        width = value / top * area
        if width > 0:
            drawing.add(_rect(label_width, y + 1, width, row - 4, primary))
        drawing.add(_text(label_width + width + 3, y + 3, text, color=INK))
    return drawing


def _columns(block: Chart, series: Series) -> Drawing:
    primary = series.first
    axis = 16 * mm
    bottom = 10
    full = CHART_HEIGHT * block.scale
    height = full - bottom
    area = WIDTH - axis
    drawing = Drawing(WIDTH, full)
    top = max([1, *(value for value, _ in block.ticks)])
    for value, text in block.ticks:
        y = bottom + value / top * height
        drawing.add(Line(axis, y, WIDTH, y, strokeColor=RULE, strokeWidth=0.5))
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
            Line(axis, y, WIDTH, y, strokeColor=MUTED, strokeWidth=1, strokeDashArray=[4, 3])
        )
        # O nome acima da linha; no topo do gráfico, abaixo dela, para não sair do desenho.
        drawing.add(_text(WIDTH, y + 2 if y + 10 < full else y - 8, text, anchor="end"))
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


def _chart(block: Chart, st: dict[str, ParagraphStyle], series: Series) -> list[Flowable]:
    flow = _head(block, st)
    if not block.points:
        return [*flow, _p(block.empty, st["muted"])]
    series = replace(series, first=series.named.get(block.color, series.first))
    flow.append(_bars(block, series.first) if block.kind == "bars" else _columns(block, series))
    if block.legend:
        legend = Drawing(WIDTH, 12)
        x = 0.0
        second = series.second if block.kind in ("stacked", "combo") else series.before
        for color, label in zip((series.first, second), block.legend, strict=True):
            legend.add(_rect(x, 2, 7, 7, color))
            legend.add(_text(x + 10, 3, label, size=8))
            x += 10 + len(label) * 4.5 + 12
        flow.append(legend)
    return [KeepTogether(flow)]


def _heatmap(block: Heatmap, st: dict[str, ParagraphStyle], series: Series) -> list[Flowable]:
    flow = _head(block, st)
    if not block.legend:
        return [*flow, _p(block.empty, st["muted"])]
    label = 10 * mm
    cell = (WIDTH - label) / len(block.hours)
    row = 5 * mm * block.scale
    tones = [colors.white, *series.heat]  # sem nada, a célula vazia, só com a borda
    drawing = Drawing(WIDTH, row * (len(block.days) + 1))
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
    legend = Drawing(WIDTH, 12)
    x = 0.0
    for level, text in block.legend:
        swatch = _rect(x, 2, 7, 7, tones[level])
        if not level:
            swatch.strokeColor, swatch.strokeWidth = RULE, 0.5
        legend.add(swatch)
        legend.add(_text(x + 10, 3, text, size=8))
        x += 10 + len(text) * 4.5 + 12
    return [KeepTogether([*flow, drawing, legend])]


def _document(story: list[Flowable], title: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=_sanitize(title),
    )
    doc.build(story)
    return buffer.getvalue()


def render_model(
    title: str,
    lines: list[str],
    blocks: list[Block],
    footer: str,
    series: dict[str, str],
    heat: tuple[str, ...],
) -> bytes:
    """O PDF de um modelo: o título, as linhas de cabeçalho (período, filtros), os blocos na
    ordem e o rodapé (quando e quem gerou). `series`: as cores da paleta por token (`chart-1` a
    `chart-4` e `chart-before`); `heat`, as do mapa de calor."""
    st = _styles()
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
            story += _cards(block, st)
        elif isinstance(block, Chart):
            story += _chart(block, st, palette)
        elif isinstance(block, Heatmap):
            story += _heatmap(block, st, palette)
        else:
            story += _grid(block, st)
    story += [Spacer(1, 10), _p(footer, st["muted"])]
    return _document(story, title)


def render_client(
    logo: bytes | None,
    title: str,
    lines: list[str],
    totals: list[tuple[str, str]],
    tickets: Grid,
    footer: str,
) -> bytes:
    """O relatório para o cliente: o logotipo da instalação, o título, o cliente e o período, os
    totais e os chamados. Nada de organização interna (quem chama já deixou de fora)."""
    st = _styles()
    head: list[Flowable] = [_p(title, st["h1"]), *(_p(line, st["body"]) for line in lines)]
    story: list[Flowable]
    if logo:
        image = ImageReader(io.BytesIO(logo))
        width, height = image.getSize()
        scale = min(40 * mm / width, 18 * mm / height)
        picture = Image(io.BytesIO(logo), width=width * scale, height=height * scale)
        header = Table([[picture, head]], colWidths=[45 * mm, WIDTH - 45 * mm])
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story = [header]
    else:
        story = head
    story += _cards(Cards("", [(label, value, "") for label, value in totals]), st)
    story += [Spacer(1, 4), *_grid(tickets, st), Spacer(1, 10), _p(footer, st["muted"])]
    return _document(story, title)
