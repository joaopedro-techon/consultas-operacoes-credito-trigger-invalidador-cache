# Domain Docs

Regras para as skills de engenharia usarem a documentação de domínio quando explorarem este repositório.

Layout: **contexto emprestado**. O domínio (visão consolidada de operações de crédito, cache versionado) é o mesmo
da API de consultas. O glossário e os ADRs de origem ficam lá, não aqui.

## Antes de explorar, leia

- **`GLOSSARY.md`** do repositório `joaopedro-techon/consultas-operacoes-credito`. Clone irmão:
  `../v1/GLOSSARY.md`; sem clone, use `gh api repos/joaopedro-techon/consultas-operacoes-credito/contents/GLOSSARY.md`.
  Termos centrais aqui: Atualização Online, Atualização Offline, Carga, Versão do registro, Marcador de
  invalidação, Cache de blocos, Cache de custódia.
- **ADR-0018** (cache versionado por operação) do mesmo repositório, que define o contrato deste invalidador.
  Também o ADR-0017 (chave `custodia:{id}` compartilhada com a fonte primária, que este repositório nunca toca).
- **`docs/adr/`** deste repositório, se existir: decisões que só valem para o invalidador.

Se algum desses arquivos não existir, siga em silêncio.

## Onde registrar

- Termo novo ou mudança de termo: no `GLOSSARY.md` da API (via PR lá), nunca num glossário paralelo aqui.
- Decisão que muda o contrato com a API (formato das chaves, regra de versão, TTLs): ADR na API.
- Decisão só do invalidador (runtime, empacotamento, infraestrutura): ADR em `docs/adr/` deste repositório, criado
  quando a primeira decisão aparecer.

## Use o vocabulário do glossário

Quando um texto (título de issue, nome de teste, proposta de refactor) nomear um conceito de domínio, use o termo
do glossário. Se o conceito ainda não estiver no glossário, ou o termo está sendo inventado, ou há uma lacuna real
para o `/domain-modeling`.

## Aponte conflitos com ADRs

Se o que você vai produzir contradiz um ADR, diga isso explicitamente em vez de passar por cima:

> _Contradiz o ADR-0018 (cache versionado), mas vale reabrir porque…_
