"""Regras puras dos chamados: o que cada pessoa pode fazer (docs/08 §8.5 e docs/10 §10.5).
Sem banco: os services consultam estas funções antes de agir.
"""

from dataclasses import dataclass

from chamados.core.permissions import Actor, P, can

FINAL_KINDS = frozenset({"closed", "canceled"})


@dataclass(frozen=True)
class Transition:
    from_kinds: frozenset[str]
    to_kind: str
    # Quem pode, além de ser do grupo atual: "member" (qualquer membro), "owner" (responsável
    # ou supervisor) ou "owner_or_creator" (também quem registrou).
    who: str
    comment_required: bool
    resolution_required: bool = False


# Fluxo padrão (docs/10 §10.5). Aprovação entra na Fase 2.
TRANSITIONS: dict[str, Transition] = {
    "wait": Transition(frozenset({"open"}), "waiting", "owner", comment_required=True),
    "resume": Transition(frozenset({"waiting"}), "open", "member", comment_required=False),
    "close": Transition(
        frozenset({"open"}), "closed", "owner", comment_required=True, resolution_required=True
    ),
    "reopen": Transition(frozenset({"closed"}), "open", "member", comment_required=True),
    "cancel": Transition(
        frozenset({"open", "waiting"}), "canceled", "owner_or_creator", comment_required=True
    ),
}


@dataclass(frozen=True)
class TicketState:
    """O que importa de um chamado para decidir as ações. Supõe que o ator já o vê."""

    team_id: int
    kind: str
    created_by_id: int
    assignee_id: int | None
    is_watcher: bool
    co_assignee_ids: frozenset[int] = frozenset()
    # Status de revisão do supervisor ("Em espera de revisão").
    in_review: bool = False


def is_supervisor(actor: Actor, team_id: int) -> bool:
    return actor.role == "admin" or team_id in actor.supervises


def allowed_actions(actor: Actor, t: TicketState) -> set[str]:
    """Ações que o ator pode fazer no chamado. A API devolve a lista para a interface."""
    mine = t.assignee_id == actor.user_id or actor.user_id in t.co_assignee_ids
    # Alterar exige ser do grupo atual (ou admin); observadores de outros grupos só comentam.
    member = t.team_id in actor.teams or actor.role == "admin"
    actions: set[str] = set()
    if can(actor, P.TICKET_COMMENT) and (member or t.is_watcher or mine):
        actions.add("comment")
    if can(actor, P.TICKET_WATCH):
        actions.add("watch_self")
    if not member:
        return actions

    for permission, action in (
        (P.TICKET_EDIT, "edit"),
        (P.TICKET_WATCH, "manage_watchers"),
        # Escolher qualquer status no formulário, sem as exigências do fluxo.
        (P.TICKET_TRANSITION, "set_status"),
    ):
        if can(actor, permission):
            actions.add(action)
    # Escolher um status concluído (Entregue, Concluído): em revisão, só o supervisor ou o admin.
    if "set_status" in actions and (not t.in_review or is_supervisor(actor, t.team_id)):
        actions.add("set_status_closed")
    if t.kind not in FINAL_KINDS:
        if can(actor, P.TICKET_ASSIGN_SELF) and not mine and t.team_id in actor.teams:
            actions.add("assign_self")
        if can(actor, P.TICKET_ASSIGN_OTHERS, t.team_id):
            actions.add("assign_others")
        if t.assignee_id is not None and (mine or can(actor, P.TICKET_ASSIGN_OTHERS, t.team_id)):
            actions.add("unassign")
        if can(actor, P.TICKET_TRANSFER):
            actions.add("transfer")

    if can(actor, P.TICKET_TRANSITION):
        owner = mine or is_supervisor(actor, t.team_id)
        allowed_by = {
            "member": True,
            "owner": owner,
            "owner_or_creator": owner or t.created_by_id == actor.user_id,
        }
        for action, tr in TRANSITIONS.items():
            if t.kind in tr.from_kinds and allowed_by[tr.who]:
                actions.add(action)
    return actions
