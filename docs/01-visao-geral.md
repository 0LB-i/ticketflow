# 1. Visão geral

## Problema

Em muitas empresas, as solicitações internas (TI, RH, facilities, financeiro, jurídico) chegam por e-mail, chat e corredor. O resultado:

- pedidos se perdem ou ficam sem dono;
- não há medição de desempenho;
- o conhecimento para resolver problemas recorrentes fica na cabeça das pessoas;
- não há dados para priorizar melhorias.

## Objetivo

Construir um sistema de chamados interno que:

1. centralize as solicitações em **filas por equipe**, cada chamado com responsável e prioridade;
2. dê ao solicitante **transparência** sobre o andamento;
3. gere indicadores de atendimento (volume, tempos, satisfação);
4. seja **API-first**, preparado para integrar depois com outros sistemas e com **IAs**, tanto consumindo serviços de IA (triagem, resumo, sugestão de resposta) quanto sendo operado por agentes de IA. Essas integrações ficam para depois da versão 1.0;
5. rode sobre **Python + PostgreSQL**, com operação simples (poucos componentes de infraestrutura).

## Público

> Primeira instalação: **Martiniti**. Quem abre e quem atende os chamados são colaboradores da própria empresa; não há fornecedores nem clientes externos no fluxo.

| Perfil | O que faz |
|--------|-----------|
| **Solicitante** | Qualquer colaborador. Abre e acompanha os próprios chamados, responde e avalia o atendimento. |
| **Agente** | Membro de uma equipe de atendimento. Trabalha os chamados das filas dele. |
| **Supervisor** | Gerencia uma ou mais equipes: redistribui chamados, acompanha relatórios. |
| **Administrador** | Configura o sistema: usuários, equipes, categorias, status e e-mail. |

## Escopo

### Dentro do escopo (versão 1.0)

- Abertura de chamados (portal, e-mail, telefone e presencial)
- Filas, atribuição, status, prioridades e categorias
- Comentários públicos e notas internas, anexos
- Notificações por e-mail e no sistema
- Busca textual em português
- Base de conhecimento
- Relatórios operacionais
- Aprovações e pesquisa de satisfação

### Depois da versão 1.0

Retirados na revisão de escopo de 2026-10-09; o plano está no [backlog do roadmap](07-roadmap.md#backlog-futuro-fora-da-v10):

- Integração com IA: classificação, resumo, sugestão de resposta, busca semântica ([plano](06-integracao-ia.md))
- Tokens de API para integrações, webhooks de saída e servidor MCP
- Papéis personalizados, visões salvas, atalhos de teclado, antivírus nos anexos e campos extras por categoria

### Fora do escopo (por enquanto)

- Atendimento a clientes externos (é um help desk **interno**)
- Gestão de ativos / CMDB completa
- Gestão de mudanças e problemas no padrão ITIL completo
- Aplicativo mobile nativo (a interface web deve ser responsiva)
- Telefonia / URA
- SLA (metas de prazo, alertas de vencimento, calendário de expediente): o atendimento é todo interno

## Métricas de sucesso

- 100% das solicitações das equipes piloto passando pelo sistema em até 60 dias após a implantação
- Tempos de atendimento medidos por grupo desde o piloto
- Redução do tempo médio de triagem (meta a definir após a medição de base)
