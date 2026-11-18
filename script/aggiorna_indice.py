"""Scrive dati/indice.json: elenco dei file pubblicati con data e impronta.

L'app scarica prima l'indice (pochi byte) e poi solo i file cambiati.
Lo script controlla anche che ogni file JSON sia leggibile e abbia la
data di aggiornamento, così un file rovinato non arriva ai telefoni.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

FORMATO = 1
DATI = Path(__file__).resolve().parent.parent / "dati"
# File che l'app usa: devono esserci tutti.
OBBLIGATORI = ("auto.json", "listino.json", "tariffe.json", "carburanti.json")


def componi_indice(cartella: Path) -> dict:
    file = {}
    for p in sorted(cartella.iterdir()):
        if p.name == "indice.json" or not p.is_file() or p.name.startswith("."):
            continue
        contenuto = p.read_bytes()
        voce = {"byte": len(contenuto), "sha256": hashlib.sha256(contenuto).hexdigest()}
        if p.suffix == ".json":
            dati = json.loads(contenuto.decode("utf-8"))
            data = dati.get("data_aggiornamento")
            if not isinstance(data, str) or len(data) != 10:
                raise ValueError(f"{p.name}: manca data_aggiornamento")
            voce["data"] = data
        file[p.name] = voce
    mancanti = [n for n in OBBLIGATORI if n not in file]
    if mancanti:
        raise ValueError(f"mancano: {', '.join(mancanti)}")
    return {"formato": FORMATO, "file": file}


def main() -> int:
    try:
        indice = componi_indice(DATI)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 1
    (DATI / "indice.json").write_text(
        json.dumps(indice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for nome, v in indice["file"].items():
        print(f"{nome:28} {v.get('data', ''):10} {v['byte']:>8} byte")
    return 0


if __name__ == "__main__":
    sys.exit(main())
