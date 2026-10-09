# 0004. IA agnóstica de provedor e assistiva por padrão

- **Status:** Proposta
- **Data:** 2026-10-09

## Contexto

O sistema deve se integrar a IAs via API. O mercado de modelos muda rápido, cada empresa tem contratos e políticas de dados diferentes, e chamados internos podem conter dados pessoais e sensíveis (RH, saúde, jurídico).

## Decisão

- Uma interface interna `AIProvider` (`complete`, `complete_structured`, `embed`) com adaptadores por provedor. O provedor e o modelo são configurados **por funcionalidade**, não fixos no código.
- A IA é **assistiva por padrão**: gera sugestões que um humano aceita, edita ou rejeita. A aplicação automática é opcional e exige limite de confiança.
- Toda execução é registrada (`ai_runs`) com a entrada mascarada, a saída, os tokens, a latência e o feedback.
- Dados passam por mascaramento antes de sair; categorias podem proibir o uso de IA.
- Agentes de IA externos operam o sistema pela mesma API (e depois via MCP), com tokens de escopo mínimo e identidade própria na auditoria.

## Alternativas consideradas

- **Acoplar a um único provedor via SDK:** mais rápido no começo, mas cria dependência de fornecedor e impede o uso de modelo local para dados sensíveis.
- **Frameworks de orquestração (LangChain, LlamaIndex):** aceleram protótipos, mas adicionam muita abstração e mudam com frequência. Preferimos uma camada própria fina, e podemos reavaliar.

## Consequências

- Cada adaptador precisa de testes próprios, e os recursos variam entre provedores (saída estruturada, cache de prompt).
- O conjunto de avaliação (evals) passa a fazer parte do CI para detectar regressões ao trocar de modelo ou de prompt.
