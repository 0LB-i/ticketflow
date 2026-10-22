"""Paleta da interface a partir das 3 cores escolhidas pelo administrador (docs/17 §17.2).

Marca (laranja), neutra (cinza) e fundo (branco). Os tons são ajustados automaticamente para
manter o contraste mínimo da WCAG 2.1 AA (docs/17 §17.3): 4,5:1 para texto e 3:1 para bordas
de campos e contorno de foco. Sem personalização, vale a paleta original do docs/17.
"""

import math
from functools import lru_cache
from typing import Literal

Colors = dict[str, str]  # brand, neutral, background
Tokens = dict[str, str]
Mode = Literal["light", "dark"]

# Tokens de cor (variáveis --tf-*) que dependem das 3 cores.
TOKENS = (
    "brand",
    "primary",
    "primary-hover",
    "on-primary",
    "primary-subtle",
    "focus",
    "bg",
    "surface",
    "surface-raised",
    "fg",
    "muted",
    "border",
    "border-input",
)

DEFAULT_COLORS: Colors = {"brand": "#F97316", "neutral": "#737373", "background": "#FFFFFF"}

# Combinações prontas da tela de Configurações; a primeira é o padrão. Sem vermelho nem rosa
# na marca: confundiriam com o botão destrutivo (docs/17 §17.2).
PRESETS: dict[str, Colors] = {
    "padrao": DEFAULT_COLORS,
    "azul": {"brand": "#2563EB", "neutral": "#64748B", "background": "#FFFFFF"},
    "verde": {"brand": "#16A34A", "neutral": "#71717A", "background": "#FFFFFF"},
    "petroleo": {"brand": "#0D9488", "neutral": "#64748B", "background": "#FFFFFF"},
    "roxo": {"brand": "#7C3AED", "neutral": "#71717A", "background": "#FFFFFF"},
    "ambar": {"brand": "#D97706", "neutral": "#78716C", "background": "#FFFBF5"},
    "grafite": {"brand": "#374151", "neutral": "#6B7280", "background": "#F9FAFB"},
}

# Paleta original, escolhida à mão (docs/17 §17.2 e static/css/input.css).
DEFAULT_PALETTE: dict[Mode, Tokens] = {
    "light": {
        "brand": "#F97316",
        "primary": "#C2410C",
        "primary-hover": "#9A3412",
        "on-primary": "#FFFFFF",
        "primary-subtle": "#FFF7ED",
        "focus": "#EA580C",
        "bg": "#FAFAFA",
        "surface": "#FFFFFF",
        "surface-raised": "#F5F5F5",
        "fg": "#171717",
        "muted": "#525252",
        "border": "#E5E5E5",
        "border-input": "#737373",
    },
    "dark": {
        "brand": "#F97316",
        "primary": "#FB923C",
        "primary-hover": "#FDBA74",
        "on-primary": "#0A0A0A",
        "primary-subtle": "#262626",
        "focus": "#FB923C",
        "bg": "#0A0A0A",
        "surface": "#171717",
        "surface-raised": "#262626",
        "fg": "#F5F5F5",
        "muted": "#A3A3A3",
        "border": "#262626",
        "border-input": "#737373",
    },
}

# --- conversões: hex ↔ sRGB ↔ OKLCH (espaço perceptual: mexer só na luminosidade L mantém o
# "mesmo" matiz) -----------------------------------------------------------------------------

Rgb = tuple[float, float, float]  # 0–1, sRGB
Oklch = tuple[float, float, float]  # l, c, h


