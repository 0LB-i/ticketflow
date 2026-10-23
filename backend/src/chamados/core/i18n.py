"""Idiomas da API (português e inglês).

As mensagens são escritas em português no código; o tratamento de erros (core/errors.py)
traduz o `detail` pelo catálogo abaixo quando a requisição pede inglês. A interface envia o
idioma escolhido no header Accept-Language. Um teste confere que toda mensagem de erro da API
tem tradução.
"""

from typing import Literal

from fastapi import Request

Locale = Literal["pt-BR", "en"]
LOCALES: tuple[Locale, ...] = ("pt-BR", "en")
DEFAULT_LOCALE: Locale = "pt-BR"


def request_locale(request: Request) -> Locale:
    """Primeiro idioma do Accept-Language que o sistema conhece; senão, português."""
    for part in request.headers.get("accept-language", "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag.startswith("en"):
            return "en"
        if tag.startswith("pt"):
            return "pt-BR"
    return DEFAULT_LOCALE


def translate(text: str, locale: str) -> str:
    return EN.get(text, text) if locale == "en" else text


EN: dict[str, str] = {
    # Títulos dos erros (RFC 9457)
    "Requisição inválida": "Bad request",
    "Não autenticado": "Unauthenticated",
    "Acesso negado": "Forbidden",
    "Não encontrado": "Not found",
    "Método não permitido": "Method not allowed",
    "Conflito": "Conflict",
    "Pré-condição falhou": "Precondition failed",
    "Dados inválidos": "Invalid data",
    "Muitas requisições": "Too many requests",
    "Erro interno": "Internal error",
    "Serviço indisponível": "Service unavailable",
    "Erro": "Error",
    "Banco de dados indisponível": "Database unavailable",
    # Login, sessão e senha
    "E-mail ou senha inválidos.": "Invalid email or password.",
    "Muitas tentativas. Tente de novo mais tarde.": "Too many attempts. Try again later.",
    "Sessão expirada ou inexistente. Entre novamente.": "Session expired. Please sign in again.",
    "Token CSRF ausente ou inválido.": "Missing or invalid CSRF token.",
    "Token de API inválido, expirado ou revogado.": "Invalid, expired or revoked API token.",
    "Este token de API só permite leitura.": "This API token is read-only.",
    "Tokens de API não acessam a administração.": "API tokens cannot access administration.",
    "Esta ação só pode ser feita pela interface.": "This action is only available in the app.",
    "Idempotency-Key: de 1 a 255 caracteres.": "Idempotency-Key: 1 to 255 characters.",
    "Uma requisição com esta Idempotency-Key ainda está em andamento.": (
        "A request with this Idempotency-Key is still in progress."
    ),
    "Esta Idempotency-Key já foi usada com outra requisição.": (
        "This Idempotency-Key was already used with a different request."
    ),
    "Troque a senha provisória antes de continuar.": (
        "Change the temporary password before continuing."
    ),
    "Link inválido ou expirado.": "Invalid or expired link.",
    "A senha atual não confere.": "The current password is incorrect.",
    "A senha nova precisa ser diferente da atual.": (
        "The new password must be different from the current one."
    ),
    "A senha precisa ter pelo menos 8 caracteres.": "The password must have at least 8 characters.",
    "A senha pode ter no máximo 256 caracteres.": "The password can have at most 256 characters.",
    "Essa senha é muito comum ou fácil de adivinhar. Escolha outra.": (
        "This password is too common or easy to guess. Choose another one."
    ),
    # Usuários, grupos e setores
    "Usuário não encontrado.": "User not found.",
    "Você não pode excluir o próprio usuário.": "You cannot delete your own user.",
    "Já existe um usuário com este e-mail.": "A user with this email already exists.",
    "Já existe um usuário com este nome de usuário.": "A user with this username already exists.",
    "O usuário precisa ter de 2 a 50 caracteres: letras sem acento, números, ponto, hífen ou "
    "sublinhado.": "The username needs 2 to 50 characters: unaccented letters, digits, dot, "
    "hyphen or underscore.",
    "Papel inválido.": "Invalid role.",
    "O sistema precisa de pelo menos um administrador ativo.": (
        "The system needs at least one active administrator."
    ),
    "Usuário inativo. Reative antes de enviar o link.": (
        "Inactive user. Reactivate before sending the link."
    ),
    "Cadastre um e-mail para este usuário antes de enviar o link.": (
        "Add an email address for this user before sending the link."
    ),
    "Grupo não encontrado.": "Team not found.",
    "Já existe um grupo com este nome.": "A team with this name already exists.",
    "Este usuário não é membro do grupo.": "This user is not a member of the team.",
    "Setor não encontrado.": "Department not found.",
    "Já existe um setor com este nome no mesmo nível.": (
        "A department with this name already exists at this level."
    ),
    "Já existe um setor com este código.": "A department with this code already exists.",
    "Um setor não pode ficar abaixo dele mesmo.": "A department cannot be placed under itself.",
    # Categorias
    "Categoria não encontrada.": "Category not found.",
    "Grupo padrão não encontrado.": "Default team not found.",
    "Já existe uma categoria com este nome no mesmo nível.": (
        "A category with this name already exists at this level."
    ),
    "As categorias têm no máximo 3 níveis.": "Categories can have at most 3 levels.",
    "Uma categoria não pode ficar abaixo dela mesma.": "A category cannot be placed under itself.",
    # Chamados
    "Você não tem permissão para esta ação.": "You are not allowed to do this.",
    "Você não tem acesso a este chamado.": "You don't have access to this ticket.",
    "Chamado não encontrado.": "Ticket not found.",
    "Cursor inválido.": "Invalid cursor.",
    'Responsável: use "me" ou o id.': 'Assignee: use "me" or the id.',
    "Categoria não encontrada ou inativa.": "Category not found or inactive.",
    "Grupo não encontrado ou inativo.": "Team not found or inactive.",
    "Setor não encontrado ou inativo.": "Department not found or inactive.",
    "Cliente não encontrado ou inativo.": "Client not found or inactive.",
    "O chamado precisa de um cliente.": "The ticket needs a client.",
    # Anexos
    "Tipo de arquivo não permitido.": "File type not allowed.",
    "O arquivo está vazio.": "The file is empty.",
    "O arquivo passa do limite de 25 MB.": "The file exceeds the 25 MB limit.",
    "O conteúdo do arquivo não corresponde à extensão.": (
        "The file content does not match its extension."
    ),
    "Anexo não encontrado.": "Attachment not found.",
    "Anexo não encontrado ou já usado.": "Attachment not found or already used.",
    "Os anexos deste chamado passariam do limite de 200 MB.": (
        "This ticket's attachments would exceed the 200 MB limit."
    ),
    "O responsável precisa ser um membro ativo do grupo.": (
        "The assignee must be an active member of the team."
    ),
    "Observador ou mencionado não encontrado ou inativo.": (
        "Watcher or mentioned user not found or inactive."
    ),
    "Escolha o grupo: a categoria não tem um grupo padrão ativo.": (
        "Choose the team: the category has no active default team."
    ),
    "Escolha o grupo do chamado.": "Choose the ticket's team.",
    "Status não encontrado.": "Status not found.",
    "Informe a cidade.": "Enter the city.",
    "Informe o nome completo.": "Enter the full name.",
    "Informe a razão social.": "Enter the legal name.",
    "Informe o nome fantasia.": "Enter the trade name.",
    "Informe o CPF.": "Enter the CPF.",
    "Informe o CNPJ.": "Enter the CNPJ.",
    "CPF inválido.": "Invalid CPF.",
    "CNPJ inválido.": "Invalid CNPJ.",
    "Já existe um cliente com este CPF/CNPJ.": "A client with this CPF/CNPJ already exists.",
    "Já existe um cliente com este nome.": "A client with this name already exists.",
    "A data de nascimento não pode ficar no futuro.": "The date of birth cannot be in the future.",
    "Telefone inválido: informe o DDD e o número.": (
        "Invalid phone: enter the area code and the number."
    ),
    "RG inválido: só números, até 14.": "Invalid ID (RG): digits only, up to 14.",
    "CEP inválido: são 8 números.": "Invalid postal code (CEP): it has 8 digits.",
    "UF inválida.": "Invalid state.",
    "Cliente não encontrado.": "Client not found.",
    "O fim do expediente precisa ser depois do início.": "Working hours must end after they start.",
    "O período precisa terminar depois de começar.": "The period must end after it starts.",
    "Data inválida.": "Invalid date.",
    "O período pode ter no máximo 366 dias.": "The period can have at most 366 days.",
    "Você só pode ver os seus próprios números.": "You can only see your own numbers.",
    "Informe o nome do status.": "Enter the status name.",
    "Já existe um status com este nome.": "A status with this name already exists.",
    "Envie todos os status, cada um uma vez.": "Send every status, each one once.",
    "Este é o único status com este comportamento. Crie outro antes de remover.": (
        "This is the only status with this behavior. Create another one before removing it."
    ),
    "O início não pode ficar no futuro.": "The start cannot be in the future.",
    "Você só registra chamados nos grupos de que é membro.": (
        "You can only create tickets in teams you are a member of."
    ),
    "Escreva o comentário.": "Write the comment.",
    "Comentário não encontrado.": "Comment not found.",
    "A data da tarefa não pode ficar no futuro.": "The task date cannot be in the future.",
    "Só o autor altera a tarefa.": "Only the author can change the task.",
    "O chamado já está neste grupo.": "The ticket is already in this team.",
    "O chamado foi alterado por outra pessoa. Recarregue e tente de novo.": (
        "The ticket was changed by someone else. Reload and try again."
    ),
    "Informe o motivo da transferência.": "Give a reason for the transfer.",
    "Escreva o comentário: ele é obrigatório nesta mudança.": (
        "Write the comment: it is required for this change."
    ),
    "Escreva o comentário do tempo gasto.": "Write a comment for the time spent.",
    "Escolha o código de resolução.": "Choose the resolution code.",
    "Este usuário não acompanha o chamado.": "This user is not watching the ticket.",
    # Configurações
    "Logotipo inválido: envie uma imagem PNG, JPEG ou WebP.": (
        "Invalid logo: upload a PNG, JPEG or WebP image."
    ),
    "O logotipo pode ter no máximo 256 KB.": "The logo can be at most 256 KB.",
    "Nenhum logotipo cadastrado.": "No logo uploaded.",
}
