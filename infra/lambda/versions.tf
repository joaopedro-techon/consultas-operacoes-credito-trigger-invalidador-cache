terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  # State remoto em S3 (configuração parcial): bucket, chave e região vêm do backend.hcl, fora do git
  # (modelo em backend.hcl.example). A chave é própria deste repositório e deste módulo (ver README).
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}
