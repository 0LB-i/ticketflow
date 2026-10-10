# 2. Requisitos

Prioridade (MoSCoW): **M** = obrigatório no MVP, **S** = deveria ter, **C** = poderia ter, **W** = não agora.

Na revisão de escopo de 2026-10-09, vários itens passaram para **W** (depois da v1.0) e estão marcados como *(futuro)*. Ver o [backlog do roadmap](07-roadmap.md#backlog-futuro-fora-da-v10).

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
| RF-01.9 | Campos personalizados por categoria (formulários dinâmicos) | W (futuro) |
| RF-01.10 | Vincular chamados (duplicado de, relacionado a, bloqueado por) | S |
| RF-01.11 | Mesclar chamados duplicados | C |
| RF-01.12 | Observadores (pessoas em cópia) | S |
| RF-01.13 | Pesquisa de satisfação ao fechar | S |
| RF-01.14 | Abertura de chamado por e-mail (caixa monitorada) e resposta por e-mail | S |
| RF-01.15 | Tipos de chamado: incidente, requisição, dúvida | M |
| RF-01.16 | Abertura em nome de outra pessoa (telefone, presencial) | M |
| RF-01.17 | Aprovação de requisições pelo gestor do setor, por um usuário ou por um grupo | S |
| RF-01.18 | Respostas prontas (macros) pessoais, do grupo e globais | S |
| RF-01.19 | Categorias confidenciais com visibilidade restrita | M |

Fluxo de status, transições e regras de trabalho: ver [Como funcionam os chamados](10-chamados.md).

### RF-02 Filas e atribuição

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-02.1 | Equipes com membros e supervisores | M |
| RF-02.2 | Roteamento automático por categoria → equipe | M |
| RF-02.3 | Atribuição manual e "pegar para mim" | M |
| RF-02.4 | Atribuição automática (round-robin / menor carga) | C |
| RF-02.5 | Regras de automação (se X então Y) | C |

### RF-03 SLA

Removido: não haverá SLA (metas de prazo, calendário de expediente, alertas). Decisão de 2026-10-09.

### RF-04 Usuários e acesso

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-04.1 | Login local (e-mail + senha) | M |
| RF-04.2 | SSO via OIDC (Microsoft Entra ID, Google Workspace, Keycloak) | W (a empresa não tem diretório de contas) |
| RF-04.3 | Sincronização / login via LDAP/Active Directory | W |
| RF-04.4 | Papéis: solicitante, agente, supervisor, admin (RBAC) | M |
| RF-04.5 | Regras de visibilidade conforme [8.4](08-organizacao-e-permissoes.md#84-regras-de-visibilidade-de-chamados) | M |
| RF-04.6 | Setores em árvore com gestores; grupos de atendimento com membros e supervisores | M |
| RF-04.7 | MFA (TOTP), obrigatório para administradores no login local | S |
| RF-04.8 | Mapeamento de grupos do provedor de identidade para papel, setor e grupos | W (depende de SSO) |
| RF-04.9 | Papéis personalizados | W (futuro) |

Detalhes em [Organização e permissões](08-organizacao-e-permissoes.md) e [Login e autenticação](09-login-e-autenticacao.md).

### RF-05 Notificações e integrações

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-05.1 | Notificação por e-mail em eventos relevantes | M |
| RF-05.2 | Preferências de notificação por usuário | S |
| RF-05.3 | Webhooks de saída assinados (HMAC) | W (futuro) |
| RF-05.4 | Notificações no Teams / Slack | W (futuro) |
| RF-05.5 | API REST completa e documentada (OpenAPI) | M |
| RF-05.6 | Tokens de API com escopos para integrações e agentes de IA | W (futuro) |

### RF-06 Busca e conhecimento

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-06.1 | Busca textual em português (título, descrição, comentários) | M |
| RF-06.2 | Filtros nas listas de chamados | M |
| RF-06.5 | Visões salvas (filtros guardados pelo usuário ou pelo grupo) | W (futuro) |
| RF-06.3 | Base de conhecimento (artigos internos e públicos) | S |
| RF-06.4 | Busca semântica (embeddings) em chamados e artigos | W (futuro) |

### RF-07 Inteligência artificial

**Toda a seção fica para depois da v1.0** (revisão de escopo de 2026-10-09). Plano em [06-integracao-ia.md](06-integracao-ia.md).

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-07.1 | Classificação automática (categoria, prioridade, equipe) com sugestão para revisão | W (futuro) |
| RF-07.2 | Resumo do chamado (útil em chamados longos e em transferências) | W (futuro) |
| RF-07.3 | Sugestão de resposta para o agente, com base em histórico e base de conhecimento | W (futuro) |
| RF-07.4 | Detecção de chamados duplicados ou semelhantes | W (futuro) |
| RF-07.5 | Assistente de abertura: sugere artigos antes de abrir o chamado (deflexão) | W (futuro) |
| RF-07.6 | Servidor MCP para agentes de IA operarem o sistema | W (futuro) |
| RF-07.7 | Geração de artigo de conhecimento a partir de chamado resolvido | W (futuro) |
| RF-07.8 | Análise de sentimento / urgência | W (futuro) |

### RF-08 Relatórios

| ID | Requisito | Prior. |
|----|-----------|--------|
| RF-08.1 | Painel: abertos, por status, por equipe | S |
| RF-08.2 | Indicadores: tempo de 1ª resposta, tempo até a entrega, satisfação | S |
| RF-08.3 | Exportação CSV | S |

## Requisitos não funcionais

| ID | Categoria | Requisito |
|----|-----------|-----------|
| RNF-01 | Desempenho | p95 < 300 ms nas leituras da API com 50 mil chamados |
| RNF-02 | Escala | Até 50 usuários na empresa; deve suportar até ~500 sem mudanças de arquitetura |
| RNF-03 | Disponibilidade | 99,5% em horário comercial |
| RNF-04 | Segurança | OWASP ASVS nível 2; senhas com Argon2id; TLS obrigatório |
| RNF-05 | Auditoria | Todas as ações registradas com autor, data e origem |
| RNF-06 | LGPD | Retenção configurável, exportação e anonimização de dados de um titular. Quando a IA entrar: minimização e mascaramento dos dados enviados |
| RNF-07 | Banco | PostgreSQL 16 e 17 suportados; CI testa as duas versões |
| RNF-08 | Observabilidade | Logs estruturados (JSON), métricas Prometheus, tracing OpenTelemetry |
| RNF-09 | Implantação | Serviços systemd (API + worker) + nginx + PostgreSQL em um único servidor, sem Redis/RabbitMQ ([ADR 0010](adr/0010-producao-systemd.md)) |
| RNF-10 | Qualidade | Cobertura de testes ≥ 80% no domínio; lint e checagem de tipos no CI |
| RNF-11 | Acessibilidade | Interface web WCAG 2.1 AA |
| RNF-12 | Idioma | Interface em pt-BR, com estrutura de i18n preparada |
