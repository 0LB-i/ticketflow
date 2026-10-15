import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

TicketType = Literal["incident", "request", "task"]
StatusKind = Literal["approval", "open", "waiting", "delivered", "closed", "canceled"]
TransitionAction = Literal["wait", "resume", "close", "reopen", "cancel"]
TicketView = Literal["mine", "news", "waiting", "watching", "all"]
Body = Annotated[str, Field(min_length=1, max_length=50_000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=300)]
# Até 1000 horas num andamento: mais que isso é erro de digitação.
TimeSpent = Annotated[int | None, Field(ge=1, le=60_000, description="tempo gasto, em minutos")]


class Ref(BaseModel):
    id: uuid.UUID
    name: str


class UserRef(BaseModel):
    id: uuid.UUID
    display_name: str


class CategoryRef(Ref):
    path: str = Field(description="caminho na árvore, ex.: TI › Acessos › Novo acesso")


class StatusRef(BaseModel):
    id: int
    name: str
    kind: StatusKind


class ResolutionRef(BaseModel):
    id: int
    name: str


class AttachmentOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    comment_id: uuid.UUID | None = Field(description="nulo: anexo do registro (descrição)")
    uploaded_by: UserRef
    created_at: datetime


class WatcherOut(UserRef):
    kind: Literal["watcher", "mentioned"]


class TicketSummary(BaseModel):
    id: uuid.UUID
    number: int
    title: str
    type: TicketType
    status: StatusRef
    team: Ref
    category: CategoryRef | None
    department: Ref | None
    client: Ref | None
    beneficiary_name: str | None = Field(description="contato: quem pediu (texto livre)")
    assignee: UserRef
    started_at: datetime
    created_at: datetime
    updated_at: datetime


class PersonTime(UserRef):
    minutes: int


class TicketOut(TicketSummary):
    description: str
    created_by: UserRef
    resolution_code: ResolutionRef | None
    reopened_count: int
    closed_at: datetime | None
    co_assignees: list[UserRef] = Field(description="outros responsáveis, além do assignee")
    watchers: list[WatcherOut]
    attachments: list[AttachmentOut] = Field(description="do registro e de todos os comentários")
    time_spent_minutes: int = Field(description="soma do tempo gasto nos comentários")
    time_by_person: list[PersonTime] = Field(description="a mesma soma, por autor (maior primeiro)")
    allowed_actions: list[str] = Field(
        description="o que o usuário pode fazer no chamado (a interface mostra os botões)"
    )


class TicketListItem(TicketSummary):
    has_news: bool = Field(description="comentário de outra pessoa desde a minha última visita")
    time_spent_minutes: int = Field(description="soma do tempo gasto nas tarefas")


class TicketPage(BaseModel):
    items: list[TicketListItem]
    next_cursor: str | None


class TicketCounts(BaseModel):
    """Quantos chamados há em cada fila (as abas da lista)."""

    mine: int
    news: int
    waiting: int
    watching: int


class BulkStatusIn(BaseModel):
    numbers: list[int] = Field(min_length=1, max_length=200, description="números dos chamados")
    status_id: int


class BulkFailure(BaseModel):
    number: int
    detail: str


class BulkResult(BaseModel):
    updated: list[int]
    failed: list[BulkFailure] = Field(description="os que não mudaram, com o motivo")


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
    client_id: uuid.UUID = Field(description="cliente ativo")
    beneficiary_name: str | None = Field(
        default=None, max_length=200, description="contato: quem pediu (texto livre)"
    )
    started_at: AwareDatetime | None = Field(
        default=None, description="início do trabalho; sem valor, a hora do registro"
    )
    status_id: int | None = Field(default=None, description="sem valor, Pendente")
    assignee: Literal["me"] | uuid.UUID = Field(description='"me" ou outro membro do grupo')
    co_assignee_ids: list[uuid.UUID] = Field(
        default=[],
        max_length=200,
        description="outros responsáveis, membros ativos do grupo; exige o assignee",
    )
    watcher_ids: list[uuid.UUID] = Field(default=[], max_length=50)
    mention_ids: list[uuid.UUID] = Field(
        default=[], max_length=50, description="@mencionados na descrição: viram observadores"
    )
    attachment_ids: list[uuid.UUID] = Field(
        default=[], max_length=10, description="envios (POST /uploads) a vincular"
    )


class TicketUpdate(BaseModel):
    title: Title | None = None
    description: str | None = Field(default=None, max_length=50_000)
    category_id: uuid.UUID | None = Field(default=None, description="nula tira a categoria")
    type: TicketType | None = None
    department_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = Field(default=None, description="outro cliente ativo")
    beneficiary_name: str | None = Field(
        default=None, max_length=200, description="contato: quem pediu (texto livre)"
    )
    started_at: AwareDatetime | None = None
    status_id: int | None = Field(
        default=None, description="qualquer status, sem as exigências do fluxo (set_status)"
    )
    attachment_ids: list[uuid.UUID] | None = Field(
        default=None, max_length=10, description="imagens coladas na descrição (POST /uploads)"
    )


class CommentIn(BaseModel):
    body: Body
    time_spent_minutes: TimeSpent = None
    done_at: AwareDatetime | None = Field(
        default=None, description="quando a tarefa foi feita; sem valor, agora (na edição, mantém)"
    )
    mention_ids: list[uuid.UUID] = Field(default=[], max_length=50)
    attachment_ids: list[uuid.UUID] = Field(
        default=[], max_length=10, description="envios (POST /uploads) a vincular"
    )


class CommentOut(BaseModel):
    id: uuid.UUID
    author: UserRef
    body: str
    is_solution: bool
    time_spent_minutes: int | None
    done_at: datetime = Field(description="quando a tarefa foi feita (o autor pode mudar)")
    created_at: datetime
    edited_at: datetime | None


class CommentList(BaseModel):
    items: list[CommentOut]


class AssignIn(BaseModel):
    assignee: Literal["me"] | uuid.UUID = Field(
        description='"me" para assumir ou um membro do grupo'
    )


class TransferIn(BaseModel):
    team_id: uuid.UUID
    assignee_id: uuid.UUID = Field(description="novo responsável: membro ativo do grupo de destino")
    reason: Body


class TransitionIn(BaseModel):
    action: TransitionAction
    comment: str | None = Field(default=None, max_length=50_000)
    time_spent_minutes: TimeSpent = None
    resolution_code_id: int | None = None
    attachment_ids: list[uuid.UUID] = Field(
        default=[], max_length=10, description="envios (POST /uploads) a vincular"
    )


class EventOut(BaseModel):
    id: int
    type: str
    actor: UserRef | None
    payload: dict[str, Any]
    created_at: datetime


class EventList(BaseModel):
    items: list[EventOut]
