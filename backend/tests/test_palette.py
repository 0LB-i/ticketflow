"""Paleta derivada das 3 cores (docs/17 §17.2) e os contrastes da WCAG 2.1 AA (§17.3)."""

import pytest

from chamados.web.palette import (
    DEFAULT_COLORS,
    DEFAULT_PALETTE,
    PRESETS,
    Colors,
    Tokens,
    contrast,
    palette,
    stylesheet,
)


def _conferir(t: Tokens) -> None:
    for fundo in (t["bg"], t["surface"], t["surface-raised"]):
        assert contrast(t["fg"], fundo) >= 4.5, f"texto sobre {fundo}"
        assert contrast(t["muted"], fundo) >= 4.5, f"texto secundário sobre {fundo}"
        assert contrast(t["primary"], fundo) >= 4.5, f"link sobre {fundo}"
    assert contrast(t["on-primary"], t["primary"]) >= 4.5, "texto do botão"
    assert contrast(t["on-primary"], t["primary-hover"]) >= 4.5, "botão com o mouse"
    assert contrast(t["primary"], t["primary-subtle"]) >= 4.5, "item de menu ativo"
    assert contrast(t["border-input"], t["surface"]) >= 3, "borda de campo"
    assert contrast(t["focus"], t["surface"]) >= 3, "contorno de foco"


COMBINACOES: dict[str, Colors] = {
    "azul": {"brand": "#1D4ED8", "neutral": "#64748B", "background": "#F8FAFC"},
    "amarelo claro (difícil de ler)": {
        "brand": "#FDE047",
        "neutral": "#A3A3A3",
        "background": "#FFFFFF",
    },
    "laranja da marca com cinza claro": {
        "brand": "#F97316",
        "neutral": "#D4D4D4",
        "background": "#FFFFFF",
    },
    "marca quase preta": {"brand": "#111111", "neutral": "#737373", "background": "#FFFFFF"},
    "verde com fundo bege": {"brand": "#16A34A", "neutral": "#78716C", "background": "#FAF5E9"},
    "fundo cinza médio": {"brand": "#C2410C", "neutral": "#525252", "background": "#D4D4D4"},
}


def test_sem_personalizacao_usa_a_paleta_original() -> None:
    assert palette(None) is DEFAULT_PALETTE
    assert palette({**DEFAULT_COLORS, "brand": "#f97316"}) is DEFAULT_PALETTE
    assert stylesheet(None) == ""


def test_a_paleta_original_cumpre_os_contrastes() -> None:
    _conferir(DEFAULT_PALETTE["light"])
    _conferir(DEFAULT_PALETTE["dark"])


@pytest.mark.parametrize("cores", COMBINACOES.values(), ids=COMBINACOES.keys())
def test_ajusta_os_tons_e_cumpre_os_contrastes(cores: Colors) -> None:
    p = palette(cores)
    _conferir(p["light"])
    _conferir(p["dark"])
    assert p["light"]["brand"] == cores["brand"]
    assert p["light"]["surface"] == cores["background"]


@pytest.mark.parametrize("cores", PRESETS.values(), ids=PRESETS.keys())
def test_combinacoes_prontas_cumprem_os_contrastes(cores: Colors) -> None:
    _conferir(palette(cores)["light"])
    _conferir(palette(cores)["dark"])


def test_cor_ja_legivel_fica_como_foi_escolhida() -> None:
    assert palette({**DEFAULT_COLORS, "brand": "#1D4ED8"})["light"]["primary"] == "#1D4ED8"


def test_folha_de_estilo_sobrepoe_os_dois_modos() -> None:
    css = stylesheet(PRESETS["azul"])
    assert css.startswith("html:root{--tf-brand:#2563EB;")
    assert "}html.dark{--tf-brand:#2563EB;" in css


def test_folha_de_estilo_calculada_uma_vez_por_combinacao() -> None:
    """Toda tela embute a folha; a paleta (~2 ms) só é derivada na primeira vez."""
    cores = {"brand": "#2563eb", "neutral": "#64748B", "background": "#FFFFFF"}
    primeira = stylesheet(cores)
    antes = palette_cache_hits()
    assert stylesheet({k: v.upper() for k, v in cores.items()}) == primeira
    assert palette_cache_hits() == antes + 1


def palette_cache_hits() -> int:
    from chamados.web import palette as modulo

    return modulo._stylesheet.cache_info().hits
