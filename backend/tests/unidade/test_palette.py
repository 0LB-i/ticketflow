"""Paleta derivada das 3 cores (docs/17 §17.2) e os contrastes da WCAG 2.1 AA (§17.3)."""

import re
from itertools import combinations
from pathlib import Path

import pytest

import chamados.web
from chamados.web.palette import (
    DEFAULT_COLORS,
    DEFAULT_PALETTE,
    PRESETS,
    Colors,
    Mode,
    Tokens,
    contrast,
    distinct,
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
    # Séries dos gráficos: marcas, 3:1; a das horas extras se distingue da primeira (chart-1, a
    # primary) também para quem não enxerga vermelho ou verde.
    for fundo in (t["bg"], t["surface"]):
        assert contrast(t["chart-2"], fundo) >= 3, f"horas extras sobre {fundo}"
        assert contrast(t["chart-before"], fundo) >= 3, f"período anterior sobre {fundo}"
    assert distinct(t["chart-2"], t["primary"]), "horas extras × série"
    # O mapa de calor: cada tom mais longe do fundo que o anterior, e o mais forte com 3:1.
    calor = [contrast(t[f"heat-{k}"], t["surface"]) for k in range(1, 6)]
    assert calor == sorted(calor) and len(set(calor)) == 5, "escala do mapa de calor"
    assert calor[-1] >= 3, "o tom mais forte do mapa de calor"
    assert calor[0] >= 1.4, "o tom mais fraco do mapa de calor se vê sobre o fundo"


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


def _tokens_do_css(css: str, seletor: str) -> dict[str, str]:
    bloco = css.split(f"{seletor} {{", 1)[1].split("}", 1)[0]
    return dict(re.findall(r"--tf-([\w-]+):\s*(#[0-9a-fA-F]{6})", bloco))


def test_etiquetas_cumprem_os_contrastes() -> None:
    """As cores das etiquetas de status não mudam com a personalização: vivem só no input.css."""
    css = (Path(chamados.web.__file__).parent / "static/css/input.css").read_text()
    claro = _tokens_do_css(css, ":root")
    escuro = {**claro, **_tokens_do_css(css, ".dark")}
    for modo in (claro, escuro):
        for cor in ("blue", "violet", "teal", "green", "gray", "red"):
            assert contrast(modo[f"{cor}-fg"], modo[f"{cor}-bg"]) >= 4.5, cor


def test_series_dos_graficos_no_css_sao_as_da_paleta_original() -> None:
    css = (Path(chamados.web.__file__).parent / "static/css/input.css").read_text()
    for seletor, tokens in (
        (":root", DEFAULT_PALETTE["light"]),
        (".dark", DEFAULT_PALETTE["dark"]),
    ):
        do_css = _tokens_do_css(css, seletor)
        tokens_series = ("chart-2", "chart-3", "chart-4", "chart-before")
        for token in (*tokens_series, *(f"heat-{k}" for k in range(1, 6))):
            assert do_css[token].upper() == tokens[token], (seletor, token)


@pytest.mark.parametrize(
    "paleta",
    [
        DEFAULT_PALETTE,
        *(palette(c) for c in COMBINACOES.values()),
        *(palette(c) for c in PRESETS.values()),
    ],
    ids=["original", *COMBINACOES, *(f"pronta {p}" for p in PRESETS)],
)
def test_series_dos_graficos_se_distinguem_duas_a_duas(paleta: dict[Mode, Tokens]) -> None:
    """As séries 1 (a primary) a 4: marcas com 3:1 sobre os fundos e distintas duas a duas, também
    para quem não enxerga vermelho ou verde."""
    for modo, t in paleta.items():
        series = {"chart-1": t["primary"], **{s: t[s] for s in ("chart-2", "chart-3", "chart-4")}}
        for nome, cor in series.items():
            for fundo in ("surface", "bg"):
                assert contrast(cor, t[fundo]) >= 3, (modo, nome, fundo)
        for (a, x), (b, y) in combinations(series.items(), 2):
            assert distinct(x, y), (modo, a, b)


def test_horas_extras_mudam_de_matiz_quando_a_marca_e_azul() -> None:
    """A 2ª série começa no azul; com a marca azul, vai para o candidato seguinte."""
    azul, verde = palette(PRESETS["azul"]), palette(PRESETS["verde"])
    for modo in ("light", "dark"):
        assert azul[modo]["chart-2"] != verde[modo]["chart-2"]


def test_cor_ja_legivel_fica_como_foi_escolhida() -> None:
    assert palette({**DEFAULT_COLORS, "brand": "#1D4ED8"})["light"]["primary"] == "#1D4ED8"


def test_folha_de_estilo_sobrepoe_os_dois_modos() -> None:
    css = stylesheet(PRESETS["azul"])
    assert css.startswith("html:root{--tf-brand:#2563EB;")
    assert "}@media screen{html.dark{--tf-brand:#2563EB;" in css  # a impressão sai no claro


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
