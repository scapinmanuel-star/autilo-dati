import datetime as dt
import io
import json
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "script"))

import aggiorna_carburanti as ac  # noqa: E402
import aggiorna_indice as ai  # noqa: E402

ULTIMA = dt.date(2026, 11, 16)


def crea_xlsx(settimane=600, ultima=ULTIMA, prezzi=None, salta_colonna=None):
    """File simile allo storico UE: 3 righe d'intestazione, date decrescenti."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = ac.FOGLIO
    intest = ["Consumer prices", "CTR", "EU_price_with_tax_euro95", "EU_price_with_tax_diesel",
              "CTR", "IT_price_with_tax_euro95", "IT_price_with_tax_diesel",
              "IT_price_with_tax_heating_oil", "IT_price_with_tax_LPG"]
    if salta_colonna:
        intest = [c for c in intest if c != salta_colonna]
    ws.append(intest)
    ws.append([None, None, "Euro-super 95"])
    ws.append(["Date", None, "1000 l"])
    for i in range(settimane):
        data = dt.datetime.combine(ultima - dt.timedelta(weeks=i), dt.time())
        # prezzi: la settimana i-esima ha benzina 1800 + i (euro/1000 l)
        b, d, g = prezzi(i) if prezzi else (1800 + i, 1700 + i, 700 + i / 10)
        riga = [data, "EU_", 1900, 1800, "IT_", b, d, 1500, g]
        if salta_colonna:
            riga = riga[:len(intest)]
        ws.append(riga)
    ws.append(["Nota a piè di pagina"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_legge_la_serie_in_euro_al_litro_dalla_piu_vecchia():
    serie = ac.leggi_serie(crea_xlsx(settimane=300))
    assert len(serie) == 300
    assert serie[-1].data == ULTIMA
    assert serie[-1].benzina == pytest.approx(1.8)
    assert serie[-1].diesel == pytest.approx(1.7)
    assert serie[-1].gpl == pytest.approx(0.7)
    assert serie[0].benzina == pytest.approx(2.099)


def test_salta_le_settimane_senza_dato():
    def prezzi(i):
        return (None, 1700, 700) if i == 1 else (1800, 1700, 700)
    serie = ac.leggi_serie(crea_xlsx(settimane=300, prezzi=prezzi))
    assert len(serie) == 299
    assert ULTIMA - dt.timedelta(weeks=1) not in [s.data for s in serie]


def test_colonna_mancante_da_errore():
    with pytest.raises(ac.ErroreDati, match="colonna"):
        ac.leggi_serie(crea_xlsx(salta_colonna="IT_price_with_tax_LPG"))


def test_media_5_anni_usa_le_settimane_del_periodo():
    serie = ac.leggi_serie(crea_xlsx(settimane=600))
    m5, scelte = ac.media(serie, 5)
    assert len(scelte) == 261  # 1826 giorni / 7: le settimane da i=0 a i=260
    attesa = sum(1800 + i for i in range(261)) / 261 / 1000
    assert m5["benzina"] == pytest.approx(attesa, abs=0.0006)
    m1, scelte1 = ac.media(serie, 1)
    assert len(scelte1) == 53


def test_controlli():
    serie = ac.leggi_serie(crea_xlsx(settimane=300))
    assert ac.controlla(serie, ULTIMA, {"benzina": 1.79, "diesel": 1.71, "gpl": 0.7}) == []
    assert ac.controlla(serie, ULTIMA + dt.timedelta(days=40), None)  # avviso: vecchia
    with pytest.raises(ac.ErroreDati, match="salto"):
        ac.controlla(serie, ULTIMA, {"benzina": 1.2})
    with pytest.raises(ac.ErroreDati, match="corta"):
        ac.controlla(serie[-100:], ULTIMA, None)
    sbagliata = ac.leggi_serie(crea_xlsx(settimane=300, prezzi=lambda i: (1800, 17000, 700)))
    with pytest.raises(ac.ErroreDati, match="fuori intervallo"):
        ac.controlla(sbagliata, ULTIMA, None)


def test_trova_link_storico():
    html = ('<a href="/document/download/abc_en?filename=2018_spain_notes.pdf">x</a>'
            '<a href="/document/download/906e_en?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx&amp;x=1">y</a>')
    assert ac.trova_link_storico(html) == (
        "https://energy.ec.europa.eu/document/download/906e_en"
        "?filename=Weekly_Oil_Bulletin_Prices_History_maticni_4web.xlsx&x=1")
    assert ac.trova_link_storico("<html></html>") is None


def test_main_scrive_i_file_e_non_li_tocca_se_i_dati_sono_sbagliati(tmp_path):
    xlsx = tmp_path / "storico.xlsx"
    xlsx.write_bytes(crea_xlsx(settimane=600))
    uscita = tmp_path / "dati"
    assert ac.main(["--xlsx", str(xlsx), "--uscita", str(uscita), "--oggi", "2026-11-18"]) == 0
    dati = json.loads((uscita / "carburanti.json").read_text(encoding="utf-8"))
    assert dati["data_aggiornamento"] == "2026-11-16"
    assert dati["oggi"] == {"benzina": 1.8, "diesel": 1.7, "gpl": 0.7}
    assert set(dati["media_5_anni"]) == {"benzina", "diesel", "gpl"}
    assert dati["media_5_anni_periodo"]["settimane"] == 261
    righe = (uscita / "storico_carburanti_it.csv").read_text(encoding="utf-8").splitlines()
    assert righe[0] == "settimana,benzina_eur_l,gasolio_eur_l,gpl_eur_l"
    assert righe[-1] == "2026-11-16,1.8000,1.7000,0.7000"
    prima = (uscita / "carburanti.json").read_text(encoding="utf-8")

    # Un file con un salto del 50% viene rifiutato e i dati restano quelli di prima.
    xlsx.write_bytes(crea_xlsx(settimane=600, prezzi=lambda i: (2700, 1700, 700)))
    assert ac.main(["--xlsx", str(xlsx), "--uscita", str(uscita), "--oggi", "2026-11-18"]) == 1
    assert (uscita / "carburanti.json").read_text(encoding="utf-8") == prima


def test_indice(tmp_path):
    for nome in ai.OBBLIGATORI:
        (tmp_path / nome).write_text(json.dumps({"data_aggiornamento": "2026-11-16"}), encoding="utf-8")
    (tmp_path / "storico_carburanti_it.csv").write_text("a,b\n", encoding="utf-8")
    indice = ai.componi_indice(tmp_path)
    assert indice["formato"] == 1
    assert indice["file"]["auto.json"]["data"] == "2026-11-16"
    assert len(indice["file"]["auto.json"]["sha256"]) == 64
    assert "data" not in indice["file"]["storico_carburanti_it.csv"]

    (tmp_path / "tariffe.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="tariffe.json"):
        ai.componi_indice(tmp_path)
    (tmp_path / "tariffe.json").unlink()
    with pytest.raises(ValueError, match="mancano"):
        ai.componi_indice(tmp_path)
