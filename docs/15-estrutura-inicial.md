# 15. Estrutura inicial

Dados para a **carga inicial** do piloto (Sprint 5, `F1-S5-09`). Este documento é um **modelo para preencher**: as linhas marcadas como *exemplo* devem ser substituídas pelos dados reais.

Conceitos usados aqui: [Organização e permissões](08-organizacao-e-permissoes.md).

## 15.1 Perguntas para responder primeiro

| # | Pergunta | Resposta |
|---|----------|----------|
| 1 | Quais áreas vão **atender** chamados no piloto? (só TI, ou também RH, Financeiro…) | |
| 2 | Quem será o **administrador** do sistema? | |
| 3 | Quem são os **agentes** de cada área que atende? | |
| 4 | Algum tipo de pedido precisa de **aprovação** do gestor? (ex.: acesso a sistemas, compra de equipamento) | |
| 5 | Existe algum assunto **confidencial** (ex.: RH › folha, denúncias)? | |
| 6 | Qual **endereço de e-mail** envia as notificações (ex.: `chamados@example.com`) e qual o provedor desse e-mail? | |

## 15.2 Setores

Onde cada pessoa **trabalha**. Pode ter subsetores.

| Setor | Setor acima | Gestor(es) |
|-------|-------------|------------|
| *Diretoria (exemplo)* | — | *Fulano* |
| *Administrativo (exemplo)* | — | *Beltrana* |
| *Financeiro (exemplo)* | Administrativo | *Beltrana* |
| *Comercial (exemplo)* | — | *Ciclano* |
| *TI (exemplo)* | Administrativo | *Ana* |

## 15.3 Grupos de atendimento

Quem **atende** chamados. Com até 50 pessoas, um ou dois grupos por área costumam bastar.

| Grupo | Supervisor | Membros (agentes) |
|-------|------------|-------------------|
| *TI – Suporte (exemplo)* | *Ana* | *Ana, Bruno* |

## 15.4 Categorias (proposta inicial para a TI)

Proposta genérica para começar o piloto. Ajustar aos sistemas e equipamentos da empresa.

| Categoria | Tipo padrão | Aprovação? | Grupo |
|-----------|-------------|------------|-------|
| TI › Acessos › Redefinir senha | Requisição | Não | TI – Suporte |
| TI › Acessos › Novo acesso a sistema ou pasta | Requisição | Gestor do setor | TI – Suporte |
| TI › Acessos › Desligamento de colaborador (remover acessos) | Requisição | Não | TI – Suporte |
| TI › Equipamentos › Computador ou notebook com problema | Incidente | Não | TI – Suporte |
| TI › Equipamentos › Solicitar equipamento ou periférico | Requisição | Gestor do setor | TI – Suporte |
| TI › Impressão › Impressora com problema | Incidente | Não | TI – Suporte |
| TI › Rede › Internet, Wi-Fi ou VPN | Incidente | Não | TI – Suporte |
| TI › E-mail › Problema no e-mail | Incidente | Não | TI – Suporte |
| TI › Sistemas › *[um item por sistema usado na empresa]* | Incidente | Não | TI – Suporte |
| TI › Dúvida ou orientação | Dúvida | Não | TI – Suporte |

As aprovações só passam a funcionar na Fase 2. Até lá, as categorias marcadas com aprovação funcionam sem ela.

## 15.5 Usuários (importação por CSV)

Formato do arquivo aceito em **Administração › Usuários › Importar**:

```csv
nome,email,setor,papel,grupos
Ana Souza,ana@example.com,TI,agent,TI – Suporte:supervisor
Bruno Lima,bruno@example.com,TI,agent,TI – Suporte
Carla Dias,carla@example.com,Financeiro,requester,
Admin Sistema,admin@example.com,TI,admin,
```

- **papel:** `requester` (solicitante), `agent` (agente), `admin` ou `auditor`.
- **grupos:** nomes separados por `;`. Acrescente `:supervisor` para quem coordena o grupo.
- O **setor** precisa existir antes da importação (ou ser criado na mesma tela).
- Cada pessoa importada recebe um **convite por e-mail** para criar a senha ([9.4](09-login-e-autenticacao.md#94-convite-esqueci-a-senha-e-troca-de-senha)).
- Gestores de setor são definidos na tela de setores, não no CSV.
