# autilo-dati

Dati aperti per l'app **Autilo**, che confronta il costo totale di due o più
auto in 3, 5 e 10 anni. L'app scarica questi file all'avvio e li salva sul
telefono; senza rete usa la copia che ha già.

I file stanno nella cartella [`dati/`](dati) e si leggono anche da
`https://raw.githubusercontent.com/scapinmanuel-star/autilo-dati/main/dati/<nome>`.

| File | Contenuto | Aggiornamento |
|---|---|---|
| `carburanti.json` | Prezzo medio nazionale di benzina, gasolio e GPL dell'ultima settimana e medie su 1, 3 e 5 anni | Automatico, controllo ogni giorno |
| `storico_carburanti_it.csv` | Serie settimanale italiana dal 2005, euro al litro | Automatico, con il precedente |
| `auto.json` | Catalogo dei motori: potenza, consumi reali, prezzo, manutenzione | A mano, dal file Excel del catalogo |
| `listino.json` | Versioni e prezzi del listino 2026 per modello | A mano |
| `tariffe.json` | Bollo, revisione, prezzo dell'energia elettrica, premio RC di riferimento | A mano |
| `indice.json` | Elenco dei file con data, dimensione e impronta SHA-256 | Automatico |

## Come si aggiornano i prezzi dei carburanti

Il workflow [`Aggiorna dati`](.github/workflows/aggiorna.yml) parte ogni
mattina:

1. scarica il file storico del *Weekly Oil Bulletin* della Commissione europea;
2. prende le colonne dell'Italia (prezzi con tasse, euro per 1000 litri);
3. controlla che i valori siano credibili: intervalli plausibili, nessun salto
   oltre il 25% rispetto all'ultimo dato pubblicato, serie di almeno 5 anni;
4. riscrive `carburanti.json`, `storico_carburanti_it.csv` e `indice.json`;
5. fa un commit solo se qualcosa è cambiato.

Se un controllo fallisce il workflow si ferma con errore e i dati pubblicati
restano quelli della volta prima.

La media su 5 anni è la media aritmetica delle settimane degli ultimi 5 anni,
contati dall'ultima settimana pubblicata.

Il sito del MIMIT (Osservaprezzi, file giornalieri `prezzo_alle_8.csv`) non
risponde ai server di GitHub, quindi per ora si usa la serie settimanale UE,
che per l'Italia riporta le medie nazionali comunicate dal MASE.

## Aggiornare il catalogo

`auto.json` e `listino.json` si generano nel progetto dell'app con
`tool/genera_catalogo.py`; poi si copiano qui insieme a `tariffe.json`. Il
workflow rifà l'indice e lo pubblica.

## Fonti e licenze

- Prezzi dei carburanti: Commissione europea, DG Energia,
  [Weekly Oil Bulletin](https://energy.ec.europa.eu/data-and-analysis/weekly-oil-bulletin_en).
  Riproduzione autorizzata con citazione della fonte. Dati italiani forniti
  dal Ministero dell'ambiente e della sicurezza energetica (MASE).
- Consumi reali: Agenzia europea dell'ambiente (EEA), dati di monitoraggio
  delle emissioni di CO₂ delle auto nuove.
- Energia elettrica a casa: ARERA, prezzo di riferimento per i clienti domestici.
- Prezzi di listino: listini delle case, con data e affidabilità indicate per
  ogni voce.

I valori sono stime per confrontare le auto, non preventivi.
