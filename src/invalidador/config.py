"""Configuração por variáveis de ambiente. Os TTLs precisam ser os mesmos da API de consultas."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    valkey_host: str
    valkey_porta: int
    valkey_tls: bool
    valkey_usuario: str | None
    valkey_senha: str | None
    valkey_timeout_s: float
    valkey_timeout_conexao_s: float
    # consultas.cache.ttl da API (5 min)
    ttl_operacao_ms: int
    # consultas.cache.ttl-custodia da API (24 h)
    ttl_custodia_ms: int

    @staticmethod
    def do_ambiente() -> "Config":
        env = os.environ
        return Config(
            valkey_host=env.get("VALKEY_HOST", "localhost"),
            valkey_porta=int(env.get("VALKEY_PORTA", "6379")),
            valkey_tls=env.get("VALKEY_TLS", "false").lower() == "true",
            valkey_usuario=env.get("VALKEY_USUARIO") or None,
            valkey_senha=env.get("VALKEY_SENHA") or None,
            valkey_timeout_s=float(env.get("VALKEY_TIMEOUT_MS", "200")) / 1000,
            valkey_timeout_conexao_s=float(env.get("VALKEY_TIMEOUT_CONEXAO_MS", "500")) / 1000,
            ttl_operacao_ms=int(env.get("CACHE_TTL_OPERACAO_MS", "300000")),
            ttl_custodia_ms=int(env.get("CACHE_TTL_CUSTODIA_MS", "86400000")),
        )
