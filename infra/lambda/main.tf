# Invalidador do cache versionado (ADR-0018 do repositorio consultas-operacoes-credito): Lambda no DynamoDB
# Streams da tabela operacoes-credito, gravando o marcador de invalidacao no Valkey.

data "aws_iam_policy_document" "assumir" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "funcao" {
  statement {
    sid       = "LerStream"
    actions   = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"]
    resources = [var.stream_arn]
  }

  statement {
    sid       = "EnviarParaDlq"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.funcao.arn}:*"]
  }
}

resource "aws_iam_role" "funcao" {
  name               = var.nome
  assume_role_policy = data.aws_iam_policy_document.assumir.json
}

resource "aws_iam_role_policy" "funcao" {
  name   = "${var.nome}-stream-dlq-logs"
  role   = aws_iam_role.funcao.id
  policy = data.aws_iam_policy_document.funcao.json
}

# Interfaces de rede na VPC (CreateNetworkInterface e afins), necessarias para alcancar o Valkey
resource "aws_iam_role_policy_attachment" "vpc" {
  role       = aws_iam_role.funcao.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "funcao" {
  name              = "/aws/lambda/${var.nome}"
  retention_in_days = var.retencao_logs_dias
}

# ---------------------------------------------------------------------------------------------------------
# Rede: a Lambda so sai para o Valkey
# ---------------------------------------------------------------------------------------------------------

resource "aws_security_group" "funcao" {
  name        = var.nome
  description = "Invalidador do cache: saida so para o Valkey"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_egress_rule" "para_valkey" {
  security_group_id            = aws_security_group.funcao.id
  referenced_security_group_id = var.valkey_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = var.valkey_porta
  to_port                      = var.valkey_porta
  description                  = "Valkey"
}

resource "aws_vpc_security_group_ingress_rule" "valkey_vindo_da_funcao" {
  security_group_id            = var.valkey_security_group_id
  referenced_security_group_id = aws_security_group.funcao.id
  ip_protocol                  = "tcp"
  from_port                    = var.valkey_porta
  to_port                      = var.valkey_porta
  description                  = "Invalidador do cache (${var.nome})"
}

# ---------------------------------------------------------------------------------------------------------
# Funcao
# ---------------------------------------------------------------------------------------------------------

data "archive_file" "pacote" {
  type        = "zip"
  source_dir  = "${path.module}/${var.pacote_dir}"
  output_path = "${path.module}/.terraform/pacote.zip"
}

resource "aws_lambda_function" "this" {
  function_name    = var.nome
  role             = aws_iam_role.funcao.arn
  runtime          = var.runtime
  architectures    = ["arm64"]
  handler          = "invalidador.handler.handler"
  filename         = data.archive_file.pacote.output_path
  source_code_hash = data.archive_file.pacote.output_base64sha256
  memory_size      = var.memoria_mb
  timeout          = var.timeout_s

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [aws_security_group.funcao.id]
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.funcao.name
  }

  environment {
    variables = {
      VALKEY_HOST               = var.valkey_host
      VALKEY_PORTA              = tostring(var.valkey_porta)
      VALKEY_TLS                = tostring(var.valkey_tls)
      VALKEY_USUARIO            = var.valkey_usuario
      VALKEY_SENHA              = var.valkey_senha
      VALKEY_TIMEOUT_MS         = tostring(var.valkey_timeout_ms)
      VALKEY_TIMEOUT_CONEXAO_MS = tostring(var.valkey_timeout_conexao_ms)
      CACHE_TTL_OPERACAO_MS     = tostring(var.ttl_operacao_ms)
      CACHE_TTL_CUSTODIA_MS     = tostring(var.ttl_custodia_ms)
      METRICAS_NAMESPACE        = var.metricas_namespace
    }
  }

  depends_on = [aws_iam_role_policy.funcao, aws_iam_role_policy_attachment.vpc]
}

# ---------------------------------------------------------------------------------------------------------
# Stream → Lambda, com retry do lote e DLQ
# ---------------------------------------------------------------------------------------------------------

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.nome}-dlq"
  message_retention_seconds = var.retencao_dlq_s
  sqs_managed_sse_enabled   = true
}

resource "aws_lambda_event_source_mapping" "stream" {
  event_source_arn  = var.stream_arn
  function_name     = aws_lambda_function.this.arn
  starting_position = "LATEST"

  batch_size                         = var.batch_size
  maximum_batching_window_in_seconds = var.janela_lote_s
  parallelization_factor             = var.parallelization_factor

  # O handler devolve o lote inteiro em batchItemFailures quando o Valkey falha
  function_response_types        = ["ReportBatchItemFailures"]
  bisect_batch_on_function_error = true
  maximum_retry_attempts         = var.maximo_tentativas
  maximum_record_age_in_seconds  = var.idade_maxima_registro_s

  # A DLQ recebe os metadados do lote (shard e faixa de sequencia), nao os registros: e diagnostica.
  # Uma invalidacao perdida fica limitada pelo TTL de 5 min do cache.
  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.dlq.arn
    }
  }
}

# ---------------------------------------------------------------------------------------------------------
# Alarmes
# ---------------------------------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "iterator_age" {
  alarm_name          = "${var.nome}-iterator-age"
  alarm_description   = "Invalidador atrasado em relacao a escrita no DynamoDB (orcamento de 2 s). Persistindo: reavaliar ParallelizationFactor ou o estagio SQS/ECS (ADR-0018)."
  namespace           = "AWS/Lambda"
  metric_name         = "IteratorAge"
  dimensions          = { FunctionName = aws_lambda_function.this.function_name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = var.alarme_iterator_age_ms
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  ok_actions          = var.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "erros" {
  alarm_name          = "${var.nome}-erros"
  alarm_description   = "Invocacoes do invalidador com erro nao tratado."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.this.function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  ok_actions          = var.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "falhas_valkey" {
  alarm_name          = "${var.nome}-falhas-valkey"
  alarm_description   = "Lotes devolvidos para retry porque o Valkey falhou (metrica EMF FalhasValkey)."
  namespace           = var.metricas_namespace
  metric_name         = "FalhasValkey"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 2
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  ok_actions          = var.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "dlq" {
  alarm_name          = "${var.nome}-dlq"
  alarm_description   = "Lotes que esgotaram as tentativas: invalidacoes perdidas (dado antigo ate o TTL de 5 min)."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_actions
  ok_actions          = var.alarm_actions
}
