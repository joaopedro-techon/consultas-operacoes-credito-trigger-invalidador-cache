"""INSERT invalida o cache de custódia, REMOVE apaga, versão inválida apaga; custodia:{id} nunca é tocada."""

import pytest

from conftest import evento, registro
from invalidador.handler import handler
from invalidador.versao import epoch_ms

ID = 100000001
OP = f"op:{ID}:SF"
CUSTODIA_VC = f"custodia-vc:{ID}"
COMPARTILHADA = f"custodia:{ID}"
V_ISO = "2026-11-25T10:00:00.123Z"
V = epoch_ms(V_ISO)
TTL_CUSTODIA_MS = 86_400_000


@pytest.fixture
def compartilhada(valkey):
    valkey.set(COMPARTILHADA, "F5", px=600_000)
    yield
    assert valkey.get(COMPARTILHADA) == "F5"  # contrato com a fonte primária (ADR-0017): nunca tocada


def test_insert_marca_tambem_o_cache_de_custodia_com_ttl_de_24h(valkey, compartilhada):
    handler(evento(registro("INSERT", ID, "SF")))

    assert valkey.hgetall(OP) == {"versao": str(V), "marcador": "1"}
    assert valkey.hgetall(CUSTODIA_VC) == {"versao": str(V), "marcador": "1"}
    assert TTL_CUSTODIA_MS - 5_000 < valkey.pttl(CUSTODIA_VC) <= TTL_CUSTODIA_MS


def test_insert_nao_rebaixa_cache_de_custodia_mais_novo(valkey, compartilhada):
    valkey.hset(CUSTODIA_VC, mapping={"custodia": "NSF", "versao": str(V + 1)})

    handler(evento(registro("INSERT", ID, "SF")))

    assert valkey.hgetall(CUSTODIA_VC) == {"custodia": "NSF", "versao": str(V + 1)}


def test_insert_numa_custodia_nova_invalida_a_custodia_lembrada_mais_antiga(valkey, compartilhada):
    # Migração SF → NSF: a versão na custódia de destino é sempre maior que a da origem
    valkey.hset(CUSTODIA_VC, mapping={"custodia": "SF", "versao": str(V - 1)})

    handler(evento(registro("INSERT", ID, "NSF")))

    assert valkey.hgetall(CUSTODIA_VC) == {"versao": str(V), "marcador": "1"}


def test_modify_nao_toca_no_cache_de_custodia(valkey, compartilhada):
    valkey.hset(CUSTODIA_VC, mapping={"custodia": "SF", "versao": str(V - 1)})

    handler(evento(registro("MODIFY", ID, "SF")))

    assert valkey.hgetall(CUSTODIA_VC) == {"custodia": "SF", "versao": str(V - 1)}


def test_remove_apaga_o_hash_da_operacao_e_o_cache_de_custodia(valkey, compartilhada):
    valkey.hset(OP, mapping={"versao": str(V), "OPERACAO": "dado"})
    valkey.hset(CUSTODIA_VC, mapping={"custodia": "SF", "versao": str(V)})

    handler(evento(registro("REMOVE", ID, "SF")))

    assert not valkey.exists(OP, CUSTODIA_VC)


def test_remove_depois_de_insert_no_mesmo_lote_remove(valkey, compartilhada):
    handler(evento(registro("INSERT", ID, "SF", sequencia="1"), registro("REMOVE", ID, "SF", sequencia="2")))

    assert not valkey.exists(OP, CUSTODIA_VC)


def test_insert_depois_de_remove_no_mesmo_lote_marca(valkey, compartilhada):
    handler(evento(registro("REMOVE", ID, "SF", sequencia="1"), registro("INSERT", ID, "SF", sequencia="2")))

    assert valkey.hgetall(OP) == {"versao": str(V), "marcador": "1"}
    assert valkey.hgetall(CUSTODIA_VC) == {"versao": str(V), "marcador": "1"}


def test_remove_de_uma_custodia_nao_apaga_o_hash_de_outra(valkey, compartilhada):
    valkey.hset(f"op:{ID}:NSF", mapping={"versao": str(V), "OPERACAO": "dado"})

    handler(evento(registro("REMOVE", ID, "SF")))

    assert valkey.hgetall(f"op:{ID}:NSF") == {"versao": str(V), "OPERACAO": "dado"}


@pytest.mark.parametrize("versao", [None, "lixo", "2026-11-25", "2026-11-25 10:00:00Z"])
def test_modify_com_versao_invalida_apaga_o_hash_da_operacao(valkey, compartilhada, versao, caplog):
    valkey.hset(OP, mapping={"versao": str(V), "OPERACAO": "dado"})
    valkey.hset(CUSTODIA_VC, mapping={"custodia": "SF", "versao": str(V)})

    handler(evento(registro("MODIFY", ID, "SF", versao=versao)))

    assert not valkey.exists(OP)
    assert valkey.exists(CUSTODIA_VC)  # MODIFY não toca na custódia
    assert '"resultado": "versao_invalida"' in caplog.text


def test_insert_com_versao_invalida_apaga_tambem_o_cache_de_custodia(valkey, compartilhada):
    valkey.hset(CUSTODIA_VC, mapping={"custodia": "SF", "versao": str(V)})

    handler(evento(registro("INSERT", ID, "SF", versao=None)))

    assert not valkey.exists(OP, CUSTODIA_VC)


def test_registro_com_custodia_desconhecida_e_ignorado_sem_falhar_o_lote(valkey, compartilhada):
    bruto = registro("MODIFY", ID, "XX")

    assert handler(evento(bruto, registro("MODIFY", ID, "SF"))) == {"batchItemFailures": []}
    assert valkey.keys("op:*") == [OP]


def test_logs_nao_levam_dados_da_imagem(valkey, compartilhada, caplog):
    handler(evento(registro("INSERT", ID, "SF"), registro("REMOVE", ID + 1, "F5")))

    assert "texto_detalhe" not in caplog.text
    assert "H4sI" not in caplog.text
