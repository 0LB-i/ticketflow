"""Relatório em PDF (docs/14 §14.7): os números da tela, em tabelas, no idioma de quem pede."""

import io
from datetime import date, datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from chamados.core.i18n import Locale
from chamados.modules.reports.schemas import Report
from chamados.modules.reports.service import TZ, Filters

TEXTS: dict[Locale, dict[str, str]] = {
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
        "weekdays": "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
    },
}

INK = colors.HexColor("#171717")
MUTED = colors.HexColor("#525252")
RULE = colors.HexColor("#E5E5E5")
HEAD = colors.HexColor("#F5F5F5")


def hours(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


def _day(d: date, locale: Locale) -> str:
    return d.strftime("%d/%m/%Y" if locale == "pt-BR" else "%Y-%m-%d")


def _moment(dt: datetime, locale: Locale) -> str:
    local = dt.astimezone(TZ)
    return f"{_day(local.date(), locale)} {local:%H:%M}"


def render(report: Report, f: Filters, who: str, locale: Locale) -> bytes:
    t = TEXTS[locale]
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12, textColor=INK)
    muted = ParagraphStyle("muted", parent=body, textColor=MUTED)
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, textColor=INK, spaceAfter=2)
    h2 = ParagraphStyle(
        "h2", parent=styles["Heading2"], fontSize=11, textColor=INK, spaceBefore=10, spaceAfter=4
    )

    def p(text: str, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(text), style)

    def table(
        head: list[str], rows: list[list[str | Paragraph]], widths: list[float]
    ) -> Table | Paragraph:
        """Só o texto que pode quebrar (nomes, títulos) vai como Paragraph; números e datas, como
        texto simples, no mesmo corpo: um Paragraph por célula levava segundos num mês cheio."""
        if not rows:
            return p(t["empty"], muted)
        data: list[list[str | Paragraph]] = [[p(h, muted) for h in head], *rows]
        tbl = Table(data, colWidths=widths, repeatRows=1)
        tbl.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HEAD),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONT", (0, 1), (-1, -1), body.fontName, body.fontSize, body.leading),
                    ("TEXTCOLOR", (0, 1), (-1, -1), INK),
                ]
            )
        )
        return tbl

    weekdays = t["weekdays"].split(",")
    wh = report.work_hours
    work = f"{', '.join(weekdays[d] for d in wh.weekdays)} · {wh.start:%H:%M}–{wh.end:%H:%M}"
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
    width = A4[0] - 30 * mm

    story = [
        p(t["title"], h1),
        p(t["period"].format(start=_day(report.start, locale), end=_day(report.end, locale))),
        p(filters, muted),
        p(f"{t['work_hours']}: {work}", muted),
        Spacer(1, 6),
        table(
            [t["hours"], t["overtime"], t["tasks"], t["opened"], t["closed"]],
            [
                [
                    hours(tot.minutes),
                    hours(tot.overtime_minutes),
                    str(tot.tasks),
                    str(tot.tickets_opened),
                    str(tot.tickets_closed),
                ]
            ],
            [width / 5] * 5,
        ),
        p(t["by_person"], h2),
        table(
            [t["person"], t["hours"], t["overtime"], t["tasks"], t["closed"]],
            [
                [
                    p(r.name),
                    hours(r.minutes),
                    hours(r.overtime_minutes),
                    str(r.tasks),
                    str(r.tickets_closed),
                ]
                for r in report.people
            ],
            [width * 0.36] + [width * 0.16] * 4,
        ),
        p(t["by_client"], h2),
        table(
            [t["client"], t["hours"], t["opened"], t["closed"]],
            [
                [
                    p(r.name or t["no_client"]),
                    hours(r.minutes),
                    str(r.tickets_opened),
                    str(r.tickets_closed),
                ]
                for r in report.clients
            ],
            [width * 0.43] + [width * 0.19] * 3,
        ),
        p(t["overtime_tasks"], h2),
        table(
            [t["when"], t["person"], t["ticket"], t["time"], t["outside"]],
            [
                [
                    _moment(r.done_at, locale),
                    p(r.person),
                    p(f"#{r.ticket_number} {r.ticket_title}"),
                    hours(r.minutes),
                    hours(r.overtime_minutes),
                ]
                for r in report.overtime_tasks
            ],
            [width * 0.17, width * 0.2, width * 0.39, width * 0.1, width * 0.14],
        ),
        Spacer(1, 10),
        p(
            t["generated"].format(when=_moment(datetime.now(TZ), locale), who=who),
            muted,
        ),
    ]
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=t["title"],
    )
    doc.build(story)
    return buffer.getvalue()
