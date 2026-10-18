"""Formatação e Markdown das telas do servidor (as regras do formato.ts e do markdown.ts)."""

from datetime import UTC, datetime, timedelta

import pytest

from chamados.web.formatting import (
    SUGGESTED_TIMES,
    format_ago,
    format_datetime,
    format_duration,
    format_size,
    local_parts,
    parse_duration,
    parse_local,
)
from chamados.web.markdown import render_markdown

ANEXO = "0f3c2a1e-1111-2222-3333-444455556666"


def test_data_e_hora_no_fuso_de_sao_paulo() -> None:
    instante = datetime(2026, 10, 10, 2, 30, tzinfo=UTC)
    assert local_parts(instante) == ("2026-10-09", "23:30")
    assert parse_local("2026-10-09", "23:30") == instante
    assert parse_local("2026-13-01", "10:00") is None
    assert format_datetime("pt-BR", instante) == "09/10/2026, 23:30"
    assert format_datetime("en", instante) == "10/9/26, 11:30 PM"


def test_ha_quanto_tempo() -> None:
    agora = datetime(2026, 10, 17, 12, tzinfo=UTC)
    casos = [(30, "este minuto", "this minute"), (15 * 60, "há 15 min.", "15 min. ago")]
    casos += [(5 * 3600, "há 5 h", "5 hr. ago"), (86_400, "ontem", "yesterday")]
    casos += [(2 * 86_400, "anteontem", "2 days ago"), (40 * 86_400, "há 40 dias", "40 days ago")]
    for segundos, pt, en in casos:
        antes = agora - timedelta(seconds=segundos)
        assert (format_ago("pt-BR", antes, agora), format_ago("en", antes, agora)) == (pt, en)


def test_tempo_gasto() -> None:
    assert [format_duration(m) for m in (45, 60, 90, 125, 6000)] == [
        "45min",
        "1h",
        "1h30",
        "2h05",
        "100h",
    ]
    assert parse_duration("01:30") == 90
    assert parse_duration("24:00") == 1440
    assert parse_duration("") is None
    for texto in ("00:75", "00:00", "1:30", "1h30"):
        with pytest.raises(ValueError):
            parse_duration(texto)


def test_horarios_sugeridos() -> None:
    """20 e 30 min, de 15 em 15 até 3 h e de hora em hora até 24 h."""
    assert SUGGESTED_TIMES[:13] == [
        "00:20",
        "00:30",
        "00:45",
        "01:00",
        "01:15",
        "01:30",
        "01:45",
        "02:00",
        "02:15",
        "02:30",
        "02:45",
        "03:00",
        "04:00",
    ]
    assert SUGGESTED_TIMES[-1] == "24:00"
    assert len(SUGGESTED_TIMES) == 33


def test_tamanho_de_arquivo() -> None:
    assert format_size("pt-BR", 512) == "512 B"
    assert format_size("pt-BR", 1536) == "1,5 KB"
    assert format_size("en", 1536) == "1.5 KB"
    assert format_size("pt-BR", 12 * 1024 * 1024) == "12 MB"


def test_markdown_sem_html_digitado() -> None:
    html = render_markdown('**ok** <img src=x onerror="alert(1)">')
    assert "<strong>ok</strong>" in html
    assert "<img" not in html
    assert "&lt;img src=x" in html


def test_links_em_outra_aba_e_sem_javascript() -> None:
    html = render_markdown("[site](https://exemplo.com) [mau](javascript:alert(1))")
    assert '<a href="https://exemplo.com" target="_blank" rel="noopener noreferrer">' in html
    assert 'href="javascript' not in html


def test_so_imagens_anexadas_no_proprio_sistema() -> None:
    html = render_markdown(
        f"![print](/api/v1/attachments/{ANEXO}) ![x](https://rastreio.com/a.png)"
    )
    assert f'<img src="/api/v1/attachments/{ANEXO}" alt="print" loading="lazy">' in html
    assert '<img src="https://rastreio.com' not in html
    assert "https://rastreio.com/a.png" in html  # aparece como texto
