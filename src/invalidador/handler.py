"""Handler da Lambda ligada ao DynamoDB Streams (NEW_IMAGE) da tabela ``operacoes-credito``.

Para cada operação gravada numa custódia na versão V, grava o marcador de invalidação em
``op:{id_operacao}:{custodia}``. Resposta no formato ``ReportBatchItemFailures``.
"""

import json
import logging

from redis import Redis

from invalidador.config import Config
from invalidador.marcador import GRAVADO, Marcador, chave_operacao
from invalidador.registro import RegistroInvalido, ler

log = logging.getLogger("invalidador")
log.setLevel(logging.INFO)

_marcador: Marcador | None = None


def handler(event: dict, context=None) -> dict:
    marcador = _obter_marcador()
    for bruto in event.get("Records", []):
        try:
            registro = ler(bruto)
        except (RegistroInvalido, KeyError) as erro:
            _logar("registro_invalido", motivo=str(erro), sequencia=_sequencia(bruto))
            continue
        if registro.evento not in ("INSERT", "MODIFY"):
            _logar("evento_ignorado", evento=registro.evento, id_operacao=registro.id_operacao,
                   custodia=registro.custodia)
            continue
        if registro.versao is None:
            _logar("versao_invalida", id_operacao=registro.id_operacao, custodia=registro.custodia)
            continue
        resultado = marcador.gravar(chave_operacao(registro.id_operacao, registro.custodia), registro.versao)
        _logar("marcador_gravado" if resultado == GRAVADO else "marcador_rejeitado",
               id_operacao=registro.id_operacao, custodia=registro.custodia, versao=registro.versao)
    return {"batchItemFailures": []}


def redefinir() -> None:
    """Descarta a conexão reaproveitada entre invocações (testes e troca de configuração)."""
    global _marcador
    _marcador = None


def _obter_marcador() -> Marcador:
    global _marcador
    if _marcador is None:
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
        _marcador = Marcador(cliente, config.ttl_operacao_ms)
    return _marcador


def _sequencia(bruto: dict) -> str | None:
    return bruto.get("dynamodb", {}).get("SequenceNumber")


def _logar(resultado: str, **campos) -> None:
    # Só identificadores e resultado: nunca texto_detalhe nem outros atributos da imagem
    log.info(json.dumps({"resultado": resultado, **campos}, ensure_ascii=False))
