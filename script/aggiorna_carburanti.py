"""Aggiorna i prezzi dei carburanti per l'app Autilo.

Fonte: Weekly Oil Bulletin della Commissione europea, file storico dal 2005
("Prices with taxes"). Per l'Italia i prezzi sono le medie nazionali
settimanali comunicate dal Ministero dell'ambiente e della sicurezza
energetica (MASE), tasse comprese, in euro per 1000 litri.

Produce nella cartella dati/:
- storico_carburanti_it.csv  serie settimanale italiana (euro al litro)
- carburanti.json            prezzo dell'ultima settimana e medie su 1, 3, 5 anni

Se il file scaricato non supera i controlli, lo script esce con errore e
non tocca i dati già pubblicati.

Uso:
    python script/aggiorna_carburanti.py               # scarica e aggiorna
    python script/aggiorna_carburanti.py --xlsx f.xlsx # usa un file locale
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import statistics
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PAGINA = "https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en"
SITO = "https://energy.ec.europa.eu"
# Link noto al file storico, usato se la pagina cambia struttura.
STORICO_NOTO = (
    "https://energy.ec.europa.eu/document/download/"
    "906e60ca-8b6a-44e7-8589-652854d2fd3f_en"
    "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx"
)
UA = "Mozilla/5.0 (compatible; autilo-dati; +https://github.com/scapinmanuel-star/autilo-dati)"

FOGLIO = "Prices with taxes"
COLONNE = {
    "benzina": "IT_price_with_tax_euro95",
    "diesel": "IT_price_with_tax_diesel",
    "gpl": "IT_price_with_tax_LPG",
}
# Intervalli plausibili in euro al litro.
INTERVALLI = {"benzina": (1.0, 3.5), "diesel": (1.0, 3.5), "gpl": (0.4, 1.6)}
# Variazione massima accettata rispetto all'ultima settimana già pubblicata.
SALTO_MASSIMO = 0.25
# Oltre questi giorni l'ultima settimana è considerata vecchia.
GIORNI_VECCHIA = 28

FONTE = (
    "Commissione europea, Weekly Oil Bulletin: prezzi medi nazionali "
    "settimanali per l'Italia comunicati dal MASE, tasse comprese"
)


class ErroreDati(Exception):
    pass


@dataclass(frozen=True)
class Settimana:
    data: dt.date
    benzina: float
    diesel: float
    gpl: float

    def valore(self, carburante: str) -> float:
        return getattr(self, carburante)


# ---------------------------------------------------------------- download

def _scarica(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def trova_link_storico(html: str) -> str | None:
    """Cerca nella pagina del bollettino il link al file storico."""
    for href in re.findall(r'href="([^"]+)"', html):
        if "prices_history" in href.lower():
            href = href.replace("&amp;", "&")
            return SITO + href if href.startswith("/") else href
    return None


def scarica_storico() -> tuple[bytes, str]:
    link = None
    try:
        link = trova_link_storico(_scarica(PAGINA).decode("utf-8", "replace"))
    except Exception as e:  # la pagina può non rispondere: si prova il link noto
        print(f"Pagina del bollettino non letta ({e}); uso il link noto.")
    link = link or STORICO_NOTO
    print(f"Scarico {link}")
    return _scarica(link, timeout=180), link


# ---------------------------------------------------------------- lettura

def leggi_serie(contenuto: bytes) -> list[Settimana]:
    """Legge la serie italiana dal file storico; ordinata dalla più vecchia."""
    import openpyxl  # importato qui: serve solo per leggere l'xlsx

    wb = openpyxl.load_workbook(io.BytesIO(contenuto), read_only=True, data_only=True)
    if FOGLIO not in wb.sheetnames:
        raise ErroreDati(f"manca il foglio '{FOGLIO}' (fogli: {wb.sheetnames})")
    righe = wb[FOGLIO].iter_rows(values_only=True)
    intestazione = [str(c).strip() if c is not None else "" for c in next(righe)]
    try:
        indici = {k: intestazione.index(v) for k, v in COLONNE.items()}
    except ValueError as e:
        raise ErroreDati(f"colonna dell'Italia non trovata: {e}") from None

    serie: dict[dt.date, Settimana] = {}
    for r in righe:
        if not r or not isinstance(r[0], (dt.datetime, dt.date)):
            continue
        data = r[0].date() if isinstance(r[0], dt.datetime) else r[0]
        valori = {}
        for k, i in indici.items():
            v = r[i] if i < len(r) else None
            if v in (None, ""):
                break
            valori[k] = round(float(v) / 1000, 4)
        else:
            serie[data] = Settimana(data, **valori)
    if not serie:
        raise ErroreDati("nessuna settimana con i tre prezzi dell'Italia")
    return [serie[d] for d in sorted(serie)]


# ---------------------------------------------------------------- controlli

def controlla(serie: list[Settimana], oggi: dt.date,
              ultima_pubblicata: dict[str, float] | None) -> list[str]:
    """Solleva ErroreDati se i dati non sono credibili; ritorna gli avvisi."""
    avvisi = []
    if len(serie) < 260:
        raise ErroreDati(f"serie troppo corta: {len(serie)} settimane")
    ultima = serie[-1]
    if ultima.data > oggi + dt.timedelta(days=7):
        raise ErroreDati(f"ultima settimana nel futuro: {ultima.data}")
    for s in serie[-260:]:
        for k, (lo, hi) in INTERVALLI.items():
            if not lo <= s.valore(k) <= hi:
                raise ErroreDati(f"{k} fuori intervallo il {s.data}: {s.valore(k)}")
    if ultima_pubblicata:
        for k in COLONNE:
            prima = ultima_pubblicata.get(k)
            if prima and abs(ultima.valore(k) / prima - 1) > SALTO_MASSIMO:
                raise ErroreDati(
                    f"{k}: salto sospetto da {prima} a {ultima.valore(k)}")
    if (oggi - ultima.data).days > GIORNI_VECCHIA:
        avvisi.append(f"ultima settimana vecchia: {ultima.data}")
    return avvisi


# ---------------------------------------------------------------- calcoli

def media(serie: list[Settimana], anni: int) -> tuple[dict[str, float], list[Settimana]]:
    """Media delle settimane negli ultimi `anni` anni, contati dall'ultima."""
    limite = serie[-1].data - dt.timedelta(days=round(365.25 * anni))
    scelte = [s for s in serie if s.data > limite]
    return {k: round(statistics.fmean(s.valore(k) for s in scelte), 3)
            for k in COLONNE}, scelte


