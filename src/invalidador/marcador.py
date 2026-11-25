"""Marcador de invalidação no Valkey (ADR-0018).

Chaves, no formato que a API de consultas lê:

- ``op:{id_operacao}:{custodia}``: hash com ``versao`` (epoch ms), um campo por bloco e, quando invalidado,
  ``marcador``.
- ``custodia-vc:{id_operacao}``: hash com ``custodia``, ``versao`` e, quando invalidado, ``marcador``.

A API só substitui um hash com marcador quando lê a versão ``versao`` ou uma mais nova. Por isso, uma leitura
atrasada com o dado antigo é rejeitada.
"""

from dataclasses import dataclass

from redis import Redis
from redis.commands.core import Script
from redis.exceptions import NoScriptError

from invalidador.plano import Plano

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


@dataclass(frozen=True)
class Resultado:
    """Chaves por desfecho no Valkey."""

    gravados: list[str]
    rejeitados: list[str]
    removidos: list[str]


class Marcador:
    """Executa um plano num único pipeline: um ``EVALSHA`` por chave a marcar e um ``DEL`` por chave a apagar.

    Antes de executar, o pipeline confere se o script está no Valkey (``SCRIPT EXISTS``) e o carrega se não estiver.
    Se o script sumir entre a conferência e a execução (``SCRIPT FLUSH``, failover, outro nó), o ``NOSCRIPT`` faz
    o lote ser repetido uma vez, já com o script recarregado. Repetir é seguro porque o script e o ``DEL`` são
    idempotentes.
    """

    def __init__(self, cliente: Redis):
        self._cliente = cliente
        self._script: Script = cliente.register_script(GRAVAR_MARCADOR)

    def executar(self, plano: Plano) -> Resultado:
        if not plano:
            return Resultado([], [], [])
        marcar = list(plano.marcar)
        apagar = sorted(plano.apagar)
        try:
            respostas = self._executar(plano, marcar, apagar)
        except NoScriptError:
            respostas = self._executar(plano, marcar, apagar)
        dos_scripts = respostas[: len(marcar)]
        return Resultado(
            gravados=[chave for chave, r in zip(marcar, dos_scripts) if int(r) == GRAVADO],
            rejeitados=[chave for chave, r in zip(marcar, dos_scripts) if int(r) == REJEITADO],
            removidos=apagar,
        )

    def _executar(self, plano: Plano, marcar: list[str], apagar: list[str]) -> list:
        with self._cliente.pipeline(transaction=False) as pipeline:
            for chave in marcar:
                marcacao = plano.marcar[chave]
                self._script(keys=[chave], args=[marcacao.versao, marcacao.ttl_ms], client=pipeline)
            for chave in apagar:
                pipeline.delete(chave)
            return pipeline.execute()
