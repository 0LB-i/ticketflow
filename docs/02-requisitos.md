# 2. Requisitos

Prioridade (MoSCoW): **M** = obrigatório no MVP, **S** = deveria ter, **C** = poderia ter, **W** = não agora.

## Requisitos funcionais

### RF-01 Chamados

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-01.1 | Abrir chamado com título, descrição, categoria e anexos | M |
| RF-01.2 | Número sequencial legível (ex.: `#2026-000123`) além do ID interno | M |
| RF-01.3 | Fluxo de status configurável, com um fluxo padrão (ver abaixo) | M |
| RF-01.4 | Prioridade (baixa, média, alta, crítica) definida por impacto × urgência | M |
| RF-01.5 | Atribuição a equipe (fila) e a agente | M |
| RF-01.6 | Comentários públicos e notas internas (visíveis só para agentes) | M |
| RF-01.7 | Histórico completo e imutável de alterações | M |
| RF-01.8 | Tags livres | S |
| RF-01.9 | Campos personalizados por categoria (formulários dinâmicos) | S |
| RF-01.10 | Vincular chamados (duplicado de, relacionado a, bloqueado por) | S |
| RF-01.11 | Mesclar chamados duplicados | C |
| RF-01.12 | Observadores (pessoas em cópia) | S |
| RF-01.13 | Pesquisa de satisfação ao fechar | S |
| RF-01.14 | Abertura de chamado por e-mail (caixa monitorada) e resposta por e-mail | S |

**Fluxo de status padrão:**

```
novo ──► em_atendimento ──► resolvido ──► fechado
  │            │  ▲              │
  │            ▼  │              └──► reaberto ──► em_atendimento
  │     aguardando_solicitante
  │     aguardando_terceiro
  └──► cancelado
```

- `resolvido` passa para `fechado` automaticamente após N dias sem resposta do solicitante (configurável).
- Nos status `aguardando_*`, o relógio de SLA de resolução **pausa**.

### RF-02 Filas e atribuição

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-02.1 | Equipes com membros e supervisores | M |
| RF-02.2 | Roteamento automático por categoria → equipe | M |
| RF-02.3 | Atribuição manual e "pegar para mim" | M |
| RF-02.4 | Atribuição automática (round-robin / menor carga) | C |
| RF-02.5 | Regras de automação (se X então Y) | C |

### RF-03 SLA

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-03.1 | Políticas de SLA por prioridade e categoria: prazo de 1ª resposta e de resolução | S |
| RF-03.2 | Calendário de expediente e feriados | S |
| RF-03.3 | Alertas de SLA próximo do vencimento e vencido | S |
| RF-03.4 | Escalonamento automático ao vencer | C |

### RF-04 Usuários e acesso

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-04.1 | Login local (e-mail + senha) | M |
| RF-04.2 | SSO via OIDC (Microsoft Entra ID, Google Workspace, Keycloak) | S |
| RF-04.3 | Sincronização / login via LDAP/Active Directory | C |
| RF-04.4 | Papéis: solicitante, agente, supervisor, admin (RBAC) | M |
| RF-04.5 | Solicitante só vê os próprios chamados e aqueles em que é observador | M |

### RF-05 Notificações e integrações

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-05.1 | Notificação por e-mail em eventos relevantes | M |
| RF-05.2 | Preferências de notificação por usuário | S |
| RF-05.3 | Webhooks de saída assinados (HMAC) | S |
| RF-05.4 | Notificações no Teams / Slack | C |
| RF-05.5 | API REST completa e documentada (OpenAPI) | M |
| RF-05.6 | Tokens de API com escopos para integrações e agentes de IA | M |

### RF-06 Busca e conhecimento

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-06.1 | Busca textual em português (título, descrição, comentários) | M |
| RF-06.2 | Filtros e visões salvas | S |
| RF-06.3 | Base de conhecimento (artigos internos e públicos) | S |
| RF-06.4 | Busca semântica (embeddings) em chamados e artigos | S |

### RF-07 Inteligência artificial

Detalhado em [06-integracao-ia.md](06-integracao-ia.md).

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-07.1 | Classificação automática (categoria, prioridade, equipe) com sugestão para revisão | S |
| RF-07.2 | Resumo do chamado (útil em chamados longos e em transferências) | S |
| RF-07.3 | Sugestão de resposta para o agente, com base em histórico e base de conhecimento | S |
| RF-07.4 | Detecção de chamados duplicados ou semelhantes | S |
| RF-07.5 | Assistente de abertura: sugere artigos antes de abrir o chamado (deflexão) | C |
| RF-07.6 | Servidor MCP para agentes de IA operarem o sistema | C |
| RF-07.7 | Geração de artigo de conhecimento a partir de chamado resolvido | C |
| RF-07.8 | Análise de sentimento / urgência | C |

### RF-08 Relatórios

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-08.1 | Painel: abertos, por status, por equipe, vencendo SLA | S |
| RF-08.2 | Indicadores: tempo de 1ª resposta, tempo de resolução, % SLA, satisfação | S |
| RF-08.3 | Exportação CSV | S |

## Requisitos não funcionais

| ID | Categoria | Requisito |
|----|-----------|-----------|
| RNF-01 | Desempenho | p95 < 300 ms nas leituras da API com 1 milhão de chamados |
| RNF-02 | Escala | Suportar 5 mil usuários e 500 agentes por instalação |
| RNF-03 | Disponibilidade | 99,5% em horário comercial; a indisponibilidade da IA **não** pode impedir o uso do sistema |
| RNF-04 | Segurança | OWASP ASVS nível 2; senhas com Argon2id; TLS obrigatório |
| RNF-05 | Auditoria | Todas as ações (inclusive de clientes de API e IA) registradas com autor, data e origem |
| RNF-06 | LGPD | Minimização de dados enviados a IA, mascaramento de dados pessoais, retenção configurável, exportação e anonimização de dados de um titular |
| RNF-07 | Banco | PostgreSQL 16 e 17 suportados; CI testa as duas versões |
| RNF-08 | Observabilidade | Logs estruturados (JSON), métricas Prometheus, tracing OpenTelemetry |
| RNF-09 | Implantação | Imagem Docker; roda com apenas app + PostgreSQL (sem Redis/RabbitMQ obrigatórios) |
| RNF-10 | Qualidade | Cobertura de testes ≥ 80% no domínio; lint e checagem de tipos no CI |
| RNF-11 | Acessibilidade | Interface web WCAG 2.1 AA |
| RNF-12 | Idioma | Interface em pt-BR, com estrutura de i18n preparada |
