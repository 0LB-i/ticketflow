# 1. Visão geral

**TicketFlow** é o sistema de chamados interno da empresa ([identidade visual](17-identidade-visual.md)).

## Problema

As equipes internas (começando pela TI) recebem pedidos e acumulam tarefas próprias por e-mail, chat, telefone e corredor, e controlam tudo de cabeça, em anotações ou em planilhas. O resultado:

- tarefas se perdem ou ficam sem dono;
- ninguém sabe ao certo o que está em andamento nem com quem;
- não há medição de volume e de tempos;
- o conhecimento para resolver problemas recorrentes fica na cabeça das pessoas;
- não há dados para priorizar melhorias nem para mostrar quanto trabalho vai para cada área.

## Objetivo

Construir uma ferramenta de trabalho para as equipes que:

1. centralize as tarefas em **filas por equipe**, cada chamado com responsável e histórico;
2. dê à equipe e ao supervisor **visibilidade** do que está em aberto, parado ou concluído;
3. gere indicadores (volume, tempos, demanda por setor atendido);
4. seja **API-first**, preparado para integrar depois com outros sistemas e com **IAs**, tanto consumindo serviços de IA (triagem, resumo, sugestão de resposta) quanto sendo operado por agentes de IA. Essas integrações ficam para depois da versão 1.0;
5. rode sobre **Python + PostgreSQL**, com operação simples (poucos componentes de infraestrutura).

## Público

> Primeira instalação: **empresa**. Só os **membros das equipes** usam o sistema: eles mesmos registram os chamados, distribuem e executam. Os demais colaboradores não têm conta; quando uma tarefa é para alguém de fora da equipe, o chamado registra o setor e o nome da pessoa atendida (decisão de 2026-10-10, [08](08-organizacao-e-permissoes.md)).

| Perfil | O que faz |
|--------|-----------|
| **Agente** | Membro de uma equipe. Registra, assume, executa e acompanha chamados. |
| **Supervisor** | Coordena um grupo: distribui chamados, aprova os que exigem aprovação, acompanha relatórios. |
| **Administrador** | Configura o sistema: usuários, grupos, setores atendidos, categorias, status e e-mail. |
| **Auditor** | Consulta tudo, sem alterar. |

## Escopo

### Dentro do escopo (versão 1.0)

- Registro de chamados pela própria equipe, com setor e pessoa atendidos
- Filas, atribuição, transferência, status e categorias
- Comentários com @menções, observadores e anexos
- Aprovação do supervisor para categorias selecionadas
- Notificações por e-mail e no sistema
- Busca textual em português
- Base de conhecimento da equipe
- Relatórios operacionais

### Depois da versão 1.0

Retirados nas revisões de escopo de 2026-10-09 e 2026-10-10; o plano está no [backlog do roadmap](07-roadmap.md#backlog-futuro-fora-da-v10):

- Integração com IA: classificação, resumo, sugestão de resposta, busca semântica ([plano](06-integracao-ia.md))
- Tokens de API para integrações, webhooks de saída e servidor MCP
- Papéis personalizados, visões salvas, atalhos de teclado, antivírus nos anexos e campos extras por categoria
- Portal para colaboradores abrirem e acompanharem pedidos, abertura por e-mail e pesquisa de satisfação

### Fora do escopo (por enquanto)

- Atendimento a clientes externos
- Gestão de ativos / CMDB completa
- Gestão de mudanças e problemas no padrão ITIL completo
- Aplicativo mobile nativo (a interface web deve ser responsiva)
- Telefonia / URA
- SLA (metas de prazo, alertas de vencimento, calendário de expediente)

## Métricas de sucesso

- 100% do trabalho das equipes piloto registrado no sistema a partir da virada ([16](16-implantacao.md))
- Tempos medidos por grupo desde o piloto
- Backlog com mais de 7 dias sem crescer semana a semana
