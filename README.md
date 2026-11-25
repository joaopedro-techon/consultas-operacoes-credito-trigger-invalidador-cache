# consultas-operacoes-credito-trigger-invalidador-cache

Lambda (Python) ligada ao DynamoDB Streams da tabela `operacoes-credito`. Ela invalida o **cache versionado** da
visão consolidada de operações de crédito, que fica no Valkey. As decisões estão no ADR-0018 do repositório
[`consultas-operacoes-credito`](https://github.com/joaopedro-techon/consultas-operacoes-credito); a spec está na
issue #1.

Para cada operação gravada numa custódia na **versão do registro** V (`codigo_identificador_carga` em epoch ms),
a Lambda grava o **marcador de invalidação** em `op:{id_operacao}:{custodia}`:

```text
versão no cache ausente ou < V  → hash vira {versao=V, marcador=1}, TTL de 5 min
versão no cache ≥ V             → intacto
```

Por evento, na ordem do shard (vence a última ação por chave; entre marcações, a maior V):

| Evento | `op:{id}:{custodia}` | `custodia-vc:{id}` |
| --- | --- | --- |
| MODIFY com V | marcador V | — |
| INSERT com V | marcador V | marcador V (TTL 24 h) |
| REMOVE | `DEL` | `DEL` |
| versão ausente ou inválida | `DEL` | `DEL` se INSERT |

A chave compartilhada `custodia:{id}` (contrato com a fonte primária, ADR-0017) nunca é tocada.

A API só substitui um hash com marcador quando lê a versão V ou uma mais nova. Por isso, uma leitura atrasada com
o dado antigo não volta a preencher o cache.

## Configuração (variáveis de ambiente)

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `VALKEY_HOST` / `VALKEY_PORTA` | `localhost` / `6379` | Endpoint do Valkey (o mesmo da API) |
| `VALKEY_TLS` | `false` | `true` em ElastiCache com TLS |
| `VALKEY_USUARIO` / `VALKEY_SENHA` | vazio | Autenticação (ACL), se houver |
| `VALKEY_TIMEOUT_MS` / `VALKEY_TIMEOUT_CONEXAO_MS` | `200` / `500` | Timeouts de comando e de conexão |
| `CACHE_TTL_OPERACAO_MS` | `300000` | TTL do marcador em `op:*`; igual a `consultas.cache.ttl` da API |
| `CACHE_TTL_CUSTODIA_MS` | `86400000` | TTL do marcador em `custodia-vc:*`; igual a `consultas.cache.ttl-custodia` da API |

| `METRICAS_NAMESPACE` | `ConsultasOperacoesCredito/InvalidadorCache` | Namespace das métricas no CloudWatch |

Handler: `invalidador.handler.handler`.

## Falhas, métricas e logs

- Se o Valkey falhar (conexão, timeout ou outro erro), todos os registros do lote voltam em `batchItemFailures`
  e o Lambda tenta de novo. O plano é idempotente, então reprocessar não tem efeito colateral. O cliente faz no
  máximo uma repetição curta, para não prender a invocação.
- Métricas em EMF (JSON no stdout, sem chamada à API):
  - por lote: `TamanhoLote`, `ChavesRemovidas`, `VersoesInvalidas`, `RegistrosInvalidos`, `FalhasValkey` e
    `AtrasoMs` (agora menos o `ApproximateCreationDateTime` do registro mais antigo);
  - por `TipoChave` (`op` ou `custodia-vc`): `MarcadoresGravados` e `MarcadoresRejeitados`.
- Logs em JSON, uma linha por evento, com `resultado` e no máximo chave, versão, quantidade de registros,
  sequência e o tipo do erro. Nunca levam `texto_detalhe` nem outros atributos da imagem.

## Testes

Pré-requisitos: Docker e Python 3.13+.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install redis pytest testcontainers
.\.venv\Scripts\python -m pytest
```

Os testes chamam o handler com eventos do Streams contra um Valkey real (`valkey/valkey:9.0.8-alpine`, via
Testcontainers). Um teste de contrato roda o script de gravação da API (`tests/fixtures`) sobre o marcador. Se o
script mudar na API, a cópia em `tests/fixtures` precisa mudar junto.

## Deploy

Terraform em [`infra/lambda`](infra/lambda/README.md): função, mapeamento do Streams, DLQ, alarmes, IAM e rede. O pacote é montado por `python scripts/empacotar.py`, que gera `build/pacote`.
