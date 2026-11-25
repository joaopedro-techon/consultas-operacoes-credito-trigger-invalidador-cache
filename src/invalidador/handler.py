"""Handler da Lambda ligada ao DynamoDB Streams (NEW_IMAGE) da tabela ``operacoes-credito``.

Lê o lote, monta o plano (a ação final de cada chave, ver ``invalidador.plano``) e o executa no Valkey num pipeline.
A resposta segue o formato ``ReportBatchItemFailures``. Se o Valkey falhar, o lote inteiro volta como falho para
o Lambda tentar de novo, porque uma invalidação perdida deixaria o dado antigo até o TTL. Como o plano é
idempotente, reprocessar um lote não tem efeito colateral.
"""

import json
import logging

from redis import Redis
from redis.backoff import ExponentialBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from invalidador.config import Config
from invalidador.marcador import Marcador
from invalidador.metricas import Metricas
from invalidador.plano import planejar
from invalidador.registro import Registro, RegistroInvalido, ler

log = logging.getLogger("invalidador")
log.setLevel(logging.INFO)

_estado: tuple[Config, Marcador] | None = None


def handler(event: dict, context=None) -> dict:
    brutos = event.get("Records", [])
    metricas = Metricas()
    metricas.contar("TamanhoLote", len(brutos))
    metricas.registrar_atraso([criacao for bruto in brutos if (criacao := _criacao(bruto)) is not None])
    try:
        return _processar(brutos, metricas)
    finally:
        metricas.emitir()


def _processar(brutos: list[dict], metricas: Metricas) -> dict:
    registros: list[Registro] = []
    for bruto in brutos:
        try:
            registros.append(ler(bruto))
        except (RegistroInvalido, KeyError) as erro:
            metricas.contar("RegistrosInvalidos")
            _logar("registro_invalido", motivo=str(erro), sequencia=_sequencia(bruto))

    try:
        config, marcador = _obter_estado()
        plano = planejar(registros, config.ttl_operacao_ms, config.ttl_custodia_ms)
        resultado = marcador.executar(plano)
    except RedisError as erro:
        metricas.contar("FalhasValkey")
        _logar("falha_valkey", erro=type(erro).__name__, registros=len(brutos))
        return {"batchItemFailures": [{"itemIdentifier": s} for bruto in brutos if (s := _sequencia(bruto))]}

    metricas.contar("VersoesInvalidas", plano.versoes_invalidas)
    metricas.contar("ChavesRemovidas", len(resultado.removidos))
    metricas.contar_chaves("MarcadoresGravados", resultado.gravados)
    metricas.contar_chaves("MarcadoresRejeitados", resultado.rejeitados)
    if plano.versoes_invalidas:
        _logar("versao_invalida", registros=plano.versoes_invalidas)
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
    # Conexão criada uma vez por ambiente de execução e reaproveitada entre invocações
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
            health_check_interval=30,
            # O padrão do redis-py repete até 3 vezes com backoff de até 10 s: com o Valkey lento, a invocação
            # ficaria presa em vez de devolver o lote. Uma repetição curta cobre uma conexão velha; o resto é retry
            # do lote pelo Lambda.
            retry=Retry(ExponentialBackoff(cap=0.05, base=0.01), 1),
        )
        _estado = (config, Marcador(cliente))
    return _estado


def _sequencia(bruto: dict) -> str | None:
    return bruto.get("dynamodb", {}).get("SequenceNumber")


def _criacao(bruto: dict) -> float | None:
    valor = bruto.get("dynamodb", {}).get("ApproximateCreationDateTime")
    return float(valor) if isinstance(valor, (int, float)) else None


def _logar(resultado: str, **campos) -> None:
    # Só identificadores e resultado: nunca texto_detalhe nem outros atributos da imagem
    log.info(json.dumps({"resultado": resultado, **campos}, ensure_ascii=False))
