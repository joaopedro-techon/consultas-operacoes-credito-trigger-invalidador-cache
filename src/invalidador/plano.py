"""O que um lote do Streams faz no Valkey: a ação final de cada alvo, na ordem do shard.

O invalidador não sabe qual regra de versão dos blocos a API usa (ADR-0019) e marca sempre os dois formatos do cache
de blocos:

- ``op:{id}:{custodia}`` (versão única, ADR-0018): INSERT/MODIFY com versão V marca o hash inteiro (TTL do cache de
  blocos), na maior V do lote; REMOVE apaga o hash.
- ``opb:{id}:{custodia}`` (versão por bloco, ADR-0019): o alvo é o bloco da linha. INSERT/MODIFY com V marca só esse
  bloco, na maior V do lote; REMOVE apaga só esse bloco.
- ``custodia-vc:{id}``: só a linha do bloco ``OPERACAO`` mexe nela. INSERT com V grava o marcador (TTL do cache de
  custódia) e REMOVE apaga a chave. O INSERT do bloco ``OPERACAO`` é o evento que pode mudar a custódia vencedora;
  numa migração, os escritores gravam todos os blocos no destino, com versão maior que a da origem.
- Versão ausente ou fora do formato: apaga os alvos que o evento marcaria, para não deixar o cache desatualizado.
- Um evento posterior no mesmo alvo substitui a ação anterior; entre marcações, vence a maior versão.

A chave compartilhada ``custodia:{id}`` (contrato com a fonte primária, ADR-0017) nunca entra no plano.
"""

from dataclasses import dataclass, field

from invalidador.registro import Registro

BLOCO_OPERACAO = "operacao"


def chave_operacao(id_operacao: str, custodia: str) -> str:
    return f"op:{id_operacao}:{custodia}"


def chave_por_bloco(id_operacao: str, custodia: str) -> str:
    return f"opb:{id_operacao}:{custodia}"


def chave_custodia(id_operacao: str) -> str:
    return f"custodia-vc:{id_operacao}"


@dataclass(frozen=True)
class Alvo:
    """Uma chave inteira ou, no hash de versão por bloco, um bloco dela."""

    chave: str
    bloco: str | None = None

    def __str__(self) -> str:
        return self.chave if self.bloco is None else f"{self.chave}#{self.bloco}"


@dataclass(frozen=True)
class Marcacao:
    versao: int
    ttl_ms: int


@dataclass
class Plano:
    marcar: dict[Alvo, Marcacao] = field(default_factory=dict)
    apagar: set[Alvo] = field(default_factory=set)
    versoes_invalidas: int = 0

    def __bool__(self) -> bool:
        return bool(self.marcar or self.apagar)


def planejar(registros: list[Registro], ttl_operacao_ms: int, ttl_custodia_ms: int) -> Plano:
    plano = Plano()
    for registro in registros:
        if registro.evento not in ("INSERT", "MODIFY", "REMOVE"):
            continue
        alvos = [
            (Alvo(chave_operacao(registro.id_operacao, registro.custodia)), ttl_operacao_ms),
            (Alvo(chave_por_bloco(registro.id_operacao, registro.custodia), registro.bloco), ttl_operacao_ms),
        ]
        if registro.bloco == BLOCO_OPERACAO and registro.evento in ("INSERT", "REMOVE"):
            alvos.append((Alvo(chave_custodia(registro.id_operacao)), ttl_custodia_ms))
        if registro.evento == "REMOVE" or registro.versao is None:
            if registro.evento != "REMOVE":
                plano.versoes_invalidas += 1
            for alvo, _ in alvos:
                plano.marcar.pop(alvo, None)
                plano.apagar.add(alvo)
            continue
        for alvo, ttl in alvos:
            anterior = plano.marcar.get(alvo)
            if anterior is None or registro.versao > anterior.versao:
                plano.marcar[alvo] = Marcacao(registro.versao, ttl)
            plano.apagar.discard(alvo)
    return plano
