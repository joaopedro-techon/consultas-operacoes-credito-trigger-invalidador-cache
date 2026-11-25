"""Lotes do Streams: uma gravação por chave, na maior versão, num pipeline."""

import pytest
from redis.client import Pipeline

from conftest import evento, registro
from invalidador.handler import handler
from invalidador.versao import epoch_ms

ID = 100000001
BLOCOS = ["OPERACAO", "PARCELAS", "AMORTIZACOES", "SALDO", "GARANTIAS", "ENCARGOS", "TAXAS", "EVENTOS", "CONTRATO"]


def execucoes_do_script(valkey) -> int:
    estatisticas = valkey.info("commandstats")
    return sum(estatisticas.get(f"cmdstat_{comando}", {}).get("calls", 0) for comando in ("evalsha", "eval"))


def test_nove_linhas_da_mesma_transacao_viram_uma_gravacao(valkey):
    lote = evento(*(registro("MODIFY", ID, "SF", bloco=bloco, sequencia=str(i)) for i, bloco in enumerate(BLOCOS)))
    valkey.config_resetstat()

    handler(lote)

    assert execucoes_do_script(valkey) == 1
    assert valkey.hget(f"op:{ID}:SF", "marcador") == "1"


@pytest.mark.parametrize("ordem", [["10:00:00.100", "10:00:00.200"], ["10:00:00.200", "10:00:00.100"]])
def test_mesma_chave_com_versoes_diferentes_vence_a_maior(valkey, ordem):
    lote = evento(*(registro("MODIFY", ID, "SF", versao=f"2026-11-25T{hora}Z") for hora in ordem))

    handler(lote)

    assert valkey.hget(f"op:{ID}:SF", "versao") == str(epoch_ms("2026-11-25T10:00:00.200Z"))


def test_varias_operacoes_e_custodias_no_mesmo_lote(valkey):
    chaves = [(ID, "SF"), (ID, "NSF"), (ID + 1, "F5"), (ID + 2, "OD")]
    valkey.config_resetstat()

    handler(evento(*(registro("INSERT", id_operacao, custodia) for id_operacao, custodia in chaves)))

    assert execucoes_do_script(valkey) == len(chaves)
    for id_operacao, custodia in chaves:
        assert valkey.hgetall(f"op:{id_operacao}:{custodia}")["marcador"] == "1"


def test_script_apagado_do_valkey_entre_invocacoes_e_recarregado(valkey):
    handler(evento(registro("MODIFY", ID, "SF", versao="2026-11-25T10:00:00.100Z")))
    valkey.script_flush()

    handler(evento(registro("MODIFY", ID, "SF", versao="2026-11-25T10:00:00.200Z")))

    assert valkey.hget(f"op:{ID}:SF", "versao") == str(epoch_ms("2026-11-25T10:00:00.200Z"))


def test_script_apagado_durante_o_lote_faz_o_lote_ser_repetido(valkey, monkeypatch):
    # Simula um SCRIPT FLUSH (ou failover) entre a conferência do script e a execução do pipeline, só na 1ª vez
    original = Pipeline.load_scripts
    vezes = []

    def carregar_e_apagar(self):
        original(self)
        if not vezes:
            vezes.append(1)
            valkey.script_flush()

    monkeypatch.setattr(Pipeline, "load_scripts", carregar_e_apagar)

    resposta = handler(evento(registro("MODIFY", ID, "SF"), registro("MODIFY", ID + 1, "SF")))

    assert resposta == {"batchItemFailures": []}
    assert valkey.hget(f"op:{ID}:SF", "marcador") == "1"
    assert valkey.hget(f"op:{ID + 1}:SF", "marcador") == "1"


def test_reprocessar_o_mesmo_lote_e_idempotente(valkey):
    lote = evento(*(registro("MODIFY", ID + i, "SF", bloco=bloco) for i, bloco in enumerate(BLOCOS)))
    handler(lote)
    antes = {chave: (valkey.hgetall(chave), valkey.pttl(chave)) for chave in valkey.keys("op:*")}

    handler(lote)

    depois = {chave: (valkey.hgetall(chave), valkey.pttl(chave)) for chave in valkey.keys("op:*")}
    assert {chave: dados for chave, (dados, _) in depois.items()} == {chave: dados for chave, (dados, _) in antes.items()}
    for chave, (_, ttl) in depois.items():
        assert ttl <= antes[chave][1]  # TTL não renovado


def test_lote_vazio_nao_chama_o_valkey(valkey):
    valkey.config_resetstat()

    assert handler(evento()) == {"batchItemFailures": []}
    assert execucoes_do_script(valkey) == 0
