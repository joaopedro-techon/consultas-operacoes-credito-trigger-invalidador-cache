"""Leitura de um registro do DynamoDB Streams da tabela ``operacoes-credito``."""

from dataclasses import dataclass

from invalidador.versao import epoch_ms

CUSTODIAS = frozenset({"SF", "F5", "OD", "NSF"})


@dataclass(frozen=True)
class Registro:
    """Uma linha gravada (ou removida) de uma operação numa custódia.

    ``versao`` é ``None`` quando a nova imagem não tem ``codigo_identificador_carga`` ou ele está fora do formato.
    """

    evento: str
    id_operacao: str
    custodia: str
    versao: int | None


class RegistroInvalido(ValueError):
    """Registro sem as chaves esperadas da tabela."""


def ler(registro: dict) -> Registro:
    dados = registro["dynamodb"]
    chaves = dados["Keys"]
    id_operacao = _numero(chaves["numero_operacao"])
    custodia = chaves["custodia_expand"]["S"].split("#", 1)[0]
    if custodia not in CUSTODIAS:
        raise RegistroInvalido(f"custódia desconhecida: {custodia}")
    imagem = dados.get("NewImage") or {}
    bruto = imagem.get("codigo_identificador_carga", {}).get("S")
    return Registro(registro["eventName"], id_operacao, custodia, epoch_ms(bruto))


def _numero(valor: dict) -> str:
    # numero_operacao é N na tabela; S aceito por robustez. Sempre sem zeros à esquerda, como a API monta a chave.
    texto = valor.get("N") or valor.get("S")
    if texto is None or not texto.isdigit():
        raise RegistroInvalido("numero_operacao ausente ou não numérico")
    return str(int(texto))
