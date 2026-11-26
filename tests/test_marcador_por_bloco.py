"""Versão por bloco (ADR-0019): cada linha invalida só o seu bloco em opb:{id}:{custodia}, e só a linha do bloco
OPERACAO mexe no cache de custódia."""

from pathlib import Path

import pytest

from conftest import evento, registro
from invalidador.handler import handler
from invalidador.versao import epoch_ms

ID = 100000001
OPB = f"opb:{ID}:SF"
CUSTODIA_VC = f"custodia-vc:{ID}"
V = epoch_ms("2026-11-25T10:00:00.123Z")
TTL_MS = 300_000


def test_modify_de_um_bloco_marca_so_esse_bloco_e_mantem_os_demais(valkey):
    # Pagamento de parcela: a originação, em cache numa versão anterior, continua servindo
    valkey.hset(OPB, mapping={"parcelas": "antigo", "v:parcelas": str(V - 1),
                              "originacao": "o", "v:originacao": str(V - 100)})
    valkey.pexpire(OPB, 10_000)

    handler(evento(registro("MODIFY", ID, "SF", bloco="PARCELAS")))

    assert valkey.hgetall(OPB) == {"v:parcelas": str(V), "m:parcelas": "1",
                                   "originacao": "o", "v:originacao": str(V - 100)}
    assert valkey.pttl(OPB) <= 10_000  # TTL não renovado


def test_hash_por_bloco_ausente_e_criado_so_com_o_marcador_e_ttl(valkey):
    handler(evento(registro("MODIFY", ID, "SF", bloco="SALDO")))

    assert valkey.hgetall(OPB) == {"v:saldo": str(V), "m:saldo": "1"}
    assert TTL_MS - 5_000 < valkey.pttl(OPB) <= TTL_MS


@pytest.mark.parametrize("versao_no_cache", [V, V + 1])
def test_bloco_com_versao_igual_ou_maior_fica_intacto(valkey, versao_no_cache):
    valkey.hset(OPB, mapping={"saldo": "s", "v:saldo": str(versao_no_cache)})

    handler(evento(registro("MODIFY", ID, "SF", bloco="SALDO")))

    assert valkey.hgetall(OPB) == {"saldo": "s", "v:saldo": str(versao_no_cache)}


def test_remove_de_um_bloco_apaga_so_esse_bloco_e_nao_toca_na_custodia(valkey):
    valkey.hset(OPB, mapping={"controles_iof": "c", "v:controles_iof": str(V), "operacao": "o", "v:operacao": str(V)})
    valkey.hset(CUSTODIA_VC, mapping={"custodia": "SF", "versao": str(V)})

    handler(evento(registro("REMOVE", ID, "SF", bloco="CONTROLES_IOF")))

    assert valkey.hgetall(OPB) == {"operacao": "o", "v:operacao": str(V)}
    assert valkey.hgetall(CUSTODIA_VC) == {"custodia": "SF", "versao": str(V)}


def test_insert_de_bloco_novo_que_nao_e_operacao_nao_marca_a_custodia(valkey):
    # Primeiro controle de IOF de uma operação que já está na SF: a custódia vencedora não muda
    valkey.hset(CUSTODIA_VC, mapping={"custodia": "SF", "versao": str(V - 1)})

    handler(evento(registro("INSERT", ID, "SF", bloco="CONTROLES_IOF")))

    assert valkey.hgetall(CUSTODIA_VC) == {"custodia": "SF", "versao": str(V - 1)}


def test_insert_do_bloco_operacao_marca_a_custodia(valkey):
    valkey.hset(CUSTODIA_VC, mapping={"custodia": "SF", "versao": str(V - 1)})

    handler(evento(registro("INSERT", ID, "NSF", bloco="OPERACAO")))

    assert valkey.hgetall(CUSTODIA_VC) == {"versao": str(V), "marcador": "1"}


def test_versao_invalida_apaga_so_o_bloco(valkey):
    valkey.hset(OPB, mapping={"saldo": "s", "v:saldo": str(V), "originacao": "o", "v:originacao": str(V)})

    handler(evento(registro("MODIFY", ID, "SF", bloco="SALDO", versao="lixo")))

    assert valkey.hgetall(OPB) == {"originacao": "o", "v:originacao": str(V)}


def test_mesmo_bloco_com_versoes_diferentes_no_lote_vence_a_maior(valkey):
    handler(evento(registro("MODIFY", ID, "SF", bloco="SALDO", versao="2026-11-25T10:00:00.200Z", sequencia="1"),
                   registro("MODIFY", ID, "SF", bloco="SALDO", versao="2026-11-25T10:00:00.100Z", sequencia="2")))

    assert valkey.hget(OPB, "v:saldo") == str(epoch_ms("2026-11-25T10:00:00.200Z"))


# Contrato com a API: depois do marcador do bloco, uma leitura atrasada (versão menor) não regrava o dado antigo
# daquele bloco; uma leitura na versão marcada ou mais nova substitui o marcador pelo dado.
SCRIPT_API = (Path(__file__).parent / "fixtures" / "gravar_por_bloco_api.lua").read_text(encoding="utf-8")


def gravar_pela_api(valkey, *bloco_versao_valor) -> int:
    return valkey.eval(SCRIPT_API, 1, OPB, TTL_MS, *bloco_versao_valor)


def test_contrato_leitura_atrasada_da_api_e_rejeitada_so_no_bloco_marcado(valkey):
    handler(evento(registro("MODIFY", ID, "SF", bloco="PARCELAS")))

    assert gravar_pela_api(valkey, "parcelas", V - 1, "antigo", "originacao", V - 100, "o") == 1

    assert valkey.hgetall(OPB) == {"v:parcelas": str(V), "m:parcelas": "1",
                                   "originacao": "o", "v:originacao": str(V - 100)}


@pytest.mark.parametrize("versao_lida", [V, V + 1])
def test_contrato_leitura_na_versao_do_marcador_ou_mais_nova_substitui(valkey, versao_lida):
    handler(evento(registro("MODIFY", ID, "SF", bloco="PARCELAS")))

    assert gravar_pela_api(valkey, "parcelas", versao_lida, "novo") == 1

    assert valkey.hgetall(OPB) == {"parcelas": "novo", "v:parcelas": str(versao_lida)}


def test_contrato_bloco_ja_na_versao_v_nao_e_apagado_pelo_marcador_atrasado(valkey):
    gravar_pela_api(valkey, "parcelas", V, "novo")

    handler(evento(registro("MODIFY", ID, "SF", bloco="PARCELAS")))

    assert valkey.hgetall(OPB) == {"parcelas": "novo", "v:parcelas": str(V)}
