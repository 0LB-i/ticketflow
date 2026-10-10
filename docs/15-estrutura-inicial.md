# 15. Estrutura inicial

Dados para a **carga inicial** do piloto (Sprint 5, `F1-S5-09`), feita pelo administrador nas telas de administração. Este documento é um **modelo para preencher**: as linhas marcadas como *exemplo* devem ser substituídas pelos dados reais.

Conceitos usados aqui: [Organização e permissões](08-organizacao-e-permissoes.md). Só os membros das equipes têm conta no TicketFlow.

## 15.1 Perguntas para responder primeiro

| # | Pergunta | Resposta |
|---|----------|----------|
| 1 | Quem é a equipe de TI que vai usar o sistema no piloto? | |
| 2 | Quem será o **administrador** do sistema? | |
| 3 | Quem é o **supervisor** da TI (aprova e distribui)? | |
| 4 | A TI se divide em mais de um grupo (ex.: Suporte e Infraestrutura) ou é um grupo só? | |
| 5 | Algum tipo de tarefa precisa de **aprovação** do supervisor? (ex.: compra de equipamento) | |
| 6 | Qual **endereço de e-mail** envia as notificações (ex.: `ticketflow@example.com`) e qual o provedor desse e-mail? | |
| 7 | Qual a **data da virada** ([16](16-implantacao.md))? | |

## 15.2 Grupos

Quem **executa** chamados. Para a TI de uma empresa de até 50 pessoas, um grupo costuma bastar.

| Grupo | Supervisor(es) | Membros |
|-------|----------------|---------|
| *TI – Suporte (exemplo)* | *Ana* | *Ana, Bruno* |

## 15.3 Usuários

Todos recebem um **convite por e-mail** para criar a senha ([9.4](09-login-e-autenticacao.md#94-convite-esqueci-a-senha-e-troca-de-senha)).

| Nome | E-mail | Papel | Grupos |
|------|--------|-------|--------|
| *Ana Souza (exemplo)* | *ana@example.com* | Agente | *TI – Suporte (supervisora)* |
| *Bruno Lima (exemplo)* | *bruno@example.com* | Agente | *TI – Suporte* |
| *Admin (exemplo)* | *admin@example.com* | Administrador | — |

- **Papel:** Agente, Administrador ou Auditor. Supervisor não é papel: é marcado no grupo.
- O administrador pode ser uma das pessoas da TI. Nesse caso ela tem papel Administrador e também é membro do grupo.

## 15.4 Setores atendidos

Para quais áreas a TI trabalha. Usados só no campo "Para quem" do chamado e nos relatórios. Podem ter subsetores.

| Setor | Setor acima |
|-------|-------------|
| *Diretoria (exemplo)* | — |
| *Administrativo (exemplo)* | — |
| *Financeiro (exemplo)* | Administrativo |
| *Comercial (exemplo)* | — |
| *RH (exemplo)* | Administrativo |
| *TI (exemplo, para tarefas internas da própria TI)* | — |

## 15.5 Categorias (proposta inicial para a TI)

Proposta genérica para começar o piloto. Ajustar aos sistemas e equipamentos da empresa.

| Categoria | Tipo padrão | Aprovação? | Grupo |
|-----------|-------------|------------|-------|
| TI › Acessos › Redefinir senha | Requisição | Não | TI – Suporte |
| TI › Acessos › Novo acesso a sistema ou pasta | Requisição | Não | TI – Suporte |
| TI › Acessos › Desligamento de colaborador (remover acessos) | Requisição | Não | TI – Suporte |
| TI › Equipamentos › Computador ou notebook com problema | Incidente | Não | TI – Suporte |
| TI › Equipamentos › Compra de equipamento ou periférico | Requisição | Supervisor | TI – Suporte |
| TI › Equipamentos › Preparar equipamento para novo colaborador | Tarefa | Não | TI – Suporte |
| TI › Impressão › Impressora com problema | Incidente | Não | TI – Suporte |
| TI › Rede › Internet, Wi-Fi ou VPN | Incidente | Não | TI – Suporte |
| TI › E-mail › Problema no e-mail | Incidente | Não | TI – Suporte |
| TI › Sistemas › *[um item por sistema usado na empresa]* | Incidente | Não | TI – Suporte |
| TI › Infraestrutura › Manutenção e rotinas (backup, atualizações, certificados) | Tarefa | Não | TI – Suporte |
| TI › Melhorias e projetos | Tarefa | Não | TI – Suporte |

As aprovações só passam a funcionar na Fase 2. Até lá, as categorias marcadas com aprovação funcionam sem ela.
