# consultas-operacoes-credito-trigger-invalidador-cache

Lambda (Python) ligada ao DynamoDB Streams da tabela `operacoes-credito`. Ela invalida o **cache versionado** da
visão consolidada de operações de crédito, que fica no Valkey. As decisões estão nos ADR-0018 e ADR-0019 do
repositório [`consultas-operacoes-credito`](https://github.com/joaopedro-techon/consultas-operacoes-credito); a spec
está na issue #1.

A API escolhe a regra de versão dos blocos (`consultas.visao-consolidada.versao-dos-blocos`, ADR-0019), e cada regra
usa um formato próprio de cache. O invalidador **não tem flag**: marca sempre os dois formatos, então trocar a regra
na API não abre janela sem invalidação.

Para cada linha (um bloco de uma operação numa custódia) gravada na **versão do registro** V
(`codigo_identificador_carga` em epoch ms), a Lambda grava o **marcador de invalidação**:

```text
op:{id}:{custodia}   (versão única)     versao ausente ou < V   → hash vira {versao=V, marcador=1}, TTL de 5 min
opb:{id}:{custodia}  (versão por bloco) v:{bloco} ausente ou < V → só o bloco vira {v:{bloco}=V, m:{bloco}=1};
                                                                  os demais blocos ficam; TTL de 5 min só na criação
versão no cache ≥ V                                              → intacto
```

Por evento, na ordem do shard (vence a última ação por alvo; entre marcações, a maior V):

| Evento | `op:{id}:{custodia}` | `opb:{id}:{custodia}` (só o bloco da linha) | `custodia-vc:{id}` (só linha `OPERACAO`) |
| --- | --- | --- | --- |
| MODIFY com V | marcador V | marcador V no bloco | — |
| INSERT com V | marcador V | marcador V no bloco | marcador V (TTL 24 h) |
| REMOVE | `DEL` | `HDEL` do bloco | `DEL` |
| versão ausente ou inválida | `DEL` | `HDEL` do bloco | `DEL` se INSERT |

O cache de custódia só muda com a linha do bloco `OPERACAO`. Com escritores que gravam só os blocos alterados, o
INSERT de um bloco novo na mesma custódia (o primeiro `controles_iof`, por exemplo) não muda a custódia vencedora e
não pode deixá-la marcada. Numa migração, os escritores gravam todos os blocos no destino, inclusive `OPERACAO`.

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
| `CACHE_TTL_OPERACAO_MS` | `300000` | TTL do marcador em `op:*` e `opb:*`; igual a `consultas.cache.ttl` da API |
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
  - por `TipoChave` (`op`, `opb` ou `custodia-vc`): `MarcadoresGravados` e `MarcadoresRejeitados` (no `opb`, um
    por bloco). `ChavesRemovidas` conta também os blocos apagados do `opb`.
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
Testcontainers). Testes de contrato rodam os scripts de gravação da API (`tests/fixtures`:
`gravar_versionado_api.lua` e `gravar_por_bloco_api.lua`) sobre o marcador. Se um script mudar na API, a cópia em
`tests/fixtures` precisa mudar junto.

## Deploy

Terraform em [`infra/lambda`](infra/lambda/README.md): função, mapeamento do Streams, DLQ, alarmes, IAM e rede. O pacote é montado por `python scripts/empacotar.py`, que gera `build/pacote`.
