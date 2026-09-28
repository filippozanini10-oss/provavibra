# VIBRA CALCIO SPLASH 2027 — Gestionale Staff

MVP locale/interno con:
- password unica staff
- squadre e giocatori
- autorizzazioni / svincoli / blocchi
- documenti con upload
- partite e timer
- ricalcolo ritardi
- classifiche e penalità
- tabellone semplice
- campi
- eventi
- registro modifiche
- chiusura giornata
- control room
- impostazioni torneo

## Avvio

1. Installa Python 3.11+.
2. Apri il terminale nella cartella.
3. Esegui:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

4. Apri http://127.0.0.1:5000
5. Password iniziale: `vibra2027`

La password può essere cambiata da Impostazioni.

Database: `vibra.db`
Upload: `uploads/`

Per uso reale durante il torneo è consigliato mettere il gestionale su una rete privata dello staff con backup del database.
