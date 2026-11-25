import pytest
from redis import Redis
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from invalidador import handler as modulo_handler

IMAGEM_VALKEY = "valkey/valkey:9.0.8-alpine"


@pytest.fixture(scope="session")
def container_valkey():
    container = (
        DockerContainer(IMAGEM_VALKEY)
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with container:
        yield container


@pytest.fixture
def valkey(container_valkey, monkeypatch) -> Redis:
    """Valkey limpo, com o handler apontando para ele."""
    host = container_valkey.get_container_host_ip()
    porta = container_valkey.get_exposed_port(6379)
    monkeypatch.setenv("VALKEY_HOST", host)
    monkeypatch.setenv("VALKEY_PORTA", str(porta))
    modulo_handler.redefinir()
    cliente = Redis(host=host, port=int(porta), decode_responses=True)
    cliente.flushall()
    cliente.script_flush()
    yield cliente
    modulo_handler.redefinir()
    cliente.close()


def evento(*registros: dict) -> dict:
    return {"Records": list(registros)}


def registro(evento_nome: str, id_operacao: int, custodia: str, bloco: str = "OPERACAO",
             versao: str | None = "2026-11-25T10:00:00.123Z", sequencia: str = "100") -> dict:
    chaves = {
        "numero_operacao": {"N": str(id_operacao)},
        "custodia_expand": {"S": f"{custodia}#EXPAND#{bloco}"},
    }
    dados = {"Keys": chaves, "SequenceNumber": sequencia, "StreamViewType": "NEW_IMAGE"}
    if evento_nome != "REMOVE":
        imagem = dict(chaves)
        imagem["texto_detalhe"] = {"B": "H4sIAAAAAAAA/6uuBQBDv6ajAgAAAA=="}
        if versao is not None:
            imagem["codigo_identificador_carga"] = {"S": versao}
        dados["NewImage"] = imagem
    return {"eventName": evento_nome, "eventSource": "aws:dynamodb", "dynamodb": dados}
