# Lambda invalidadora: IaC

Terraform do invalidador: a Lambda ligada ao DynamoDB Streams da tabela `operacoes-credito`, com retries, DLQ e
alarmes.

## O que é criado

| Recurso | Configuração |
| --- | --- |
| Lambda `consultas-invalidador-cache` | Python 3.13, arm64, 512 MB, 30 s, na VPC do Valkey |
| Event source mapping (Streams) | `ReportBatchItemFailures`, bisect ligado, 5 tentativas, registros de até 10 min, lote de 1000, janela 0 s, `ParallelizationFactor` 4 |
| DLQ SQS `<nome>-dlq` | destino `OnFailure`; recebe os metadados do lote (shard e faixa de sequência), retenção de 14 dias, SSE |
| Security group da Lambda | saída só para o Valkey; regra de entrada correspondente no SG do Valkey |
| Role IAM | leitura do stream, `sqs:SendMessage` na DLQ, logs, `AWSLambdaVPCAccessExecutionRole` |
| Log group `/aws/lambda/<nome>` | retenção de 30 dias |
| Alarmes | `IteratorAge` > 2 s (3 de 5 min), `Errors` > 0, `FalhasValkey` > 0 (EMF), mensagens visíveis na DLQ |

Pontos de projeto:
- **Orçamento de 2 s:** a janela de lote fica em 0 s (a validação limita a 1 s), porque uma janela maior consome o
  orçamento. Para acompanhar uma Carga, a alavanca é o `ParallelizationFactor` (até 10). A ordem por
  `numero_operacao` (chave de partição) se mantém, que é o que a regra "REMOVE depois de INSERT" precisa.
- **A DLQ é diagnóstica:** uma invalidação perdida deixa o dado antigo até o TTL de 5 min, sem misturar versões.
  O `MaximumRecordAgeInSeconds` de 10 min descarta registros que já não teriam efeito.
- **Se o `IteratorAge` alarmar com frequência,** reavalie o estágio SQS → ECS, rejeitado por ora no ADR-0018.
- **TTLs e endpoint** precisam bater com a configuração da API (`consultas.cache.ttl`, `ttl-custodia`,
  `CONSULTAS_VALKEY_HOST`).
- **Senha ACL:** vai como variável de ambiente, cifrada pela KMS do Lambda. Se a política exigir Secrets Manager,
  troque por leitura do segredo no início da execução.

## Fora do escopo (pré-requisitos)

- Tabela `operacoes-credito` com o Streams ligado (`NEW_IMAGE` ou `NEW_AND_OLD_IMAGES`).
- VPC, subnets privadas e ElastiCache (Valkey), com `maxmemory-policy allkeys-lru` e alarme em
  `evicted_keys > 0` (ADR-0018).
- Tópico SNS dos alarmes.

O módulo recebe tudo por variável.

## Aplicar

```powershell
python scripts/empacotar.py                            # na raiz do repositório: monta build/pacote
cd infra/lambda
Copy-Item terraform.tfvars.example terraform.tfvars   # git-ignored; ajuste ARNs, subnets e o endpoint do Valkey
Copy-Item backend.hcl.example backend.hcl             # git-ignored; ajuste o bucket (a chave já é a deste repositório)
terraform init -backend-config=backend.hcl
terraform plan -out=tfplan
terraform apply tfplan
```

## Verificar

1. Escolha uma operação que esteja no cache:
   `HGETALL op:<id>:<custodia>` no Valkey traz `versao` e os blocos.
2. Grave um item dela no DynamoDB com um `codigo_identificador_carga` mais novo, ou deixe uma Atualização Online
   chegar.
3. Em até ~2 s, `HGETALL op:<id>:<custodia>` deve trazer só `versao=<nova em epoch ms>` e `marcador=1`, com
   `PTTL` perto de 300000.
4. No CloudWatch, o namespace `ConsultasOperacoesCredito/InvalidadorCache` deve mostrar `MarcadoresGravados`
   (`TipoChave=op`) e um `AtrasoMs` baixo.
5. A próxima consulta da operação na API repreenche o hash na versão nova.
