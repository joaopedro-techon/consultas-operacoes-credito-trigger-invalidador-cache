"""Monta o pacote da Lambda em build/pacote: o código de src/invalidador e as dependências de runtime.

Uso: python scripts/empacotar.py
O Terraform (infra/lambda) compacta essa pasta. As dependências são puro Python (redis-py), então o pacote é o
mesmo em x86_64 e arm64.
"""

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "build" / "pacote"


def main() -> None:
    dependencias = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    shutil.rmtree(DESTINO, ignore_errors=True)
    DESTINO.mkdir(parents=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--no-compile", "--target", str(DESTINO), *dependencias],
        check=True,
    )
    shutil.copytree(RAIZ / "src" / "invalidador", DESTINO / "invalidador",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for sobra in DESTINO.glob("*.dist-info"):
        shutil.rmtree(sobra)
    print(f"Pacote em {DESTINO}")


if __name__ == "__main__":
    main()
