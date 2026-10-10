# 0004. IA por uma API genérica, sem código por provedor ou modelo, e assistiva por padrão

- **Status:** Aceita
- **Data:** 2026-10-09

> **Nota (2026-10-09):** na revisão de escopo, a integração com IA saiu da v1.0 e foi para o backlog. A decisão continua valendo para quando a IA entrar.

## Contexto

O sistema deve se integrar a IAs via API. O mercado de modelos muda rápido, cada empresa tem contratos e políticas de dados diferentes, e chamados internos podem conter dados pessoais e sensíveis (RH, saúde, jurídico). Não queremos manter código específico para cada provedor ou modelo.

## Decisão

- **Um único cliente HTTP genérico**, no formato compatível com a API da OpenAI, que virou o padrão de fato do mercado:
  - `POST {base_url}/chat/completions` para geração de texto;
  - `POST {base_url}/embeddings` para vetores.
- A configuração de cada endpoint é **apenas**: URL base, chave (referência a um segredo), nome do modelo (texto livre) e parâmetros genéricos (timeout, temperatura, limite de tokens). Ver a tabela `ai_endpoints`.
- **Nenhum SDK de fornecedor e nenhum nome de modelo no código.** Para usar um serviço que não fala esse formato, a empresa coloca um gateway na frente (ex.: LiteLLM); o sistema não muda.
- **Saída estruturada portátil:** o prompt pede JSON, a resposta é validada com Pydantic e há uma nova tentativa enviando o erro de validação. O uso de `response_format` com JSON Schema é opcional, ligado por configuração.
- Funcionalidades diferentes podem usar endpoints diferentes (ex.: um modelo local para categorias sensíveis e outro para embeddings).
- **Dimensão dos embeddings** definida na instalação (`AI_EMBEDDING_DIM`); um comando de reindexação recalcula tudo ao trocar de modelo.
- A IA é **assistiva por padrão**: gera sugestões que um humano aceita, edita ou rejeita. A aplicação automática é opcional e exige limite de confiança.
- Toda execução é registrada (`ai_runs`) com a entrada mascarada, a saída, o modelo usado, os tokens, a latência e o feedback.
- Dados passam por mascaramento antes de sair; categorias podem proibir o uso de IA.
- Na direção inversa, agentes de IA externos operam o sistema pela mesma API REST (e depois via MCP), com tokens de escopo mínimo e identidade própria na auditoria.

## Alternativas consideradas

- **Adaptadores por provedor (SDKs oficiais):** permitem recursos específicos de cada um (cache de prompt, ferramentas nativas), mas exigem código e testes por fornecedor e acoplam o produto a eles.
- **Frameworks de orquestração (LangChain, LlamaIndex):** muita abstração e mudanças frequentes; o cliente genérico tem poucas centenas de linhas.

## Consequências

- Trocar de modelo ou de provedor é só mudar a configuração, sem deploy.
- Não aproveitamos recursos exclusivos de provedores. Aceitável enquanto as funcionalidades forem classificação, resumo, sugestão e embeddings.
- Diferenças de comportamento entre serviços "compatíveis" (campos ignorados, `usage` ausente) precisam ser toleradas: o cliente trata campos opcionais como opcionais.
- O conjunto de avaliação (evals) faz parte do CI e deve ser rodado ao trocar de modelo, porque a qualidade muda mesmo com a mesma API.
