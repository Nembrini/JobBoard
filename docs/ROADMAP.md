# Roadmap — fasi e sottofasi

> Per le scelte tecniche e il perché di ognuna vedi [ARCHITECTURE.md](./ARCHITECTURE.md).

**Stima totale: ~16 giorni-uomo.**
**MVP online e navigabile alla fine della Fase 4** (~5 giorni): dashboard pubblica con
tabella e punteggi di compatibilità, candidatura ancora manuale.

Ogni fase si chiude con un criterio di verifica osservabile. Se il criterio non passa,
la fase non è finita: non si prosegue accumulando debito.

---

## Prerequisiti — cose che può fare solo Filippo

Vanno completate prima della Fase 0.2. Sono azioni su account personali e richiedono
credenziali, quindi non sono automatizzabili.

- [x] **Installare Python 3.12** da [python.org](https://www.python.org/downloads/release/python-31210/)
      selezionando "Add python.exe to PATH". Non rimuovere il 3.14 già presente: convivono.
- [ ] Creare un progetto **Supabase** gratuito, region `eu-central-1` (Francoforte).
      Annotare: connection string diretta, connection string pooler, project URL, service role key.
- [ ] Creare nel progetto Supabase un bucket Storage **privato** chiamato `resumes`.
- [ ] Creare un account **Vercel** e collegarlo al repository.
- [ ] Creare credenziali **Google OAuth** su Google Cloud Console (tipo "Web application"),
      con redirect URI `https://<dominio-vercel>/api/auth/callback/google`.
- [ ] Ottenere una **API key Anthropic** su console.anthropic.com (a consumo, separata
      dall'abbonamento Claude Code).
- [ ] Registrare le chiavi gratuite delle fonti: **Adzuna** (app id + key), **Jooble**,
      **RapidAPI** per JSearch.
- [ ] Attivare la verifica in due passaggi su Gmail e generare una **App Password** per
      SMTP/IMAP. Serve solo dalla Fase 8 in poi.

Tutte queste chiavi vanno in `worker/.env` (mai committato) e nelle Environment
Variables del progetto Vercel. Il template è in `.env.example`.

---

## Fase 0 — Fondamenta e infrastruttura · 1 gg

- [x] **0.1** Python 3.12, `worker/.venv`, `git init`, struttura cartelle
- [x] **0.2** Progetto Supabase region EU: Postgres + bucket privato `resumes`; **session pooler** per il worker (porta 5432) e transaction pooler per Vercel (6543)
- [x] **0.3** SQLAlchemy + Alembic nel worker, migration applicate su Supabase: 13 tabelle, 14 indici, 16 vincoli CHECK
- [x] **0.4** `create-next-app` in `web/`, Tailwind + shadcn/ui, tipi TypeScript generati da `jobboard gen-web-schema` *(non da `drizzle-kit pull`: va in crash sui pseudo-CHECK dei NOT NULL)*
- [x] **0.5** Progetto Vercel collegato al repo, environment variables, primo deploy — live su [job-board-official.vercel.app](https://job-board-official.vercel.app)
- [x] **0.6** `.env.example`, `.gitignore`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`
- [x] **0.7** `playwright install chromium` sul worker (~150 MB, una volta sola)

**Verifica:** ✅ sito live su https://job-board-official.vercel.app (HTTP 200), database Supabase raggiungibile dal worker, 13 tabelle create.

---

## Fase 1 — Profilo e CV master · 1 gg

- [x] **1.1** Estrazione testo da PDF/DOCX: doppio estrattore con scelta gerarchica — integrità delle parole, poi cifre conservate, poi qualità della prosa
- [x] **1.2** Schema Pydantic `MasterProfile` con id stabili e bullet in forma ACR
- [x] **1.3** Structuring LLM testo → `MasterProfile`, con normalizzazione deterministica delle date e id assegnati dal codice
- [x] **1.4** `CandidateAnswers`: le risposte standard ai form ATS (telefono, LinkedIn, GitHub, work authorization, preavviso, RAL attesa)
- [x] **1.5** Embedding del profilo con fastembed, in locale su CPU
- [x] **1.6** Persistenza su Supabase e comandi `profile import` / `load` / `embed` / `show`, `candidate init` / `load` / `show`
- [~] **1.7** Revisione campo per campo in dashboard — *rimandata alla Fase 4, dove la UI esiste già. Per ora la revisione si fa sul JSON in VS Code*

> **1.3 è il punto critico dell'intero progetto.** Ogni punteggio di compatibilità e ogni
> CV generato derivano da questo JSON. Va corretto a mano una volta sola, ma va corretto bene.
> Il flag `reviewed` sulla tabella `profile` esiste apposta: la pipeline di matching non
> parte finché è `false`.

**Verifica:** `jobboard profile import CV.pdf` → correggi il JSON → `jobboard profile load`
→ `jobboard profile show` rilegge dal database profilo, flag di revisione ed embedding.

---

## Fase 2 — Ingestione · 2 gg

- [x] **2.1** Interfaccia `SourceAdapter` con registry, rate limiter e retry con backoff, tutti nel client HTTP condiviso invece che in ogni adapter
- [x] **2.2** Adapter gratuiti: **Adzuna** (IT/DE/NL/ES/FR/UK), **Jooble**, **Arbeitnow**, **Remotive**, **RemoteOK**
- [x] **2.3** Adapter ATS sulle company board seguite: **Greenhouse**, **Lever**, **Ashby**, **Workable**, con `jobboard sources boards` per aggiungerne
- [x] **2.4** Adapter **JSearch** (Google for Jobs, quindi LinkedIn/Indeed/Glassdoor), con budget giornaliero esplicito e query consumate in ordine di priorità
- [x] **2.5** Normalizzazione: work_mode, seniority, tipo contratto, famiglia di ruolo, **parsing RAL multi-valuta e multi-periodo** con mensilità italiane, rilevamento lingua
- [x] **2.6** Dedup canonico + SimHash, con fusione delle varianti: vince il link ATS, la descrizione più lunga, la RAL dichiarata e la data più vecchia
- [x] **2.7** Tabella `run` con esito, conteggi e chiamate API per fonte
- [~] **2.8** Chiavi Adzuna e Jooble in `worker/.env` — *le fonti restano spente finché non ci sono*

> **La retribuzione predetta va scartata.** Adzuna restituisce una RAL anche quando
> l'annuncio non ne dichiara alcuna, marcandola con `salary_is_predicted`. La dashboard
> promette *"RAL se dichiarata"*: una stima esibita come dato la renderebbe inaffidabile.

**Verifica:** `jobboard ingest --dry-run` stampa gli annunci normalizzati fonte per
fonte senza scrivere nulla. Misurato sulle sole fonti senza chiave: **181 annunci
raccolti, 154 distinti, 13 chiamate API**, di cui 73 con link ATS diretto.

---

## Fase 3 — Matching · 1.5 gg

- [x] **3.1** Stadio 0: filtri duri configurabili da `settings`, con il motivo di ogni
      scarto salvato in `match.filtered_reason`. Regola trasversale: **un dato mancante
      non esclude mai** — un terzo degli annunci non dichiara il paese e due quinti non
      dichiarano il livello.
- [x] **3.2** Stadio 1: coseno su embedding + BM25 sulle competenze, combinati come
      `0.6*spread(coseno) + 0.4*spread(bm25)`. BM25 cerca le competenze come **frasi**
      (n-grammi fino a tre parole) e usa la IDF smussata, che non diventa mai negativa.
- [x] **3.3** Stadio 2: estrazione `job_requirements` e rubrica pesata in **una sola
      chiamata** per annuncio. La Message Batches API era una feature Anthropic: sul
      provider attivo non esiste, quindi le chiamate sono sequenziali con 4 secondi di
      pausa per restare dentro il rate limit del free tier.
- [x] **3.4** Persistenza `match` con sotto-punteggi, motivazione e gap. La media pesata
      la calcola il codice, non il modello: è l'unico modo di poterla ritarare dopo.
- [x] **3.5** `scripts/calibrate.py`: esporta un CSV da etichettare, cerca i pesi
      migliori su 53 130 combinazioni e **verifica su una metà quello che ha imparato
      sull'altra**, perché sei pesi liberi su trenta esempi trovano sempre qualcosa.
- [x] **3.6** Comandi `jobboard match`, `jobboard matches list|show|criteria`.

**Verifica:** eseguita sui 153 annunci in banca dati. L'imbuto ha fatto
**153 -> 44 -> 40**, gli scarti dello Stadio 0 sono livello 85, età 21, paese 3, e i
primi dodici punteggi sono tutti ruoli da sviluppatore coerenti con il profilo. Costo di
una run completa: **40 chiamate, 101k token, circa 5 minuti**.

> **Il bug che ha richiesto la correzione più importante.** Alla prima run vera il
> punteggio più alto dell'intero raccolto — 65, primo in classifica — è andato a un
> annuncio da contabile a Pune con quattro righe di descrizione. La motivazione scritta
> dal modello stesso diceva "ruolo completamente slegato dal profilo tecnico", e
> `domain_fit` valeva 0. Il colpevole era `must_have_coverage: 100`: l'annuncio non
> elencava nessun requisito, e coprire il 100% di zero requisiti è vero quanto è inutile.
> Quel criterio pesa il 40%. Ora un elenco di requisiti vuoto vale **neutro**, non
> perfetto, e quell'annuncio è sceso a 25.

**Resta aperto:** i punteggi non superano 65 perché `location_fit` e `salary_fit` restano
neutri finché `candidate_profile.json` non dichiara lingue, autorizzazione al lavoro e
RAL attesa. Con `MATCH_THRESHOLD=65` passa un annuncio solo.

---

## Fase 4 — Dashboard pubblica su Vercel · 2 gg

- [ ] **4.1** **Auth.js + Google OAuth**, allowlist a una sola email, middleware su tutte le rotte tranne `/login`
- [ ] **4.2** Route handler `GET /api/matches` con filtri, ordinamento e paginazione lato server
- [ ] **4.3** Tabella TanStack: **Ruolo · Azienda · Luogo · Modalità · RAL · Tipo · Match % · Fonte · Azioni**
- [ ] **4.4** Badge colorati per modalità (on-site / ibrido / remote) e per fascia di punteggio; RAL mostrata come "n.d." quando non dichiarata — **mai stimata e presentata come dichiarata**
- [ ] **4.5** Filtri: soglia punteggio, modalità, paese, fonte, solo nuovi, nascondi già visti
- [ ] **4.6** Drawer di dettaglio: job description completa, requisiti estratti, **gap evidenziati**, link all'annuncio originale
- [ ] **4.7** Azioni di riga: shortlist, nascondi, **Candidati**
- [ ] **4.8** Layout responsive: su mobile la tabella diventa lista di card, perché è da lì che la consulterai davvero
- [ ] **4.9** Deploy in produzione e verifica che il login respinga ogni altro account Google

**Verifica:** apri l'URL Vercel dal telefono, fai login con Google, ordini per Match % e leggi una job description.

---

## Fase 5 — Ponte UI verso worker · 0.5 gg

- [ ] **5.1** Tabella `task` e enum dei tipi: `generate_cv`, `apply`, `run_pipeline`, `reparse_profile`
- [ ] **5.2** Consumer nel worker con `FOR UPDATE SKIP LOCKED`, polling ogni 30 s, retry ed errori persistiti
- [ ] **5.3** `worker_heartbeat` e indicatore **online/offline** in testata alla dashboard
- [ ] **5.4** Componente di progresso task in UI: in coda / in corso / fatto / errore

**Verifica:** dal telefono premi "Aggiorna adesso"; a worker acceso il task viene raccolto entro 30 s e la UI segue l'avanzamento; a worker spento il task resta in coda e parte da solo al riavvio.

---

## Fase 6 — Generazione CV su misura · 2 gg

- [ ] **6.1** Integrazione **letterale del prompt fornito** (career coach / executive resume writer / ATS specialist, framework ACR, divieto assoluto di inventare), con output strutturato: `top_keywords[5]`, `summary` da 45-60 parole, `experience[]`, `skills{hard, soft}`
- [ ] **6.2** **Validatore anti-invenzione**: ogni bullet e ogni skill deve risalire a una entry del `MasterProfile`; le violazioni bloccano il render e forzano la rigenerazione
- [ ] **6.3** Template Jinja2 ATS-safe: colonna singola, nessuna tabella o icona o layout multi-colonna, font standard, heading canonici
- [ ] **6.4** Render Playwright con **loop fit-a-una-pagina**: render, conteggio pagine, compressione via LLM se serve, massimo 3 iterazioni, e solo in extremis riduzione controllata di interlinea e margini
- [ ] **6.5** Upload su Supabase Storage in `resumes/{job_id}/Filippo_Nembrini_Resume.pdf`
- [ ] **6.6** UI di preview: PDF via signed URL affiancato al diff rispetto al CV master, con le 5 keyword evidenziate; pulsanti Rigenera e Approva
- [ ] **6.7** Lingua del CV determinata dalla lingua della job description (it/en/de/es/fr)

**Verifica:** da un annuncio reale esce un PDF di **esattamente una pagina**, con testo selezionabile, che passa un parser ATS di test ed è scaricabile dal telefono.

---

## Fase 7 — Candidatura · 2.5 gg

- [ ] **7.1** Router per tier in base a `ats_type`
- [ ] **7.2** **Tier A**: client Greenhouse / Lever / Ashby / Workable, mapping dei campi da `candidate_profile`, upload multipart del PDF, parsing e salvataggio della risposta
- [ ] **7.3** **Tier B**: Playwright headful sul PC, autofill euristico su label e attributi ATS noti, **stop prima del submit**, notifica alla dashboard "pronto da rivedere", screenshot salvato
- [ ] **7.4** **Tier C**: apertura URL e task manuale in lista
- [ ] **7.5** Guardrail: dry-run globale, cap giornaliero, conferma alla prima candidatura verso ogni nuova azienda, idempotenza
- [ ] **7.6** Timeline `application_event`

**Verifica:** una candidatura Tier A reale arriva a destinazione e ricevi la mail di conferma dell'ATS; una Tier B si ferma correttamente prima dell'invio.

---

## Fase 8 — Run giornaliera e notifiche · 1 gg

- [ ] **8.1** APScheduler nel worker: pipeline completa una volta al giorno, a orario configurabile
- [ ] **8.2** Windows Task Scheduler con "esegui appena possibile se l'esecuzione è stata saltata", per coprire il PC spento
- [ ] **8.3** Digest email HTML via SMTP Gmail, con i nuovi match sopra soglia e link diretto alla riga sul sito Vercel
- [ ] **8.4** **Toggle notifiche on/off in UI** nella pagina Impostazioni, persistito in `settings`, insieme a soglia e orario
- [ ] **8.5** Pagina Run History: esiti, conteggi ed errori per fonte

**Verifica:** forzi una run dal telefono e la mail arriva; spegni il toggle e non arriva più.

---

## Fase 9 — Tracking post-candidatura · 1.5 gg

- [ ] **9.1** Vista stati: inviata, in attesa, colloquio, rifiutata, offerta — aggiornabili a mano
- [ ] **9.2** Reader IMAP Gmail **con scope ristretto**: solo mail successive alla data della candidatura e correlate per dominio azienda o thread. Non scansiona la casella intera e non conserva il corpo delle mail non correlate
- [ ] **9.3** Classificatore Haiku: `interview` / `rejection` / `ack` / `request_info` / `other`, che aggiorna lo stato e notifica
- [ ] **9.4** Promemoria di follow-up dopo N giorni di silenzio
- [ ] **9.5** Metriche: tasso di risposta per fonte, per fascia di punteggio, per tier

**Verifica:** una mail di risposta reale sposta la candidatura nello stato corretto.

---

## Fase 10 — Rifinitura · 1 gg

- [ ] **10.1** Ricalibrazione dei pesi su dati reali dopo circa due settimane d'uso
- [ ] **10.2** Dashboard di consumo token e costo API
- [ ] **10.3** Backup automatico del database ed export CSV
- [ ] **10.4** README con setup da zero: worker, Vercel, Supabase

---

## Verifica end-to-end

Al termine della Fase 8, il test completo si fa **dal telefono, con il PC acceso in
un'altra stanza**:

1. Apri l'URL Vercel e fai login con Google. Un account diverso deve essere respinto.
2. Verifica l'indicatore **worker online**.
3. Premi "Aggiorna adesso". Entro 30 s parte la run: ingest da tutte le fonti attive,
   dedup, scoring, riga in `run`, digest inviato.
4. Ordina per Match %, apri il drawer del primo risultato, controlla i gap evidenziati.
5. Premi **Candidati**. Il worker genera il CV: verifica che il PDF sia **di una pagina**,
   si chiami `Filippo_Nembrini_Resume.pdf` e sia scaricabile dal telefono via signed URL.
6. Approva su un annuncio Greenhouse (Tier A), conferma l'invio e attendi la mail di
   conferma dell'ATS.
7. Spegni il worker e premi di nuovo **Candidati** su un altro annuncio: il task deve
   restare in coda, l'indicatore diventare **offline**, e il task partire da solo alla
   riaccensione.
