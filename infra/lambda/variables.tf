variable "aws_region" {
  description = "Regiao AWS da tabela, do Valkey e da Lambda."
  type        = string
}

variable "nome" {
  description = "Prefixo dos recursos (funcao, role, fila, alarmes)."
  type        = string
  default     = "consultas-invalidador-cache"
}

variable "tags" {
  description = "Tags padrao de todos os recursos."
  type        = map(string)
  default     = {}
}

# ---------------------------------------------------------------------------------------------------------
# Infraestrutura existente (nao criada aqui)
# ---------------------------------------------------------------------------------------------------------

variable "stream_arn" {
  description = "ARN do DynamoDB Stream da tabela operacoes-credito (StreamViewType NEW_IMAGE ou NEW_AND_OLD_IMAGES)."
  type        = string
}

variable "vpc_id" {
  description = "VPC do Valkey (ElastiCache)."
  type        = string
}

variable "subnet_ids" {
  description = "Subnets privadas da Lambda, com rota para o Valkey (uma por AZ)."
  type        = list(string)
}

variable "valkey_security_group_id" {
  description = "Security group do Valkey; recebe a regra de entrada vinda da Lambda."
  type        = string
}

variable "valkey_host" {
  description = "Endpoint primario do Valkey (o mesmo da API: CONSULTAS_VALKEY_HOST)."
  type        = string
}

variable "valkey_porta" {
  description = "Porta do Valkey."
  type        = number
  default     = 6379
}

variable "valkey_tls" {
  description = "TLS em transito no ElastiCache."
  type        = bool
  default     = true
}

variable "valkey_usuario" {
  description = "Usuario ACL do Valkey (vazio sem ACL)."
  type        = string
  default     = ""
}

variable "valkey_senha" {
  description = "Senha ACL do Valkey (vazio sem ACL). Vai como variavel de ambiente cifrada pela KMS do Lambda."
  type        = string
  default     = ""
  sensitive   = true
}

variable "alarm_actions" {
  description = "ARNs (SNS) acionados pelos alarmes."
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------------------------------------------------
# Funcao
# ---------------------------------------------------------------------------------------------------------

variable "pacote_dir" {
  description = "Pasta montada por scripts/empacotar.py, relativa a este modulo."
  type        = string
  default     = "../../build/pacote"
}

variable "runtime" {
  description = "Runtime Python gerenciado do Lambda."
  type        = string
  default     = "python3.13"
}

variable "memoria_mb" {
  description = "Memoria da funcao (a CPU acompanha a memoria)."
  type        = number
  default     = 512
}

variable "timeout_s" {
  description = "Timeout da invocacao. Um lote com o Valkey saudavel leva milissegundos."
  type        = number
  default     = 30
}

variable "retencao_logs_dias" {
  description = "Retencao do log group da funcao."
  type        = number
  default     = 30
}

variable "valkey_timeout_ms" {
  description = "Timeout de cada comando no Valkey."
  type        = number
  default     = 200
}

variable "valkey_timeout_conexao_ms" {
  description = "Timeout de conexao com o Valkey."
  type        = number
  default     = 500
}

variable "ttl_operacao_ms" {
  description = "TTL do marcador em op:*; igual a consultas.cache.ttl da API (5 min)."
  type        = number
  default     = 300000
}

variable "ttl_custodia_ms" {
  description = "TTL do marcador em custodia-vc:*; igual a consultas.cache.ttl-custodia da API (24 h)."
  type        = number
  default     = 86400000
}

variable "metricas_namespace" {
  description = "Namespace das metricas EMF no CloudWatch."
  type        = string
  default     = "ConsultasOperacoesCredito/InvalidadorCache"
}

# ---------------------------------------------------------------------------------------------------------
# Mapeamento do stream (orcamento: dado novo visivel em ate 2 s)
# ---------------------------------------------------------------------------------------------------------

variable "batch_size" {
  description = "Registros por lote (ate 10000)."
  type        = number
  default     = 1000
}

variable "janela_lote_s" {
  description = "MaximumBatchingWindowInSeconds: espera para encher o lote. 0 entrega na hora; acima de 1 come o orcamento de 2 s."
  type        = number
  default     = 0

  validation {
    condition     = var.janela_lote_s >= 0 && var.janela_lote_s <= 1
    error_message = "janela_lote_s deve ficar entre 0 e 1 s para caber no orcamento de 2 s."
  }
}

variable "parallelization_factor" {
  description = "Lotes simultaneos por shard (1 a 10). A ordem por chave de particao (numero_operacao) e mantida."
  type        = number
  default     = 4

  validation {
    condition     = var.parallelization_factor >= 1 && var.parallelization_factor <= 10
    error_message = "parallelization_factor aceita de 1 a 10."
  }
}

variable "maximo_tentativas" {
  description = "MaximumRetryAttempts do lote antes de ir para a DLQ."
  type        = number
  default     = 5
}

variable "idade_maxima_registro_s" {
  description = "MaximumRecordAgeInSeconds. Uma invalidacao mais velha que o TTL do cache (5 min) ja nao tem efeito."
  type        = number
  default     = 600
}

variable "retencao_dlq_s" {
  description = "Retencao das mensagens na DLQ."
  type        = number
  default     = 1209600 # 14 dias
}

# ---------------------------------------------------------------------------------------------------------
# Alarmes
# ---------------------------------------------------------------------------------------------------------

variable "alarme_iterator_age_ms" {
  description = "IteratorAge maximo antes de alarmar; acima de 2 s o invalidador nao acompanha a escrita."
  type        = number
  default     = 2000
}
