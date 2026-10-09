# Glossário

Termos do domínio em português e o nome usado no código (ver [ADR 0001](adr/0001-registro-de-decisoes.md)).

| Termo | Código | Definição |
|-------|--------|-----------|
| Chamado | `ticket` | Registro de um pedido ou problema |
| Solicitante | `requester` | Pessoa que precisa do atendimento |
| Agente | `agent` | Pessoa que atende chamados |
| Responsável | `assignee` | Agente que está com o chamado |
| Setor | `department` | Unidade da empresa onde a pessoa trabalha |
| Gestor de setor | `department_manager` | Gestor que acompanha os chamados do setor e aprova requisições |
| Grupo de atendimento (fila) | `team` | Equipe que atende chamados |
| Supervisor | `team_members.role = 'supervisor'` | Coordenador de um grupo de atendimento |
| Papel | `role` | Conjunto de permissões globais |
| Categoria | `category` | Item do catálogo de serviços |
| Status (etapa) | `ticket_status` + `kind` | Padrão: Pendente (`open`), Aguardando cliente (`waiting`), Entregue (`resolved`), Concluído (`closed`), Cancelado (`canceled`) |
| Cliente (em "Aguardando cliente") | `requester` | O colaborador que abriu o chamado. Não existem clientes externos |
| Tipo | `type` | Incidente (`incident`), requisição (`request`) ou dúvida (`question`) |
| Impacto / urgência / prioridade | `impact` / `urgency` / `priority` | Ver [10.3](10-chamados.md#103-prioridade-impacto--urgência) |
| Observador | `watcher` | Pessoa que acompanha um chamado |
| Comentário público | `comment` (`visibility = 'public'`) | Visível ao solicitante |
| Nota interna | `comment` (`visibility = 'internal'`) | Visível só para agentes |
| Anexo | `attachment` | Arquivo vinculado a chamado, comentário ou artigo |
| Transferência | `transfer` | Mudança de grupo de atendimento |
| Aprovação | `approval` | Autorização exigida antes do atendimento de uma requisição |
| Resposta pronta | `canned_response` | Texto padrão reutilizável (macro) |
| Código de resolução | `resolution_code` | Classificação de como o chamado foi encerrado |
| Base de conhecimento | `kb` | Artigos com soluções e orientações |
