# consultas-operacoes-credito-trigger-invalidador-cache

## Stack

Lambda em **Python** (3.13+), ligada ao DynamoDB Streams da tabela `operacoes-credito`, grava o marcador de
invalidação no Valkey (cliente `redis-py`). Testes com `pytest` + `testcontainers` contra um Valkey real; Docker
é pré-requisito. Ver `README.md`.

## Agent skills

### Issue tracker

Issues e specs ficam nas GitHub Issues deste repositório
(`joaopedro-techon/consultas-operacoes-credito-trigger-invalidador-cache`), via `gh`. Ver
`docs/agents/issue-tracker.md`.

### Domain docs

Glossário e ADRs de origem ficam no repositório da API (`joaopedro-techon/consultas-operacoes-credito`). Ver
`docs/agents/domain.md`.
