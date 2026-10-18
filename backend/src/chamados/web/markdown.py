"""HTML seguro a partir do Markdown dos chamados e comentários (como o `editor/markdown.ts`)."""

import re
from collections.abc import Sequence
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from markupsafe import Markup

# `html: False`: HTML digitado no texto aparece como texto, nunca vira elemento (sem XSS).
# O markdown-it também recusa links javascript:, vbscript: e data: (exceto imagens).
_md = MarkdownIt("js-default", {"html": False, "linkify": True, "breaks": True})

# Imagens só dos anexos do próprio sistema (prints colados no editor). Uma imagem de fora
# seria carregada por quem abre o chamado (rastreamento): aparece só o endereço, como texto.
ATTACHMENT = re.compile(r"^/api/v1/attachments/[0-9a-f-]{36}$")


def _link_open(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType
) -> str:
    tokens[idx].attrSet("target", "_blank")
    tokens[idx].attrSet("rel", "noopener noreferrer")
    return self.renderToken(tokens, idx, options, env)


def _image(
    self: RendererHTML, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType
) -> str:
    src = str(tokens[idx].attrGet("src") or "")
    if not ATTACHMENT.match(src):
        return escapeHtml(src)
    tokens[idx].attrSet("loading", "lazy")
    image: Any = RendererHTML.image
    href = escapeHtml(src)
    inner = image(self, tokens, idx, options, env)
    return f'<a href="{href}" target="_blank" rel="noopener noreferrer">{inner}</a>'


_md.add_render_rule("link_open", _link_open)
_md.add_render_rule("image", _image)


def render_markdown(text: str) -> Markup:
    return Markup(_md.render(text))  # noqa: S704 (HTML gerado com html: False)
