# 1. Visão geral

## Problema

Em muitas empresas, as solicitações internas (TI, RH, facilities, financeiro, jurídico) chegam por e-mail, chat e corredor. O resultado:

- pedidos se perdem ou ficam sem dono;
- não há prazo acordado (SLA) nem medição de desempenho;
- o conhecimento para resolver problemas recorrentes fica na cabeça das pessoas;
- não há dados para priorizar melhorias.

## Objetivo

Construir um sistema de chamados interno que:

1. centralize as solicitações em **filas por equipe**, cada chamado com responsável, prioridade e prazo;
2. dê ao solicitante **transparência** sobre o andamento;
3. meça **SLA** e gere indicadores;
4. seja **API-first**, para integrar com outros sistemas e principalmente com **IAs**, tanto consumindo serviços de IA (triagem, resumo, sugestão de resposta) quanto sendo operado por agentes de IA;
5. rode sobre **Python + PostgreSQL**, com operação simples (poucos componentes de infraestrutura).

## Público

| Perfil | O que faz |
|--------|-----------|
| **Solicitante** | Qualquer colaborador. Abre e acompanha os próprios chamados, responde e avalia o atendimento. |
| **Agente** | Membro de uma equipe de atendimento. Trabalha os chamados das filas dele. |
| **Supervisor** | Gerencia uma ou mais equipes: redistribui chamados, acompanha SLA e relatórios. |
| **Administrador** | Configura o sistema: usuários, equipes, categorias, SLAs, integrações e IA. |
| **Cliente de API** | Sistema externo ou agente de IA autenticado por token com escopos. |

## Escopo

### Dentro do escopo (versão 1.x)

- Abertura de chamados (web, e-mail e API)
- Filas, atribuição, status, prioridades e categorias
- Comentários públicos e notas internas, anexos
- SLA (primeira resposta e resolução) com calendário de expediente
- Notificações por e-mail e webhooks
- Busca textual em português
- Base de conhecimento
- Relatórios operacionais
- Integração com IA: classificação, resumo, sugestão de resposta, busca semântica

### Fora do escopo (por enquanto)

- Atendimento a clientes externos (é um help desk **interno**)
- Gestão de ativos / CMDB completa
- Gestão de mudanças e problemas no padrão ITIL completo
- Aplicativo mobile nativo (a interface web deve ser responsiva)
- Telefonia / URA

## Métricas de sucesso

- 100% das solicitações das equipes piloto passando pelo sistema em até 60 dias após a implantação
- Cumprimento de SLA de primeira resposta ≥ 90%
- Redução do tempo médio de triagem (meta a definir após a medição de base)
- Pelo menos 30% das sugestões de IA aceitas pelos agentes (com ou sem edição)
