"""Leitura de um registro do DynamoDB Streams da tabela ``operacoes-credito``."""

from dataclasses import dataclass

from invalidador.versao import epoch_ms

CUSTODIAS = frozenset({"SF", "F5", "OD", "NSF"})
INFIXO_SK = "#EXPAND#"


@dataclass(frozen=True)
class Registro:
    """Uma linha gravada (ou removida) de uma operação numa custódia: um bloco.

    ``bloco`` é o nome canônico do bloco, em minúsculas, como o campo no hash da API (``parcelas``, ``operacao``).
    ``versao`` é ``None`` quando a nova imagem não tem ``codigo_identificador_carga`` ou ele está fora do formato.
    """

    evento: str
    id_operacao: str
    custodia: str
    bloco: str
    versao: int | None


class RegistroInvalido(ValueError):
    """Registro sem as chaves esperadas da tabela."""


def ler(registro: dict) -> Registro:
    dados = registro["dynamodb"]
    chaves = dados["Keys"]
    id_operacao = _numero(chaves["numero_operacao"])
    custodia, separador, bloco = chaves["custodia_expand"]["S"].partition(INFIXO_SK)
    if custodia not in CUSTODIAS:
        raise RegistroInvalido(f"custódia desconhecida: {custodia}")
    if not separador or not bloco:
        raise RegistroInvalido("custodia_expand sem <CUSTODIA>#EXPAND#<BLOCO>")
    imagem = dados.get("NewImage") or {}
    bruto = imagem.get("codigo_identificador_carga", {}).get("S")
    return Registro(registro["eventName"], id_operacao, custodia, bloco.lower(), epoch_ms(bruto))


def _numero(valor: dict) -> str:
    # numero_operacao é N na tabela; S aceito por robustez. Sempre sem zeros à esquerda, como a API monta a chave.
    texto = valor.get("N") or valor.get("S")
    if texto is None or not texto.isdigit():
        raise RegistroInvalido("numero_operacao ausente ou não numérico")
    return str(int(texto))