def _hex_to_rgb(hex_color: str) -> Rgb:
    n = int(hex_color[1:], 16)
    return ((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255


def _rgb_to_hex(rgb: Rgb) -> str:
    # floor(x + 0,5) arredonda como o Math.round do JavaScript (o round do Python é bancário).
    return "#" + "".join(f"{math.floor(min(1, max(0, v)) * 255 + 0.5):02X}" for v in rgb)


def _linear(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _gamma(v: float) -> float:
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _rgb_to_oklch(rgb: Rgb) -> Oklch:
    r, g, b = (_linear(v) for v in rgb)
    l_ = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    big_l = 0.2104542553 * l_ + 0.793617785 * m - 0.0040720468 * s
    a = 1.9779984951 * l_ - 2.428592205 * m + 0.4505937099 * s
    bb = 0.0259040371 * l_ + 0.7827717662 * m - 0.808675766 * s
    return big_l, math.hypot(a, bb), math.atan2(bb, a)


def _oklch_to_rgb_raw(color: Oklch) -> Rgb:
    big_l, c, h = color
    a = c * math.cos(h)
    b = c * math.sin(h)
    l_ = (big_l + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (big_l - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (big_l - 0.0894841775 * a - 1.291485548 * b) ** 3
    return (
        _gamma(4.0767416621 * l_ - 3.3077115913 * m + 0.2309699292 * s),
        _gamma(-1.2684380046 * l_ + 2.6097574011 * m - 0.3413193965 * s),
        _gamma(-0.0041960863 * l_ - 0.7034186147 * m + 1.707614701 * s),
    )


def _oklch_to_hex(color: Oklch) -> str:
    """Converte para hex; fora da faixa de cores da tela, reduz a saturação até caber."""

    def fits(rgb: Rgb) -> bool:
        return all(-1e-4 <= v <= 1 + 1e-4 for v in rgb)

    big_l, c, h = color
    rgb = _oklch_to_rgb_raw(color)
    if not fits(rgb):
        lo, hi = 0.0, c
        for _ in range(20):
            mid = (lo + hi) / 2
            if fits(_oklch_to_rgb_raw((big_l, mid, h))):
                lo = mid
            else:
                hi = mid
        rgb = _oklch_to_rgb_raw((big_l, lo, h))
    return _rgb_to_hex(rgb)


# --- contraste (WCAG 2.1) ---------------------------------------------------------------------


def _luminance(hex_color: str) -> float:
    r, g, b = (_linear(v) for v in _hex_to_rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    x, y = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _readable(hex_color: str, backgrounds: list[str], minimum: float) -> str:
    """Escurece (sobre fundos claros) ou clareia (sobre escuros) a cor, mantendo o matiz, até
    ter o contraste mínimo com todos os fundos. Se já tem, fica como está."""

    def ok(h: str) -> bool:
        return all(contrast(h, f) >= minimum for f in backgrounds)

    if ok(hex_color):
        return hex_color
    light = max(_luminance(f) for f in backgrounds) > 0.18
    base_l, c, h = _rgb_to_oklch(_hex_to_rgb(hex_color))
    for step in range(1, 201):
        lum = base_l + (-1 if light else 1) * step * 0.005
        if lum <= 0 or lum >= 1:
            break
        candidate = _oklch_to_hex((lum, c, h))
        if ok(candidate):
            return candidate
    return "#000000" if light else "#FFFFFF"


def _tone(hex_color: str, lum: float, c_max: float) -> str:
    """Mesmo matiz da cor, com a luminosidade e a saturação (limitada) indicadas."""
    _, c, h = _rgb_to_oklch(_hex_to_rgb(hex_color))
    return _oklch_to_hex((lum, min(c, c_max), h))


def _shift(hex_color: str, delta: float) -> str:
    base_l, c, h = _rgb_to_oklch(_hex_to_rgb(hex_color))
    return _oklch_to_hex((min(1, max(0, base_l + delta)), c, h))


DARK_TEXT = "#0A0A0A"
WHITE = "#FFFFFF"


def _derive(colors: Colors, mode: Mode) -> Tokens:
    brand, neutral = colors["brand"], colors["neutral"]
    if mode == "light":
        # O fundo escolhido vale só no modo claro; no escuro, os fundos saem da cor neutra.
        surface = colors["background"]
        direction = -1 if _rgb_to_oklch(_hex_to_rgb(surface))[0] > 0.6 else 1
        bg = _shift(surface, direction * 0.015)
        raised = _shift(surface, direction * 0.035)
        border = _shift(surface, direction * 0.1)
    else:
        bg = _tone(neutral, 0.145, 0.015)
        surface = _tone(neutral, 0.205, 0.015)
        raised = _tone(neutral, 0.269, 0.015)
        border = raised
    light_bgs = _luminance(surface) > 0.18
    backgrounds = [bg, surface, raised]

    fg = _readable(_tone(neutral, 0.205 if light_bgs else 0.97, 0.02), backgrounds, 7)
    muted = _readable(neutral, backgrounds, 4.5)
    border_input = _readable(neutral, [surface, bg], 3)

    subtle = (
        _tone(brand, min(0.975, _rgb_to_oklch(_hex_to_rgb(surface))[0] - 0.02), 0.03)
        if light_bgs
        else _tone(brand, 0.269, 0.02)
    )
    # O texto sobre o botão é branco nos fundos claros e quase preto nos escuros.
    on_primary = WHITE if light_bgs else DARK_TEXT
    # Primária: legível como texto (links, item de menu ativo) e com o texto do botão por cima.
    primary = _readable(brand, [*backgrounds, subtle, on_primary], 4.5)
    hover = _readable(_shift(primary, -0.07 if light_bgs else 0.07), [on_primary], 4.5)
    focus = _readable(brand, [surface, bg], 3)

    return {
        "brand": brand,
        "primary": primary,
        "primary-hover": hover,
        "on-primary": on_primary,
        "primary-subtle": subtle,
        "focus": focus,
        "bg": bg,
        "surface": surface,
        "surface-raised": raised,
        "fg": fg,
        "muted": muted,
        "border": border,
        "border-input": border_input,
    }


def palette(colors: Colors | None) -> dict[Mode, Tokens]:
    if not colors or all(colors[k].upper() == v for k, v in DEFAULT_COLORS.items()):
        return DEFAULT_PALETTE
    return {"light": _derive(colors, "light"), "dark": _derive(colors, "dark")}


def stylesheet(colors: Colors | None) -> str:
    """Folha que sobrepõe os tokens do input.css; vazia com as cores padrão.

    `html:root` e `html.dark` têm especificidade maior que `:root` e `.dark`, então valem em
    qualquer ordem no <head>.
    """
    if not colors:
        return ""
    return _stylesheet(
        colors["brand"].upper(), colors["neutral"].upper(), colors["background"].upper()
    )


@lru_cache(maxsize=8)
def _stylesheet(brand: str, neutral: str, background: str) -> str:
    """Toda tela embute a folha: derivar a paleta (~2 ms) uma vez por combinação de cores."""
    p = palette({"brand": brand, "neutral": neutral, "background": background})
    if p is DEFAULT_PALETTE:
        return ""

    def rules(tokens: Tokens) -> str:
        return ";".join(f"--tf-{t}:{tokens[t]}" for t in TOKENS)

    return f"html:root{{{rules(p['light'])}}}html.dark{{{rules(p['dark'])}}}"
