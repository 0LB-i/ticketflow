# Glossário

Termos do domínio em português e o nome usado no código (ver [ADR 0001](adr/0001-registro-de-decisoes.md)).

| Termo | Código | Definição |
|-------|--------|-----------|
| TicketFlow | `settings.app_name` | Nome do sistema exibido aos usuários. Os identificadores técnicos (pacote `chamados`, serviço `sistema-chamados`) não mudam |
| Chamado | `ticket` | Tarefa registrada e executada por uma equipe |
| Agente | `agent` | Membro de uma equipe; único tipo de usuário que trabalha nos chamados |
| Registrado por | `created_by` | Membro que criou o chamado |
| Responsável | `assignee` | Membro que está executando o chamado |
| Grupo (fila) | `team` | Equipe que registra e executa chamados |
| Supervisor | `team_members.role = 'supervisor'` | Coordenador de um grupo; aprova chamados |
| Setor atendido | `department` | Área da empresa para a qual a tarefa é feita. Só para relatórios: setores não têm login |
| Pessoa atendida | `beneficiary_name` | Nome, em texto livre, de quem pediu ou será atendido. Não tem conta no sistema |
| Papel | `role` | Conjunto de permissões globais: agente, admin ou auditor |
| Categoria | `category` | O que é a tarefa |
| Status (etapa) | `ticket_status` + `kind` | Padrão: Pendente (`open`), Aguardando (`waiting`), Concluído (`closed`), Cancelado (`canceled`) |
| Tipo | `type` | Incidente (`incident`), requisição (`request`) ou tarefa (`task`) |
| Impacto / urgência / prioridade | `impact` / `urgency` / `priority` | Ver [10.3](10-chamados.md#103-prioridade-impacto--urgência) |
| Observador | `watcher` | Colega que acompanha um chamado |
| Comentário | `comment` | Mensagem na linha do tempo, visível a todos que veem o chamado |
| Anexo | `attachment` | Arquivo vinculado a chamado, comentário ou artigo |
| Transferência | `transfer` | Mudança de grupo |
| Aprovação | `approval` | "Ok" do supervisor do grupo antes de começar a tarefa |
| Código de resolução | `resolution_code` | Classificação de como o chamado foi encerrado |
| Base de conhecimento | `kb` | Artigos da equipe com soluções e procedimentos |
| Virada | — | Dia a partir do qual a equipe só trabalha pelo TicketFlow ([16](16-implantacao.md)) |
