# 16. Plano de implantação

Como o TicketFlow entra em uso na Martiniti: primeiro com a **TI** (piloto, marco M1 do [roadmap](07-roadmap.md)) e depois com as outras equipes (M2).

## 16.1 Premissas

- Só a equipe usa o sistema ([modelo](08-organizacao-e-permissoes.md)). Para o resto da empresa **nada muda**: as pessoas continuam pedindo à TI como hoje, e quem recebe o pedido registra o chamado.
- **Virada com data marcada:** a partir do dia D, todo trabalho da TI passa pelo TicketFlow. Não há período de convivência com o controle antigo.
- **Sem importação de histórico.** No dia D entram só as tarefas que ainda estão em aberto, cadastradas à mão. O histórico antigo continua onde está, para consulta.
- A instalação é a de produção ([manual do servidor](18-manual-do-servidor.md)). Não há homologação ([12.6](12-processo-de-desenvolvimento.md#126-ambientes)): o treinamento acontece na própria produção, num grupo **Treinamento** que é desativado antes da virada.

## 16.2 Papéis na implantação

| Papel | Quem | Responsabilidades |
|-------|------|-------------------|
| **Dono da implantação** | Supervisor da TI | Marca a data D, cobra os combinados, decide se o piloto continua |
| **Administrador** | Definido em [15.1](15-estrutura-martiniti.md#151-perguntas-para-responder-primeiro) | Carga inicial, usuários, ajustes de categorias e status |
| **Desenvolvedor** | Quem desenvolve o TicketFlow | Instalação, treinamento, correções e coleta de retorno |
| **Equipe da TI** | Todos os membros | Registrar todo o trabalho no sistema a partir de D |

## 16.3 Cronograma

O dia D é marcado no início da Sprint 5. Sugestão: uma **terça ou quarta-feira**, fora de fechamento de mês e de férias da equipe.

| Quando | O quê | Responsável | Pronto quando |
|--------|-------|-------------|---------------|
| D−15 | Servidor de produção pronto conforme o [manual](18-manual-do-servidor.md): HTTPS, e-mail de envio funcionando, backup **restaurado com sucesso** pelo menos uma vez | Desenvolvedor | Todos os passos de 18.3 e a restauração de 18.5 conferidos |
| D−10 | Carga inicial ([15](15-estrutura-martiniti.md)): grupos, setores atendidos, categorias, usuários convidados | Administrador | Todos os membros conseguem entrar |
| D−7 | **Treinamento** de 1 hora (16.5) + guia rápido (16.6) | Desenvolvedor | Cada membro registrou, assumiu e concluiu um chamado de teste |
| D−3 a D−1 | **Levantamento das tarefas em aberto**: cada membro lista o que está com ele hoje (e-mails, anotações, mensagens, planilhas) | Equipe da TI | Lista pronta para cadastrar |
| **D** | **Virada.** Até o meio-dia, cada um cadastra as próprias tarefas em aberto. A partir daí vale a regra: *se não está no TicketFlow, não existe* | Equipe da TI | Nenhuma tarefa em aberto fora do sistema |
| D+1 a D+10 | **Acompanhamento próximo**: 10 minutos diários revisando "Não atribuídos" e dúvidas; desenvolvedor disponível para correções | Supervisor + desenvolvedor | — |
| D+7 | 1ª conversa de retorno (16.7) | Supervisor + desenvolvedor | Ajustes priorizados |
| D+14 | **Avaliação do M1**: duas semanas usando só o sistema, sem bugs críticos abertos | Supervisor | Decisão: piloto aprovado, estendido ou pausado |
| D+30 | Retrospectiva: categorias, status e combinados revistos com os dados do primeiro mês | Supervisor + equipe | Mudanças aplicadas pelo administrador |

## 16.4 Combinados da equipe (proposta)

Regras simples, para que o sistema reflita de fato o trabalho da TI. A equipe ajusta na retrospectiva.

1. **Todo pedido vira chamado**, por qualquer canal que chegue, se levar mais de 15 minutos ou depender de outra pessoa. Pedidos rápidos resolvidos na hora são opcionais.
2. **Quem recebe o pedido registra**, preenchendo setor e pessoa atendidos.
3. **Tarefa parada vai para "Aguardando"**, com um comentário dizendo o que falta.
4. **Concluir com o que foi feito.** O texto da conclusão é o que vai ajudar na próxima vez.
5. **Combinar no chamado.** Decisões e informações importantes ficam em comentário, não só na conversa.

## 16.5 Treinamento (1 hora)

Na própria produção, antes da virada. O administrador cria um grupo **Treinamento** com todos os membros; os chamados de teste ficam nele. Depois do treinamento, os chamados de teste são cancelados e o grupo é desativado, então não aparecem nas filas nem nos relatórios dos grupos reais.

| Tempo | Conteúdo |
|-------|----------|
| 10 min | Por que o TicketFlow, os combinados (16.4) e a data D |
| 15 min | Demonstração: registrar, assumir, comentar com @menção, aguardar, transferir, concluir |
| 25 min | Mão na massa no grupo Treinamento: cada um faz o ciclo completo com dois chamados de teste e testa um pelo celular |
| 10 min | Dúvidas, perfil (senha, notificações, tema) e como dar retorno |

O administrador tem um treinamento separado, de 30 minutos, sobre as telas de administração.

## 16.6 Guia rápido (uma página)

Entregue no treinamento e linkado na tela inicial do sistema. Conteúdo:

- endereço do sistema e como entrar (convite, esqueci a senha);
- o caminho do chamado: **Novo chamado → Pendente → (Aguardando) → Concluído**;
- o significado de cada fila;
- os cinco combinados;
- a quem pedir ajuda e como relatar um problema.

## 16.7 Retorno e correções durante o piloto

- **Canal único de retorno:** um formulário simples ou um grupo de mensagens combinado no treinamento. Cada retorno vira um item no `TAREFAS.md` ([12.1](12-processo-de-desenvolvimento.md#121-repositório-e-tarefas)).
- **Triagem semanal** entre o supervisor e o desenvolvedor: o que é bug, o que é ajuste de configuração e o que vai para o backlog.
- **Bug crítico** (impede registrar ou trabalhar chamados): correção no mesmo dia ou plano de contorno (16.8).

## 16.8 Plano de contingência

| Situação | O que fazer |
|----------|-------------|
| Sistema fora do ar por menos de meio dia | Anotar as tarefas numa lista compartilhada e cadastrar quando voltar |
| Sistema fora do ar por mais de um dia, ou perda de dados | Restaurar o backup mais recente ([03](03-arquitetura.md#implantação)) e cadastrar as tarefas criadas depois dele |
| Piloto pausado na avaliação do D+14 | A equipe volta ao controle anterior; os chamados em aberto são exportados (CSV) para não se perderem |

## 16.9 Como medir o piloto

| Medida | Como | Meta |
|--------|------|------|
| Adesão | Pergunta na conversa semanal: "algum trabalho seu ficou fora do sistema?" | Nenhum a partir da 2ª semana |
| Uso | Chamados registrados e concluídos por semana (relatório 14) | Volume estável depois da 1ª semana |
| Fila sob controle | Backlog com mais de 7 dias | Não crescer semana a semana |
| Qualidade | Bugs críticos abertos | Zero no D+14 |

## 16.10 Expansão para outras equipes (Fase 2, M2)

Cada nova equipe (ex.: RH, Financeiro) segue uma versão curta deste plano:

1. Grupo, supervisor, membros e categorias definidos com o modelo do [documento 15](15-estrutura-martiniti.md).
2. Avaliar se alguma categoria é **confidencial** (ex.: folha de pagamento).
3. Treinamento de 1 hora e guia rápido.
4. Data de virada própria e duas semanas de acompanhamento.

A meta do M2 é ter pelo menos três equipes além da TI usando o sistema.
