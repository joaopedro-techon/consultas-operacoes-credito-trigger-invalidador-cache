"""O que um lote do Streams faz no Valkey: a ação final de cada chave, na ordem do shard.

- INSERT/MODIFY com versão V: marcador em ``op:{id}:{custodia}`` (TTL do cache de blocos), na maior V do lote.
- INSERT com V: também o marcador em ``custodia-vc:{id}`` (TTL do cache de custódia). O INSERT é o evento que pode
  mudar a custódia vencedora; numa migração, a versão na custódia de destino é sempre maior que a da origem.
- REMOVE: apaga ``op:{id}:{custodia}`` e ``custodia-vc:{id}``.
- Versão ausente ou fora do formato: apaga as chaves que o evento marcaria, para não deixar o cache desatualizado.
- Um evento posterior na mesma chave substitui a ação anterior; entre marcações, vence a maior versão.

A chave compartilhada ``custodia:{id}`` (contrato com a fonte primária, ADR-0017) nunca entra no plano.
"""

from dataclasses import dataclass, field

from invalidador.registro import Registro


def chave_operacao(id_operacao: str, custodia: str) -> str:
    return f"op:{id_operacao}:{custodia}"


def chave_custodia(id_operacao: str) -> str:
    return f"custodia-vc:{id_operacao}"


@dataclass(frozen=True)
class Marcacao:
    versao: int
    ttl_ms: int


@dataclass
class Plano:
    marcar: dict[str, Marcacao] = field(default_factory=dict)
    apagar: set[str] = field(default_factory=set)
    versoes_invalidas: int = 0

    def __bool__(self) -> bool:
        return bool(self.marcar or self.apagar)


def planejar(registros: list[Registro], ttl_operacao_ms: int, ttl_custodia_ms: int) -> Plano:
    plano = Plano()
    for registro in registros:
        if registro.evento not in ("INSERT", "MODIFY", "REMOVE"):
            continue
        chaves = [(chave_operacao(registro.id_operacao, registro.custodia), ttl_operacao_ms)]
        if registro.evento in ("INSERT", "REMOVE"):
            chaves.append((chave_custodia(registro.id_operacao), ttl_custodia_ms))
        if registro.evento == "REMOVE" or registro.versao is None:
            if registro.evento != "REMOVE":
                plano.versoes_invalidas += 1
            for chave, _ in chaves:
                plano.marcar.pop(chave, None)
                plano.apagar.add(chave)
            continue
        for chave, ttl in chaves:
            anterior = plano.marcar.get(chave)
            if anterior is None or registro.versao > anterior.versao:
                plano.marcar[chave] = Marcacao(registro.versao, ttl)
            plano.apagar.discard(chave)
    return plano
