"""Marcador de invalidação no Valkey (ADR-0018, ADR-0019).

Chaves, no formato que a API de consultas lê:

- ``op:{id_operacao}:{custodia}`` (versão única): hash com ``versao`` (epoch ms), um campo por bloco e, quando
  invalidado, ``marcador``.
- ``opb:{id_operacao}:{custodia}`` (versão por bloco): para cada bloco, ``{bloco}``, ``v:{bloco}`` (epoch ms) e,
  quando invalidado, ``m:{bloco}``.
- ``custodia-vc:{id_operacao}``: hash com ``custodia``, ``versao`` e, quando invalidado, ``marcador``.

A API só substitui um marcador quando lê a versão marcada ou uma mais nova. Por isso, uma leitura atrasada com o
dado antigo é rejeitada.
"""

from dataclasses import dataclass

from redis import Redis
from redis.commands.core import Script
from redis.exceptions import NoScriptError

from invalidador.plano import Alvo, Plano

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

# KEYS[1]: o hash de versão por bloco; ARGV[1]: o bloco; ARGV[2]: a versão V em epoch ms; ARGV[3]: o TTL em ms.
# v:{bloco} ausente (ou fora do formato) ou menor que V: apaga o bloco e grava v:{bloco}=V e m:{bloco}=1 (1); os
# demais blocos ficam intactos. Igual ou maior: intacto (0). O TTL só é definido quando o hash é criado: nunca
# renovado, como na API.
GRAVAR_MARCADOR_DO_BLOCO = """
local campoVersao = 'v:' .. ARGV[1]
local atual = tonumber(redis.call('HGET', KEYS[1], campoVersao))
local versao = tonumber(ARGV[2])
if atual and atual >= versao then
  return 0
end
local criado = redis.call('EXISTS', KEYS[1]) == 0
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('HSET', KEYS[1], campoVersao, ARGV[2], 'm:' .. ARGV[1], '1')
if criado then
  redis.call('PEXPIRE', KEYS[1], ARGV[3])
end
return 1
"""

GRAVADO = 1
REJEITADO = 0


@dataclass(frozen=True)
class Resultado:
    """Alvos por desfecho no Valkey."""

    gravados: list[Alvo]
    rejeitados: list[Alvo]
    removidos: list[Alvo]


class Marcador:
    """Executa um plano num único pipeline: um ``EVALSHA`` por alvo a marcar, e um ``DEL`` (chave inteira) ou
    ``HDEL`` (bloco) por alvo a apagar.

    Antes de executar, o pipeline confere se os scripts estão no Valkey (``SCRIPT EXISTS``) e os carrega se não
    estiverem. Se um script sumir entre a conferência e a execução (``SCRIPT FLUSH``, failover, outro nó), o
    ``NOSCRIPT`` faz o lote ser repetido uma vez, já com o script recarregado. Repetir é seguro porque os scripts, o
    ``DEL`` e o ``HDEL`` são idempotentes.
    """

    def __init__(self, cliente: Redis):
        self._cliente = cliente
        self._marcar_chave: Script = cliente.register_script(GRAVAR_MARCADOR)
        self._marcar_bloco: Script = cliente.register_script(GRAVAR_MARCADOR_DO_BLOCO)

    def executar(self, plano: Plano) -> Resultado:
        if not plano:
            return Resultado([], [], [])
        marcar = list(plano.marcar)
        apagar = sorted(plano.apagar, key=str)
        try:
            respostas = self._executar(plano, marcar, apagar)
        except NoScriptError:
            respostas = self._executar(plano, marcar, apagar)
        dos_scripts = respostas[: len(marcar)]
        return Resultado(
            gravados=[alvo for alvo, r in zip(marcar, dos_scripts) if int(r) == GRAVADO],
            rejeitados=[alvo for alvo, r in zip(marcar, dos_scripts) if int(r) == REJEITADO],
            removidos=apagar,
        )

    def _executar(self, plano: Plano, marcar: list[Alvo], apagar: list[Alvo]) -> list:
        with self._cliente.pipeline(transaction=False) as pipeline:
            for alvo in marcar:
                marcacao = plano.marcar[alvo]
                if alvo.bloco is None:
                    self._marcar_chave(keys=[alvo.chave], args=[marcacao.versao, marcacao.ttl_ms], client=pipeline)
                else:
                    self._marcar_bloco(keys=[alvo.chave], args=[alvo.bloco, marcacao.versao, marcacao.ttl_ms],
                                       client=pipeline)
            for alvo in apagar:
                if alvo.bloco is None:
                    pipeline.delete(alvo.chave)
                else:
                    pipeline.hdel(alvo.chave, alvo.bloco, f"v:{alvo.bloco}", f"m:{alvo.bloco}")
            return pipeline.execute()
