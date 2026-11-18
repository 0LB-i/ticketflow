"""O que cada token de API pode fazer (docs/05): uma lista de permissões `área.ação`, escolhida por
quem cria o token, e a permissão que cada rota da API pede de um token.

O token nunca faz mais que o dono: a rota confere também a permissão dele (`require(P.X)`, as
regras do chamado, a visibilidade). Uma rota que não está em `ROUTES` recusa qualquer token (o
teste `test_toda_rota_da_api_tem_a_permissao_do_token` obriga a incluir as novas).
"""

# As áreas e as ações de cada uma, na ordem da tela. Grupos e Catálogo não têm "ver": as listas
# deles são de apoio (abaixo).
AREAS: dict[str, tuple[str, ...]] = {
    "tickets": ("view", "create", "edit", "delete"),
    "clients": ("view", "create", "edit"),
    "users": ("view", "create", "edit", "delete"),
    "teams": ("create", "edit", "delete"),
    "catalog": ("create", "edit", "delete"),
    "reports": ("view",),
    "settings": ("view", "edit"),
    "audit": ("view",),
}
ACTIONS = ("view", "create", "edit", "delete")
PERMISSIONS = frozenset(f"{area}.{action}" for area, actions in AREAS.items() for action in actions)

# O acesso dos escopos antigos (`read` e `write`), que a migração 0051 converteu, e o do
# `chamados token create` (com e sem `--read-only`).
READ_ONLY = ("tickets.view", "reports.view")
READ_WRITE = ("tickets.view", "tickets.create", "tickets.edit", "tickets.delete", "reports.view")

ANY = "*"  # Qualquer token: as listas de apoio, que qualquer pessoa logada vê.

# (método, caminho da rota no módulo) → a permissão (uma delas, se for uma tupla), ANY ou None
# (nenhum token: só pela interface).
ROUTES: dict[tuple[str, str], str | tuple[str, ...] | None] = {
    # identity (sair e trocar a senha recusam o token com a mensagem própria: `require_session`)
    ("POST", "/auth/logout"): ANY,
    ("GET", "/me"): ANY,
    ("PATCH", "/me"): None,
    ("POST", "/me/password"): ANY,
    ("GET", "/users"): "users.view",
    ("GET", "/users/{user_id}"): "users.view",
    ("POST", "/users"): "users.create",
    ("PATCH", "/users/{user_id}"): "users.edit",
    ("DELETE", "/users/{user_id}"): "users.delete",
    ("POST", "/users/{user_id}/link"): "users.edit",
    ("GET", "/admin/api-tokens"): None,
    ("POST", "/admin/api-tokens"): None,
    ("PATCH", "/admin/api-tokens/{token_id}"): None,
    ("DELETE", "/admin/api-tokens/{token_id}"): None,
    # organization
    ("GET", "/teams"): ANY,
    ("POST", "/teams"): "teams.create",
    ("PATCH", "/teams/{team_id}"): "teams.edit",
    ("PUT", "/teams/{team_id}/members/{user_id}"): "teams.edit",
    ("DELETE", "/teams/{team_id}/members/{user_id}"): "teams.delete",
    # catalog
    ("GET", "/categories"): ANY,
    ("POST", "/categories"): "catalog.create",
    ("PATCH", "/categories/{category_id}"): "catalog.edit",
    ("GET", "/statuses"): ANY,
    ("POST", "/statuses"): "catalog.create",
    ("PATCH", "/statuses/{status_id}"): "catalog.edit",
    ("PUT", "/statuses/order"): "catalog.edit",
    ("DELETE", "/statuses/{status_id}"): "catalog.delete",
    ("GET", "/resolution-codes"): ANY,
    # clients
    ("GET", "/clients"): "clients.view",
    ("GET", "/clients/options"): ANY,
    ("GET", "/clients/{client_id}"): "clients.view",
    ("POST", "/clients"): "clients.create",
    ("PUT", "/clients/{client_id}"): "clients.edit",
    # tickets
    ("GET", "/tickets"): "tickets.view",
    ("GET", "/tickets/counts"): "tickets.view",
    ("POST", "/tickets/bulk/status"): "tickets.edit",
    ("POST", "/tickets"): "tickets.create",
    ("GET", "/tickets/{ticket_ref}"): "tickets.view",
    ("PATCH", "/tickets/{ticket_ref}"): "tickets.edit",
    ("POST", "/tickets/{ticket_ref}/assign"): "tickets.edit",
    ("PUT", "/tickets/{ticket_ref}/assignees"): "tickets.edit",
    ("POST", "/tickets/{ticket_ref}/transfer"): "tickets.edit",
    ("POST", "/tickets/{ticket_ref}/transitions"): "tickets.edit",
    ("GET", "/tickets/{ticket_ref}/comments"): "tickets.view",
    ("POST", "/tickets/{ticket_ref}/comments"): "tickets.edit",
    ("PATCH", "/tickets/{ticket_ref}/comments/{comment_id}"): "tickets.edit",
    ("DELETE", "/tickets/{ticket_ref}/comments/{comment_id}"): "tickets.delete",
    ("GET", "/tickets/{ticket_ref}/events"): "tickets.view",
    # attachments: o anexo vai num chamado novo ou numa tarefa
    ("POST", "/uploads"): ("tickets.create", "tickets.edit"),
    ("GET", "/attachments/{attachment_id}"): "tickets.view",
    # reports
    ("GET", "/reports/options"): "reports.view",
    ("GET", "/reports"): "reports.view",
    ("GET", "/reports/pdf"): "reports.view",
    ("GET", "/reports/csv"): "reports.view",
    # system
    ("GET", "/work-hours"): ANY,
    ("PATCH", "/admin/settings"): "settings.edit",
    ("PUT", "/admin/settings/logo"): "settings.edit",
    ("DELETE", "/admin/settings/logo"): "settings.edit",
    ("PUT", "/admin/settings/report-logo"): "settings.edit",
    ("DELETE", "/admin/settings/report-logo"): "settings.edit",
    ("GET", "/admin/settings/company"): "settings.view",
    ("PUT", "/admin/settings/company"): "settings.edit",
    ("GET", "/admin/settings/report-filters"): "settings.view",
    ("PUT", "/admin/settings/report-filters"): "settings.edit",
    ("GET", "/admin/settings/ticket-list"): "settings.view",
    ("PUT", "/admin/settings/ticket-list"): "settings.edit",
    ("PUT", "/admin/settings/work-hours"): "settings.edit",
    # audit
    ("GET", "/admin/audit-log"): "audit.view",
}


def allows(permissions: list[str], needed: str | tuple[str, ...] | None) -> bool:
    if needed is None:
        return False
    if needed == ANY:
        return True
    options = (needed,) if isinstance(needed, str) else needed
    return any(p in permissions for p in options)


def route_allows(permissions: list[str], method: str, path: str) -> bool:
    """A rota (método e caminho no módulo) deixa entrar um token com estas permissões?"""
    return allows(permissions, ROUTES.get((method, path)))


def ordered(permissions: list[str] | set[str]) -> list[str]:
    """Só as permissões que existem, na ordem da tela."""
    return [
        f"{area}.{action}"
        for area, actions in AREAS.items()
        for action in actions
        if f"{area}.{action}" in permissions
    ]
