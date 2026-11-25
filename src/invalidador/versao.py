"""Versão do registro: o ``codigo_identificador_carga`` (ISO-8601) em epoch ms.

Mesma regra da API de consultas, que confere a versão do cache com a que ela mesma converte:

- com fuso, respeita o fuso; sem fuso, é lido como UTC;
- data e hora separadas por ``T`` (só data, ou separadas por espaço, ficam fora do formato);
- milissegundos truncados (micro e nanossegundos descartados, como ``Instant.toEpochMilli``).
"""

from datetime import UTC, datetime, timedelta

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_UM_MS = timedelta(milliseconds=1)


def epoch_ms(texto: str | None) -> int | None:
    """Epoch ms da versão, ou ``None`` se ausente ou fora do formato."""
    if not texto or "T" not in texto:
        return None
    try:
        instante = datetime.fromisoformat(texto)
    except ValueError:
        return None
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=UTC)
    return (instante - _EPOCH) // _UM_MS
