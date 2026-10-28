# ExpenseTracker — guida d'uso

## 1. Cosa fa

ExpenseTracker **cattura le uscite**: estratti conto BBVA (xlsx e PDF), storico Excel,
export PayPal, scontrini da foto o PDF, spese singole. Per ognuna propone categoria e
«condivisa sì/no», te la fa confermare e la scrive nel nodo **Finance**.
Non tiene uno storico proprio: le uscite vivono solo in Finance.
Gli stati sono due: `proposto` → `confermato`.

## 2. Come si apre

Non ha un'interfaccia web. Si usa in tre modi:

- **CLI**: `cd backend && .venv/bin/python -m expense_tracker_backend.cli <comando>`
  (su Windows `.venv/Scripts/python`).
- **API**: `http://127.0.0.1:10024` in una configurazione locale. Salute:
  `GET /api/health`. Swagger: `/docs`.

Ogni comando CLI accetta `--dry-run`: legge Finance e **non scrive niente**. Provalo sempre
per primo su un file nuovo.

## 3. Casi d'uso

### a. Estratto conto BBVA (.xlsx)
- CLI: `import-bank <file.xlsx>`
- API: `POST /api/import/bank` (upload nel campo `file`, `?dry_run=true` per provare)

Le righe diventano proposte e, se c'è uno scontrino in attesa, lo riconcilia.
Esempio verificato: un dry-run su un estratto di prova ha risposto
`{"parsed":170,"created":170,"existing":0,"reconciled":0,...,"dry_run":true}`.

### b. Estratto conto PDF
- CLI: `import-bank-pdf <file.pdf>`
- API: `POST /api/import/bank_pdf`

### c. Scontrino da foto o PDF
- CLI: `import-receipt <file>` (aggiungi `--confirmed` se hai pagato in contanti)
- API: `POST /api/import/receipt`

Lo scontrino resta `proposto` finché non arriva la riga di banca corrispondente: stesso
importo (al netto dei buoni) entro 4 giorni. A quel punto si conferma da solo.

### d. Spesa singola a mano
- CLI: `add --desc "..." --amount 150,00 --date 25/10/2026` (`--confirmed` per i contanti; `--category`, `--shared`/`--personal`, `--buoni` facoltativi)
- API: `POST /api/expenses`

### e. Export PayPal (.csv)
- CLI: `import-paypal <file.csv>`

Rinomina le proposte «PayPal (da dettagliare)» con il negozio vero.

### f. Storico Excel
- CLI: `import-excel <file.xlsx>`

### g. Rivedere le proposte
- CLI: `review` — conferma o corregge ogni proposta e insegna l'abbinamento
  negozio → categoria.
- CLI: `merchant-map` (API: `GET /api/merchant-map`) — elenca cosa ha imparato.

## 4. Servizi LLM

Oggi il nodo **non usa nessun modello linguistico**: la classificazione segue le regole del
`merchant_map` e l'OCR gira in locale con Tesseract. Se un giorno ne userà uno, si
dichiarerà come servizio esplicito nella configurazione dell'installazione.

## 5. Problemi comuni

| Sintomo | Cosa fare |
|---|---|
| La CLI esce con codice 1, l'API risponde 502 | Finance è spento o irraggiungibile. Il nodo non restituisce mai un risultato vuoto: riaccendi Finance e ripeti. |
| Ho importato due volte la stessa riga | Nessun problema: non crea doppioni, risponde «già presente». |
| Uno scontrino non si conferma | Importo o data fuori dalla finestra di ±4 giorni, oppure più scontrini candidati. Confermalo a mano con `review`. |
| La foto dello scontrino non si legge | Serve `tesseract` con la lingua `ita`. Meglio un PDF o una foto dritta e nitida. |
| Categoria sbagliata | Correggila in `review`: il negozio viene imparato. |
