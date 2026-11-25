"""Falhas do Valkey viram retry do lote; métricas (EMF) e logs do invalidador."""

import json
import time

import pytest

from conftest import evento, registro
from invalidador import handler as modulo_handler
from invalidador.handler import handler

ID = 100000001


def documentos_emf(saida: str) -> list[dict]:
    return [json.loads(linha) for linha in saida.splitlines() if linha.startswith('{"_aws"')]


def totais(saida: str) -> dict:
    return next(d for d in documentos_emf(saida) if "TipoChave" not in d)


def por_tipo(saida: str) -> dict[str, dict]:
    return {d["TipoChave"]: d for d in documentos_emf(saida) if "TipoChave" in d}


def lote_de_tres():
    return evento(registro("INSERT", ID, "SF", sequencia="11"),
                  registro("MODIFY", ID + 1, "SF", sequencia="12"),
                  registro("REMOVE", ID + 2, "F5", sequencia="13"))


@pytest.fixture
def valkey_inalcancavel(valkey, monkeypatch):
    monkeypatch.setenv("VALKEY_HOST", "127.0.0.1")
    monkeypatch.setenv("VALKEY_PORTA", "1")  # nada escutando: conexão recusada
    modulo_handler.redefinir()


def test_valkey_inalcancavel_devolve_o_lote_inteiro_para_retry(valkey_inalcancavel, capsys, caplog):
    resposta = handler(lote_de_tres())

    assert resposta == {"batchItemFailures": [{"itemIdentifier": s} for s in ("11", "12", "13")]}
    assert totais(capsys.readouterr().out)["FalhasValkey"] == 1
    assert '"resultado": "falha_valkey"' in caplog.text


def test_valkey_lento_estoura_o_timeout_e_devolve_o_lote(valkey, monkeypatch):
    monkeypatch.setenv("VALKEY_TIMEOUT_MS", "100")
    modulo_handler.redefinir()
    handler(evento(registro("MODIFY", ID, "SF")))  # conexão já aberta e script carregado
    valkey.execute_command("CLIENT", "PAUSE", 1000, "ALL")
    try:
        inicio = time.monotonic()
        resposta = handler(evento(registro("MODIFY", ID, "SF", versao="2026-11-25T11:00:00Z", sequencia="7")))
        assert time.monotonic() - inicio < 0.9
    finally:
        valkey.execute_command("CLIENT", "UNPAUSE")

    assert resposta == {"batchItemFailures": [{"itemIdentifier": "7"}]}


def test_conexao_e_reaproveitada_entre_invocacoes(valkey):
    handler(evento(registro("MODIFY", ID, "SF")))
    conexoes = int(valkey.info("stats")["total_connections_received"])

    for i in range(5):
        handler(evento(registro("MODIFY", ID + i, "SF")))

    assert int(valkey.info("stats")["total_connections_received"]) == conexoes


def test_metricas_do_lote(valkey, capsys):
    valkey.hset(f"op:{ID + 1}:SF", mapping={"versao": "9999999999999", "OPERACAO": "dado"})  # mais novo: rejeita
    capsys.readouterr()

    handler(evento(*lote_de_tres()["Records"], registro("MODIFY", ID + 3, "OD", versao="lixo"),
                   {"eventName": "MODIFY", "dynamodb": {"Keys": {}, "SequenceNumber": "99"}}))

    saida = capsys.readouterr().out
    total = totais(saida)
    assert total["TamanhoLote"] == 5
    assert total["ChavesRemovidas"] == 3  # REMOVE: op + custodia-vc; versão inválida: op
    assert total["VersoesInvalidas"] == 1
    assert total["RegistrosInvalidos"] == 1
    assert total["FalhasValkey"] == 0
    tipos = por_tipo(saida)
    assert tipos["op"]["MarcadoresGravados"] == 1 and tipos["op"]["MarcadoresRejeitados"] == 1
    assert tipos["custodia-vc"]["MarcadoresGravados"] == 1
    assert total["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "ConsultasOperacoesCredito/InvalidadorCache"


def test_atraso_e_medido_pelo_registro_mais_antigo(valkey, capsys):
    agora = time.time()
    capsys.readouterr()

    handler(evento(registro("MODIFY", ID, "SF", criacao=agora - 1.5), registro("MODIFY", ID + 1, "SF", criacao=agora)))

    atraso = totais(capsys.readouterr().out)["AtrasoMs"]
    assert 1_500 <= atraso < 3_000


def test_logs_estruturados_so_com_identificadores(valkey, caplog):
    handler(lote_de_tres())

    linhas = [json.loads(r.getMessage()) for r in caplog.records if r.name == "invalidador"]
    assert linhas
    campos = {campo for linha in linhas for campo in linha}
    assert campos <= {"resultado", "chave", "versao", "registros", "motivo", "sequencia", "erro"}
