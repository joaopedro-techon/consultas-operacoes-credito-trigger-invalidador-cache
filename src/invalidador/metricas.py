"""Métricas no CloudWatch pelo Embedded Metric Format (EMF): documentos JSON no stdout da Lambda, sem chamada à API.

Um documento por invocação, com os totais do lote, e um por tipo de chave (``op``, ``custodia-vc``) com os
marcadores gravados e rejeitados.
"""

import json
import os
import sys
import time
from collections import Counter

NAMESPACE_PADRAO = "ConsultasOperacoesCredito/InvalidadorCache"

TOTAIS = {
    "TamanhoLote": "Count",
    "ChavesRemovidas": "Count",
    "VersoesInvalidas": "Count",
    "RegistrosInvalidos": "Count",
    "FalhasValkey": "Count",
    "AtrasoMs": "Milliseconds",
}
POR_TIPO_DE_CHAVE = {"MarcadoresGravados": "Count", "MarcadoresRejeitados": "Count"}


def tipo_de_chave(chave: str) -> str:
    return chave.split(":", 1)[0]


class Metricas:
    def __init__(self) -> None:
        self.totais: Counter[str] = Counter({nome: 0 for nome in TOTAIS})
        self.por_tipo: dict[str, Counter[str]] = {}
        self.atraso_ms: int | None = None

    def contar(self, nome: str, quantidade: int = 1) -> None:
        self.totais[nome] += quantidade

    def contar_chaves(self, nome: str, chaves: list[str]) -> None:
        for chave in chaves:
            self.por_tipo.setdefault(tipo_de_chave(chave), Counter())[nome] += 1

    def registrar_atraso(self, criacoes_s: list[float]) -> None:
        if criacoes_s:
            self.atraso_ms = max(0, int(time.time() * 1000 - min(criacoes_s) * 1000))

    def emitir(self, saida=None) -> None:
        saida = saida or sys.stdout
        namespace = os.environ.get("METRICAS_NAMESPACE", NAMESPACE_PADRAO)
        agora = int(time.time() * 1000)
        valores = dict(self.totais)
        unidades = dict(TOTAIS)
        if self.atraso_ms is None:
            valores.pop("AtrasoMs")
            unidades.pop("AtrasoMs")
        else:
            valores["AtrasoMs"] = self.atraso_ms
        _escrever(saida, namespace, agora, [], {}, valores, unidades)
        for tipo, contagem in sorted(self.por_tipo.items()):
            valores_tipo = {nome: contagem.get(nome, 0) for nome in POR_TIPO_DE_CHAVE}
            _escrever(saida, namespace, agora, ["TipoChave"], {"TipoChave": tipo}, valores_tipo, POR_TIPO_DE_CHAVE)


def _escrever(saida, namespace, agora, dimensoes, valores_dimensoes, valores, unidades) -> None:
    documento = {
        "_aws": {
            "Timestamp": agora,
            "CloudWatchMetrics": [{
                "Namespace": namespace,
                "Dimensions": [dimensoes],
                "Metrics": [{"Name": nome, "Unit": unidades[nome]} for nome in valores],
            }],
        },
        **valores_dimensoes,
        **valores,
    }
    print(json.dumps(documento), file=saida, flush=True)
