"""Uma atualização de uma operação numa custódia invalida o hash op:{id}:{custodia} com o marcador da versão."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from conftest import evento, registro
from invalidador.handler import handler

ID = 100000001
CHAVE = f"op:{ID}:SF"
TTL_MS = 300_000


def ms(texto: str) -> int:
    return int(datetime.fromisoformat(texto).astimezone(UTC).timestamp() * 1000)


V = ms("2026-11-25T10:00:00.123+00:00")


def test_modify_grava_marcador_com_versao_e_ttl(valkey):
    resposta = handler(evento(registro("MODIFY", ID, "SF")))

    assert resposta == {"batchItemFailures": []}
    assert valkey.hgetall(CHAVE) == {"versao": str(V), "marcador": "1"}
    assert TTL_MS - 5_000 < valkey.pttl(CHAVE) <= TTL_MS


def test_insert_tambem_marca_o_hash_da_operacao(valkey):
    handler(evento(registro("INSERT", ID, "NSF")))

    assert valkey.hgetall(f"op:{ID}:NSF") == {"versao": str(V), "marcador": "1"}


def test_versao_menor_no_cache_vira_marcador_sem_os_blocos(valkey):
    valkey.hset(CHAVE, mapping={"versao": str(V - 1), "PARCELAS": "antigo", "OPERACAO": "antigo"})
    valkey.pexpire(CHAVE, 10_000)

    handler(evento(registro("MODIFY", ID, "SF", bloco="PARCELAS")))

    assert valkey.hgetall(CHAVE) == {"versao": str(V), "marcador": "1"}
    assert valkey.pttl(CHAVE) > 10_000


@pytest.mark.parametrize("versao_no_cache", [V, V + 1])
def test_versao_igual_ou_maior_no_cache_fica_intacta(valkey, versao_no_cache):
    valkey.hset(CHAVE, mapping={"versao": str(versao_no_cache), "OPERACAO": "dado"})
    valkey.pexpire(CHAVE, 10_000)

    handler(evento(registro("MODIFY", ID, "SF")))

    assert valkey.hgetall(CHAVE) == {"versao": str(versao_no_cache), "OPERACAO": "dado"}
    assert valkey.pttl(CHAVE) <= 10_000


def test_versao_fora_do_formato_no_cache_e_substituida(valkey):
    valkey.hset(CHAVE, mapping={"versao": "lixo", "OPERACAO": "dado"})

    handler(evento(registro("MODIFY", ID, "SF")))

    assert valkey.hgetall(CHAVE) == {"versao": str(V), "marcador": "1"}


@pytest.mark.parametrize(("iso", "esperado"), [
    ("2026-11-25T10:00:00.123", "2026-11-25T10:00:00.123+00:00"),       # sem fuso: UTC
    ("2026-11-25T07:00:00.123-03:00", "2026-11-25T10:00:00.123+00:00"),  # com fuso: respeitado
    ("2026-11-25T10:00:00.123987Z", "2026-11-25T10:00:00.123+00:00"),    # micro truncado para ms
    ("2026-11-25T10:00:00Z", "2026-11-25T10:00:00+00:00"),
])
def test_versao_iso_vira_epoch_ms_como_na_api(valkey, iso, esperado):
    handler(evento(registro("MODIFY", ID, "SF", versao=iso)))

    assert valkey.hget(CHAVE, "versao") == str(ms(esperado))


def test_numero_da_operacao_vira_a_mesma_chave_da_api(valkey):
    bruto = registro("MODIFY", ID, "SF")
    bruto["dynamodb"]["Keys"]["numero_operacao"] = {"N": "000100000001"}

    handler(evento(bruto))

    assert valkey.exists(CHAVE)


def test_chave_compartilhada_de_custodia_nao_e_tocada(valkey):
    valkey.set(f"custodia:{ID}", "F5", px=60_000)

    handler(evento(registro("MODIFY", ID, "SF")))

    assert valkey.get(f"custodia:{ID}") == "F5"


# Contrato com a API: depois do marcador, uma leitura atrasada (versão menor) não regrava o dado antigo;
# uma leitura na versão V ou mais nova substitui o marcador pelos dados.
SCRIPT_API = (Path(__file__).parent / "fixtures" / "gravar_versionado_api.lua").read_text(encoding="utf-8")


def gravar_pela_api(valkey, versao: int, **blocos: str) -> int:
    pares = [valor for campo_valor in blocos.items() for valor in campo_valor]
    return valkey.eval(SCRIPT_API, 1, CHAVE, versao, TTL_MS, *pares)


def test_contrato_leitura_atrasada_da_api_e_rejeitada_depois_do_marcador(valkey):
    handler(evento(registro("MODIFY", ID, "SF")))

    assert gravar_pela_api(valkey, V - 1, OPERACAO="antigo") == 0
    assert valkey.hgetall(CHAVE) == {"versao": str(V), "marcador": "1"}


@pytest.mark.parametrize("versao_lida", [V, V + 1])
def test_contrato_leitura_na_versao_do_marcador_ou_mais_nova_substitui(valkey, versao_lida):
    handler(evento(registro("MODIFY", ID, "SF")))

    assert gravar_pela_api(valkey, versao_lida, OPERACAO="novo") == 1
    assert valkey.hgetall(CHAVE) == {"versao": str(versao_lida), "OPERACAO": "novo"}


def test_contrato_api_ja_na_versao_v_nao_e_apagada_pelo_marcador_atrasado(valkey):
    gravar_pela_api(valkey, V, OPERACAO="novo")

    handler(evento(registro("MODIFY", ID, "SF")))

    assert valkey.hgetall(CHAVE) == {"versao": str(V), "OPERACAO": "novo"}
