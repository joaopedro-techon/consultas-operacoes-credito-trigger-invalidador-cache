output "funcao_arn" {
  description = "ARN da Lambda invalidadora."
  value       = aws_lambda_function.this.arn
}

output "dlq_url" {
  description = "URL da DLQ (metadados dos lotes que esgotaram as tentativas)."
  value       = aws_sqs_queue.dlq.url
}

output "security_group_id" {
  description = "Security group da Lambda."
  value       = aws_security_group.funcao.id
}