def componi_json(serie: list[Settimana], link: str) -> dict:
    ultima = serie[-1]
    m5, sel5 = media(serie, 5)
    m3, _ = media(serie, 3)
    m1, _ = media(serie, 1)
    return {
        "formato": 1,
        "data_aggiornamento": ultima.data.isoformat(),
        "nota": "Prezzi in euro al litro, tasse comprese. 'oggi' è la media "
                "nazionale dell'ultima settimana pubblicata; le medie sono "
                "aritmetiche sulle settimane del periodo.",
        "fonte": FONTE,
        "url_fonte": PAGINA,
        "file_fonte": link,
        "settimana": ultima.data.isoformat(),
        "oggi": {k: round(ultima.valore(k), 3) for k in COLONNE},
        "media_5_anni": m5,
        "media_5_anni_periodo": {
            "dal": sel5[0].data.isoformat(),
            "al": sel5[-1].data.isoformat(),
            "settimane": len(sel5),
        },
        "media_3_anni": m3,
        "media_1_anno": m1,
    }


def scrivi_csv(serie: list[Settimana], percorso: Path) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["settimana", "benzina_eur_l", "gasolio_eur_l", "gpl_eur_l"])
    for s in serie:
        w.writerow([s.data.isoformat(), f"{s.benzina:.4f}", f"{s.diesel:.4f}", f"{s.gpl:.4f}"])
    percorso.write_text(buf.getvalue(), encoding="utf-8")


def scrivi_json(dati: dict, percorso: Path) -> None:
    percorso.write_text(json.dumps(dati, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--xlsx", type=Path, help="file storico locale invece del download")
    ap.add_argument("--uscita", type=Path, default=Path(__file__).resolve().parent.parent / "dati")
    ap.add_argument("--oggi", type=dt.date.fromisoformat, default=dt.date.today())
    a = ap.parse_args(argv)

    if a.xlsx:
        contenuto, link = a.xlsx.read_bytes(), STORICO_NOTO
    else:
        contenuto, link = scarica_storico()

    a.uscita.mkdir(parents=True, exist_ok=True)
    percorso_json = a.uscita / "carburanti.json"
    precedente = None
    if percorso_json.exists():
        precedente = json.loads(percorso_json.read_text(encoding="utf-8")).get("oggi")

    try:
        serie = leggi_serie(contenuto)
        avvisi = controlla(serie, a.oggi, precedente)
    except ErroreDati as e:
        print(f"ERRORE: {e}. Dati pubblicati lasciati come sono.", file=sys.stderr)
        return 1
    for av in avvisi:
        print(f"::warning::{av}")

    dati = componi_json(serie, link)
    scrivi_csv(serie, a.uscita / "storico_carburanti_it.csv")
    scrivi_json(dati, percorso_json)
    print(f"Settimana {dati['settimana']}: oggi {dati['oggi']}, "
          f"media 5 anni {dati['media_5_anni']} ({dati['media_5_anni_periodo']['settimane']} settimane)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
