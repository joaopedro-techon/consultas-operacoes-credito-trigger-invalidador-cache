"""Handler da Lambda ligada ao DynamoDB Streams (NEW_IMAGE) da tabela ``operacoes-credito``.

Lê o lote, monta o plano (ação final por chave, ver ``invalidador.plano``) e o executa no Valkey num pipeline.
Resposta no formato ``ReportBatchItemFailures``.
"""

import json
import logging

from redis import Redis

from invalidador.config import Config
from invalidador.marcador import Marcador
from invalidador.plano import planejar
from invalidador.registro import Registro, RegistroInvalido, ler

log = logging.getLogger("invalidador")
log.setLevel(logging.INFO)

_estado: tuple[Config, Marcador] | None = None


def handler(event: dict, context=None) -> dict:
    config, marcador = _obter_estado()
    registros: list[Registro] = []
    for bruto in event.get("Records", []):
        try:
            registros.append(ler(bruto))
        except (RegistroInvalido, KeyError) as erro:
            _logar("registro_invalido", motivo=str(erro), sequencia=_sequencia(bruto))

    plano = planejar(registros, config.ttl_operacao_ms, config.ttl_custodia_ms)
    if plano.versoes_invalidas:
        _logar("versao_invalida", registros=plano.versoes_invalidas)
    resultado = marcador.executar(plano)
    for chave in resultado.gravados:
        _logar("marcador_gravado", chave=chave, versao=plano.marcar[chave].versao)
    for chave in resultado.rejeitados:
        _logar("marcador_rejeitado", chave=chave, versao=plano.marcar[chave].versao)
    for chave in resultado.removidos:
        _logar("chave_removida", chave=chave)
    return {"batchItemFailures": []}


def redefinir() -> None:
    """Descarta a conexão reaproveitada entre invocações (testes e troca de configuração)."""
    global _estado
    _estado = None


def _obter_estado() -> tuple[Config, Marcador]:
    global _estado
    if _estado is None:
        config = Config.do_ambiente()
        cliente = Redis(
            host=config.valkey_host,
            port=config.valkey_porta,
            ssl=config.valkey_tls,
            username=config.valkey_usuario,
            password=config.valkey_senha,
            socket_timeout=config.valkey_timeout_s,
            socket_connect_timeout=config.valkey_timeout_conexao_s,
        )
        _estado = (config, Marcador(cliente))
    return _estado


def _sequencia(bruto: dict) -> str | None:
    return bruto.get("dynamodb", {}).get("SequenceNumber")


def _logar(resultado: str, **campos) -> None:
    # Só identificadores e resultado: nunca texto_detalhe nem outros atributos da imagem
    log.info(json.dumps({"resultado": resultado, **campos}, ensure_ascii=False))
