"""Marcador de invalidação no Valkey (ADR-0018).

Chaves (formato que a API de consultas lê):

- ``op:{id_operacao}:{custodia}``: hash com ``versao`` (epoch ms), um campo por bloco e, quando invalidado,
  ``marcador``. A API só substitui um hash com marcador por uma leitura com versão >= ``versao``, então uma
  leitura atrasada com o dado antigo é rejeitada.
"""

from redis import Redis
from redis.commands.core import Script

# KEYS[1]: o hash; ARGV[1]: a versão V em epoch ms; ARGV[2]: o TTL em ms.
# Versão no cache ausente (ou fora do formato) ou menor que V: o hash vira só {versao=V, marcador=1}, com TTL (1).
# Igual ou maior: intacto (0). Igual é a própria versão V, já em cache com os dados ou já marcada.
GRAVAR_MARCADOR = """
local atual = tonumber(redis.call('HGET', KEYS[1], 'versao'))
local versao = tonumber(ARGV[1])
if atual and atual >= versao then
  return 0
end
redis.call('DEL', KEYS[1])
redis.call('HSET', KEYS[1], 'versao', ARGV[1], 'marcador', '1')
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return 1
"""

GRAVADO = 1
REJEITADO = 0


def chave_operacao(id_operacao: str, custodia: str) -> str:
    return f"op:{id_operacao}:{custodia}"


class Marcador:
    """Grava marcadores com ``EVALSHA`` (o cliente cai para ``EVAL`` em ``NOSCRIPT``)."""

    def __init__(self, cliente: Redis, ttl_ms: int):
        self._script: Script = cliente.register_script(GRAVAR_MARCADOR)
        self._ttl_ms = ttl_ms

    def gravar(self, chave: str, versao: int) -> int:
        return int(self._script(keys=[chave], args=[versao, self._ttl_ms]))
