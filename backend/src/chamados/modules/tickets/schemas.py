import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

TicketType = Literal["incident", "request", "task"]
StatusKind = Literal["approval", "open", "waiting", "closed", "canceled"]
TransitionAction = Literal["wait", "resume", "close", "reopen", "cancel"]
TicketView = Literal["unassigned", "mine", "news", "waiting", "watching", "all"]
Body = Annotated[str, Field(min_length=1, max_length=50_000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]


class Ref(BaseModel):
    id: uuid.UUID
    name: str


class UserRef(BaseModel):
    id: uuid.UUID
    full_name: str


class CategoryRef(Ref):
    path: str = Field(description="caminho na árvore, ex.: TI › Acessos › Novo acesso")


class StatusRef(BaseModel):
    id: int
    name: str
    kind: StatusKind


class ResolutionRef(BaseModel):
    id: int
    name: str


class WatcherOut(UserRef):
    kind: Literal["watcher", "mentioned"]


class TicketSummary(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    type: TicketType
    status: StatusRef
    priority: int
    team: Ref
    category: CategoryRef | None
    department: Ref | None
    client: Ref | None
    beneficiary_name: str | None = Field(description="contato: quem pediu (texto livre)")
    assignee: UserRef | None
    started_at: datetime
    created_at: datetime
    updated_at: datetime


class TicketOut(TicketSummary):
    description: str
    impact: int
    urgency: int
    priority_overridden: bool
    created_by: UserRef
    resolution_code: ResolutionRef | None
    reopened_count: int
    closed_at: datetime | None
    watchers: list[WatcherOut]
    allowed_actions: list[str] = Field(
        description="o que o usuário pode fazer no chamado (a interface mostra os botões)"
    )


class TicketListItem(TicketSummary):
    has_news: bool = Field(description="comentário de outra pessoa desde a minha última visita")


class TicketPage(BaseModel):
    items: list[TicketListItem]
    next_cursor: str | None


class TicketCounts(BaseModel):
    """Quantos chamados há em cada fila (as abas da lista)."""

    unassigned: int
    mine: int
    news: int
    waiting: int
    watching: int


class NextIn(BaseModel):
    team_id: uuid.UUID | None = Field(
        default=None, description="sem grupo, a fila de todos os meus grupos"
    )


class TicketCreate(BaseModel):
    title: Title
    description: str = Field(default="", max_length=50_000)
    category_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = Field(
        default=None, description="sem grupo, vai para o grupo padrão da categoria"
    )
    type: TicketType | None = Field(
        default=None, description='sem tipo, usa o da categoria (sem categoria, "incident")'
    )
    department_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None
    beneficiary_name: str | None = Field(
        default=None, max_length=200, description="contato: quem pediu (texto livre)"
    )
    started_at: AwareDatetime | None = Field(
        default=None, description="início do trabalho; sem valor, a hora do registro"
    )
    status_id: int | None = Field(default=None, description="sem valor, Pendente")
    impact: int = Field(default=1, ge=1, le=3)
    urgency: int = Field(default=1, ge=1, le=3)
    assignee: Literal["me"] | uuid.UUID | None = Field(
        default=None, description='"me", outro membro do grupo (supervisor) ou nulo (fila)'
    )
    watcher_ids: list[uuid.UUID] = Field(default=[], max_length=50)
    mention_ids: list[uuid.UUID] = Field(
        default=[], max_length=50, description="@mencionados na descrição: viram observadores"
    )


class TicketUpdate(BaseModel):
    title: Title | None = None
    description: str | None = Field(default=None, max_length=50_000)
    category_id: uuid.UUID | None = Field(default=None, description="nula tira a categoria")
    type: TicketType | None = None
    department_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = Field(default=None, description="nulo tira o cliente")
    beneficiary_name: str | None = Field(
        default=None, max_length=200, description="contato: quem pediu (texto livre)"
    )
    started_at: AwareDatetime | None = None
    status_id: int | None = Field(
        default=None, description="qualquer status, sem as exigências do fluxo (set_status)"
    )
    impact: int | None = Field(default=None, ge=1, le=3)
    urgency: int | None = Field(default=None, ge=1, le=3)
    priority: int | None = Field(
        default=None,
        ge=1,
        le=4,
        description="diferente da matriz exige priority_reason; nula volta ao valor da matriz",
    )
    priority_reason: str | None = Field(default=None, max_length=1000)


class CommentIn(BaseModel):
    body: Body
    mention_ids: list[uuid.UUID] = Field(default=[], max_length=50)


class CommentOut(BaseModel):
    id: uuid.UUID
    author: UserRef
    body: str
    is_solution: bool
    created_at: datetime
    edited_at: datetime | None
    editable_until: datetime = Field(description="o autor pode editar até este momento")


class CommentList(BaseModel):
    items: list[CommentOut]


class AssignIn(BaseModel):
    assignee: Literal["me"] | uuid.UUID | None = Field(
        description='"me" para assumir, um membro do grupo, ou nulo para devolver à fila'
    )


class TransferIn(BaseModel):
    team_id: uuid.UUID
    reason: Body


class TransitionIn(BaseModel):
    action: TransitionAction
    comment: str | None = Field(default=None, max_length=50_000)
    resolution_code_id: int | None = None


class EventOut(BaseModel):
    id: int
    type: str
    actor: UserRef | None
    payload: dict[str, Any]
    created_at: datetime


class EventList(BaseModel):
    items: list[EventOut]
