"""Textos dos e-mails dos chamados (docs/10 §10.10), por idioma de quem recebe. Texto simples, como
os de convite e redefinição (identity/service.EMAILS). O título do chamado e o comentário vão como
foram escritos."""

TEXTS: dict[str, dict[str, tuple[str, ...]]] = {
    "pt-BR": {
        # motivo: (fim do assunto, primeira linha)
        "assigned": ("atribuído a você", "{quem} atribuiu a você o chamado #{numero}."),
        "new_in_team": (
            "novo chamado no grupo {grupo}",
            "{quem} registrou o chamado #{numero} no grupo {grupo}.",
        ),
        "transferred": (
            "transferido para o grupo {grupo}",
            "{quem} transferiu o chamado #{numero} para o grupo {grupo}.",
        ),
        "comment": ("comentário novo", "{quem} comentou o chamado #{numero}."),
        "mentioned": ("você foi mencionado", "{quem} mencionou você no chamado #{numero}."),
        "closed": ("concluído", "{quem} concluiu o chamado #{numero}."),
        "reopened": ("reaberto", "{quem} reabriu o chamado #{numero}."),
        # (assunto, corpo, bloco do comentário)
        "email": (
            "[#{numero}] {titulo}: {motivo}",
            "Olá, {nome}.\n\n{linha}\n\nChamado #{numero}: {titulo}\n{comentario}\n"
            "Abrir o chamado: {url}\n",
            "\nComentário:\n{texto}\n",
        ),
    },
    "en": {
        "assigned": ("assigned to you", "{quem} assigned ticket #{numero} to you."),
        "new_in_team": (
            "new ticket in group {grupo}",
            "{quem} created ticket #{numero} in group {grupo}.",
        ),
        "transferred": (
            "transferred to group {grupo}",
            "{quem} transferred ticket #{numero} to group {grupo}.",
        ),
        "comment": ("new comment", "{quem} commented on ticket #{numero}."),
        "mentioned": ("you were mentioned", "{quem} mentioned you in ticket #{numero}."),
        "closed": ("closed", "{quem} closed ticket #{numero}."),
        "reopened": ("reopened", "{quem} reopened ticket #{numero}."),
        "email": (
            "[#{numero}] {titulo}: {motivo}",
            "Hello, {nome}.\n\n{linha}\n\nTicket #{numero}: {titulo}\n{comentario}\n"
            "Open the ticket: {url}\n",
            "\nComment:\n{texto}\n",
        ),
    },
}


def render(
    locale: str,
    reason: str,
    *,
    nome: str,
    quem: str,
    numero: int,
    titulo: str,
    grupo: str,
    url: str,
    comentario: str | None,
) -> tuple[str, str]:
    """Assunto e corpo do e-mail."""
    texts = TEXTS.get(locale, TEXTS["pt-BR"])
    motivo, linha = (t.format(quem=quem, numero=numero, grupo=grupo) for t in texts[reason])
    assunto, corpo, bloco = texts["email"]
    return assunto.format(numero=numero, titulo=titulo, motivo=motivo), corpo.format(
        nome=nome,
        linha=linha,
        numero=numero,
        titulo=titulo,
        comentario=bloco.format(texto=comentario) if comentario else "",
        url=url,
    )
