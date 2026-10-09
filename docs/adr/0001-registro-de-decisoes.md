# 0001. Registrar decisões em ADRs e convenções de idioma

- **Status:** Aceita
- **Data:** 2026-10-09

## Contexto

O projeto começa do zero e várias decisões estruturais serão tomadas antes de existir código. Precisamos registrar o *porquê* de cada uma.

## Decisão

- Decisões de arquitetura são registradas como ADRs em `docs/adr/`, numeradas e imutáveis. Para mudar uma decisão, escreve-se um novo ADR que substitui o anterior.
- **Documentação** em português (pt-BR).
- **Identificadores de código, banco de dados e API** em inglês (`ticket`, `assignee`, `status_changed`).
- **Textos de interface** em pt-BR, via arquivos de tradução (i18n) desde o início.

## Alternativas consideradas

- **Tudo em português** (`chamado`, `responsavel`): mais próximo do domínio, mas mistura com palavras-chave e bibliotecas em inglês, tem problemas com acentos em identificadores e dificulta contribuições externas.

## Consequências

- É preciso manter um glossário curto (chamado = ticket, fila = queue/team, solicitante = requester, responsável = assignee, observador = watcher).
