# Architettura

> Documento di riferimento sulle scelte tecniche. Per la suddivisione in fasi e
> sottofasi vedi [ROADMAP.md](./ROADMAP.md).

## 1. Cosa fa il sistema

Ogni giorno raccoglie annunci di lavoro da più portali, li confronta con il CV di
Filippo Nembrini, li presenta in una tabella ordinata per compatibilità e — con un
click — genera un CV su misura per quel singolo annuncio e invia la candidatura,
automaticamente dove l'ATS lo consente e in modo assistito altrove.

```
[1 INGEST] -> [2 NORMALIZE + DEDUP] -> [3 ENRICH] -> [4 MATCH] -> [5 DASHBOARD]
                                                                       |
                                                  [6 TAILOR CV] -> [7 APPLY] -> [8 TRACK]
```

Gli stadi 1-4 girano una volta al giorno senza intervento umano.
Gli stadi 6-7 partono dal bottone **Candidati**.

## 2. Due vincoli di realtà

Sono i due fatti che hanno determinato quasi tutte le scelte successive.

### 2.1 LinkedIn e Indeed non hanno API gratuite

LinkedIn espone soltanto la Talent Solutions API, riservata ai partner. Indeed ha
chiuso la Publisher API nel 2023. Le uniche due strade sono:

| Strada | Valutazione |
|---|---|
| Aggregatore che indicizza Google for Jobs (JSearch/RapidAPI) | **Scelta.** Legale, contiene gli annunci pubblicati su LinkedIn/Indeed/Glassdoor, free tier limitato |
| Scraping diretto di LinkedIn | **Scartata.** Viola i ToS, rischio concreto di ban dell'account, anti-bot e CAPTCHA |

Conseguenza pratica: la copertura di LinkedIn è quella che **Google ha indicizzato**,
non il 100% del portale. Le job board degli ATS restano la fonte con i dati migliori.

### 2.2 Su Vercel non può girare tutto

Le funzioni serverless hanno filesystem effimero, bundle limitato a ~250 MB e timeout
di pochi minuti. Non ci stanno:

- **Playwright/Chromium**, che serve sia per generare il PDF sia per l'apply assistito
- gli **embedding ONNX locali** (runtime + modello)
- una **pipeline** che macina centinaia di annunci con chiamate LLM

E soprattutto: l'apply assistito è *headful* per definizione. Un browser che devi
guardare mentre compila un form non può girare su un server.

Da qui l'architettura **split**: interfaccia in cloud, lavoro pesante in locale.

## 3. Topologia

```
   +------------------- VERCEL (pubblico, sempre online) -------------------+
   |  Next.js 16 App Router · Auth.js/Google · TanStack Table               |
   |  Route handlers: leggono i match, scrivono task nella coda             |
   +-------------------------------+---------------------------------------+
                                   | TLS
   +-------------------------------v---------------------------------------+
   |  SUPABASE (region EU)                                                 |
   |  Postgres  ·  Storage (PDF, bucket privato con signed URL)            |
   +-------------------------------^---------------------------------------+
                                   | TLS
   +-------------------------------+---------------------------------------+
   |  WORKER — PC Windows di casa (Python 3.12)                            |
   |  APScheduler: pipeline giornaliera                                    |
   |  Consumer della coda: genera CV, invia candidature                    |
   |  Playwright Chromium · fastembed ONNX · Claude API · SMTP/IMAP        |
   +-----------------------------------------------------------------------+
```

### Cosa funziona sempre, anche a PC spento

Consultare la dashboard, filtrare, ordinare, leggere le job description, mettere in
shortlist, scaricare CV già generati, cambiare le impostazioni.

### Cosa richiede il worker acceso

La run giornaliera, la generazione di un nuovo CV, l'invio di una candidatura.

Premendo **Candidati** a PC spento il task resta in coda ed esegue al prossimo avvio.
La UI mostra sempre in testata un indicatore **worker online / offline · ultimo
contatto N minuti fa**: non deve mai esserci ambiguità su cosa stia succedendo.

## 4. Ponte UI <-> worker

Coda su Postgres. Nessuna infrastruttura aggiuntiva: niente Redis, niente broker.

| Passo | Chi | Cosa |
|---|---|---|
| 1 | Next.js | `INSERT` in `task` (type, payload, status = pending) |
| 2 | worker | polling ogni 30 s: `SELECT ... FOR UPDATE SKIP LOCKED`, poi status = running |
| 3 | worker | esegue, aggiorna `progress`, chiude con status done/failed + `result` |
| 4 | Next.js | la UI fa polling sul task e mostra l'avanzamento |

`FOR UPDATE SKIP LOCKED` garantisce che nessun task venga preso due volte, anche se un
giorno ci fossero più worker in parallelo. Il worker scrive una riga `worker_heartbeat`
ogni 30 s: è quella che alimenta l'indicatore online/offline.

Latenza attesa fra click e inizio esecuzione: **entro 30 secondi**.

## 5. Scelte tecniche e motivazioni

### Next.js invece di Vite/SPA

Serve rendering lato server per due motivi non negoziabili: Auth.js richiede un backend
per il flusso OAuth, e la connection string del database non deve mai finire nel bundle
del browser. I route handler di Next sostituiscono quella che sarebbe stata un'API
separata, quindi il conto totale dei pezzi in movimento scende.

### Supabase invece di Neon + Vercel Blob

Un solo servizio copre **Postgres** e lo **storage dei PDF**, con region EU selezionabile
(si tratta del CV e dei dati personali di Filippo) e signed URL nativi. Con una run
giornaliera il progetto free non va mai in pausa.

- Vercel si connette tramite il pooler **Supavisor**: le funzioni serverless aprono e
  chiudono connessioni continuamente, e una connessione diretta esaurirebbe il pool
- il worker usa la **connessione diretta**, essendo un processo long-running con poche
  connessioni stabili

### Python 3.12 nel worker, non 3.14

Le dipendenze native del progetto — `onnxruntime`, `pypdfium2`, `lxml` — hanno wheel
Windows stabili su 3.12. Su 3.14 la copertura è ancora incerta e un fallimento di build
qui blocca tutto il resto. Non vale la pena rischiarlo per una versione più recente che
a questo progetto non porta alcun vantaggio.

### Playwright per il PDF, non WeasyPrint

Su Windows WeasyPrint richiede GTK e l'installazione è notoriamente fragile. Playwright
serve comunque per l'apply assistito: usarlo anche per il rendering PDF significa una
dipendenza pesante invece di due.

### fastembed (ONNX su CPU) con `intfloat/multilingual-e5-small`

384 dimensioni, ~120 MB, **multilingua** — essenziale con annunci misti IT/EN/DE. Gira
su CPU senza toccare la GPU da 4 GB, che non basterebbe comunque per un LLM decente.

I vettori stanno come `bytea` in Postgres e vengono caricati in un array numpy dal
worker: sotto i 10.000 annunci il cosine brute-force è istantaneo. Nessuna estensione
vettoriale da installare e mantenere.

### Claude API: due modelli per due lavori diversi

| Modello | Uso | Perché |
|---|---|---|
| `claude-haiku-4-5-20251001` | estrazione requisiti dalla JD, scoring rubrica | alto volume, basso costo; gira di notte via **Message Batches API** con il 50% di sconto |
| `claude-opus-5` | riscrittura del CV | basso volume, qualità massima: è il documento che ti rappresenta |

**Prompt caching** sul `MasterProfile`, che è identico in tutte le chiamate di tailoring.

### Alembic è l'unica fonte di verità dello schema

I modelli SQLAlchemy nel worker definiscono lo schema; Alembic genera e applica le
migration. Il lato Next.js usa **Drizzle in sola introspezione** (`drizzle-kit pull`)
per generare i tipi TypeScript dal database reale.

Risultato: un solo posto dove si cambia una colonna, e nessuna possibilità di drift fra
i due linguaggi.

## 6. Modello dati

| Tabella | Contenuto |
|---|---|
| `profile` | riga singola: MasterProfile JSON, file CV originale, embedding |
| `candidate_profile` | anagrafica + risposte standard ai form ATS: telefono, LinkedIn, GitHub, work authorization, preavviso, RAL attesa |
| `source` | adapter, enabled, riferimento chiave API, rate limit, ultima run |
| `job` | annuncio canonico: titolo, azienda, luogo, work_mode, RAL min/max/valuta/periodo, tipo contratto, seniority, description raw e pulita, lingua, url, apply_url, ats_type, ats_board_token, ats_job_id, posted_at, fetched_at, content_hash, embedding |
| `job_source_link` | N:1 su `job` — stesso annuncio visto da più fonti |
| `job_requirements` | estratto LLM: must_have[], nice_to_have[], tech_stack[], anni esperienza, lingue[], remote_policy, red_flags[] |
| `match` | job_id, score 0-100, subscores JSON, rationale, gaps[], status: new/seen/shortlist/hidden/applied |
| `application` | match_id, tier, status, cv_storage_path, cover_letter_path, submitted_at, ats_response, screenshots[] |
| `application_event` | timeline: created / submitted / email_received / interview / rejected |
| `task` | **coda UI verso worker**: type, payload, status, progress, result, error, created_at, claimed_at |
| `worker_heartbeat` | last_seen, versione, esito ultima run |
| `run` | log della run giornaliera per fonte: fetched, new, errors, durata |
| `settings` | chiave/valore: notifiche on/off, orario, soglia match, cap giornaliero, dry-run |

## 7. Algoritmo di matching — imbuto a 3 stadi

Il punto dell'imbuto è il costo. Mandare 500 annunci al giorno a un LLM è insostenibile;
mandarne 40 no. Ogni stadio scarta il più possibile usando il metodo più economico
disponibile a quel livello.

```
STADIO 0 — HARD FILTER          (SQL, costo zero)                ~500 -> ~150
  esclude: lingua non parlata, work authorization mancante, seniority fuori
  range +/-1, location fuori dai mercati scelti, contratto escluso, azienda in
  blocklist, annuncio gia' visto o gia' candidato

STADIO 1 — SEMANTIC             (embedding locale, costo zero)   ~150 -> 40
  cosine(profile_emb, job_emb)  su testo normalizzato
  + BM25/rapidfuzz su skill keywords   <- cattura i match esatti di tecnologia
    che l'embedding da solo diluisce
  score_ibrido = 0.6*cosine + 0.4*bm25_norm

STADIO 2 — RUBRICA LLM          (Haiku, Batch API)               40 -> score finale
  must_have_coverage    40%
  nice_to_have          10%
  seniority_fit         15%
  domain/industry_fit   10%
  work_mode + location  15%
  salary_fit            10%   <- neutro quando la RAL non e' dichiarata
  output: score 0-100 + rationale in 2 righe + gaps[]
```

Perché lo Stadio 1 è ibrido e non solo embedding: un annuncio che chiede *Kubernetes* e
un CV che lo cita hanno un match lessicale esatto che il cosine su testo lungo
diluisce. BM25 lo recupera.

I pesi dello Stadio 2 si tarano con `scripts/calibrate.py` su 20-30 annunci etichettati
a mano.

## 8. Deduplicazione

Chiave canonica: `normalize(company) + normalize(title) + normalize(city)`.

In caso di collisione si confronta il **SimHash** della description, soglia 0.85. Se
combaciano è lo stesso annuncio: si tiene un solo `job` e si aggiunge un
`job_source_link`.

Come `apply_url` vince **sempre** il link ATS diretto (Greenhouse/Lever/Ashby) su quello
dell'aggregatore: è l'unico che abilita l'invio automatico.

## 9. Generazione del CV

Il system prompt è quello fornito da Filippo (career coach / executive resume writer /
ATS specialist, framework Action-Context-Result, **divieto assoluto di inventare**), con
output strutturato in `top_keywords[5]`, `summary` da 45-60 parole, `experience[]` e
`skills{hard, soft}`.

Tre vincoli implementati come codice, non come raccomandazioni al modello:

1. **Validatore anti-invenzione** — ogni bullet e ogni skill deve risalire a una entry
   del `MasterProfile`. Le violazioni bloccano il render e forzano la rigenerazione. È
   il guardrail che rende il sistema usabile senza rileggere tutto ogni volta.
2. **Fit a una pagina** — loop render, conteggio pagine, e se sono più di una si chiede
   all'LLM di comprimere (tagliare i bullet meno rilevanti, accorciare il summary), al
   massimo 3 iterazioni. Solo in extremis si riducono interlinea e margini, entro soglie
   che restano leggibili.
3. **Template ATS-safe** — colonna singola, nessuna tabella, icona o layout
   multi-colonna, font standard, heading canonici (Experience, Skills, Education). I
   parser ATS sbagliano su tutto il resto.

Naming: `resumes/{job_id}/Filippo_Nembrini_Resume.pdf` su Supabase Storage. Una cartella
per annuncio, così il nome visibile del file è **sempre lo stesso** senza mai
sovrascrivere il CV di un'altra candidatura.

Lingua del CV determinata dalla lingua della job description (it/en/de/es/fr).

## 10. Router della candidatura

| Tier | Quando | Comportamento |
|---|---|---|
| **A — automatico** | `ats_type` fra greenhouse, lever, ashby, workable | il worker fa POST all'endpoint pubblico della board, PDF in multipart, risposta salvata |
| **B — assistito** | tutto il resto con form raggiungibile | Playwright **headful** sul PC: precompila i campi noti, **si ferma prima del submit**, notifica "pronto da rivedere", screenshot salvato |
| **C — manuale** | form non automatizzabile o dietro login | apre l'URL, crea un task da fare a mano |

### Guardrail non negoziabili

- **dry-run globale** attivo al primo avvio
- **cap giornaliero** configurabile, default 10 candidature
- **conferma esplicita** alla prima candidatura verso ogni nuova azienda
- **idempotenza**: lo stesso annuncio non può partire due volte
- **nessun aggiramento** di CAPTCHA o sistemi anti-bot

## 11. Sicurezza

La dashboard è su internet e contiene il CV, i dati personali e un bottone che invia
candidature a nome di Filippo. Requisiti minimi:

- **Auth.js + Google OAuth con allowlist di una sola email.** Il callback rifiuta ogni
  account diverso; chiunque altro apra l'URL vede solo il login. Middleware Next.js su
  ogni rotta tranne `/login`.
- **Connection string e service key mai nel bundle client**: solo server component e
  route handler, variabili senza prefisso `NEXT_PUBLIC_`.
- **Bucket PDF privato**, servito esclusivamente con signed URL a scadenza breve. Mai
  URL pubblici, neanche con la scusa che tanto non sono indicizzati.
- **Rate limiting** sui route handler che creano task, così un bug nella UI non può
  accodare 200 invii.
- **Region EU** su Supabase, trattandosi di dati personali.
- Segreti in `.env` git-ignored lato worker, Environment Variables lato Vercel.
- Vercel piano Hobby: uso personale e non commerciale, questo caso rientra.

## 12. Rischi noti e mitigazioni

| Rischio | Mitigazione |
|---|---|
| **Il PC spento blocca CV e candidature** | Indicatore online/offline sempre visibile, task in coda che partono al riavvio, digest che dice quando è stata l'ultima run. Il worker è scritto 12-factor: spostarlo su un container da ~5€/mese è mezza giornata di lavoro |
| JSearch free tier stretto (~6 chiamate/giorno) e copre solo ciò che Google indicizza | Query batchate e prioritizzate; le board ATS restano la fonte primaria; l'upgrade a pagamento è una scelta successiva, non un prerequisito |
| Dati personali su servizi terzi | Region EU, bucket privato con signed URL, auth a singolo account, nessun dato in URL o query string |
| `onnxruntime` / `fastembed` senza wheel su Windows | Motivo per cui si usa Python 3.12; fallback su embedding API (Voyage) dietro la stessa interfaccia |
| Gli endpoint di apply degli ATS cambiano senza preavviso | Test di contratto per adapter; il fallimento del Tier A degrada automaticamente a Tier B |
| `MasterProfile` estratto male avvelena tutto a valle | Revisione manuale obbligatoria in Fase 1.3 prima di procedere |
| Free tier Supabase/Vercel esauriti o in pausa | Con una run giornaliera Supabase non va mai in pausa; il consumo si monitora in Fase 10.2 |
| Gmail IMAP/SMTP richiede 2FA + App Password | Documentato nel README; il tracking automatico è l'ultima fase e non blocca nulla |

## 13. Layout del repository

```
Job Board/
  worker/                    Python 3.12 — tutto il lavoro pesante
    jobboard/
      main.py, config.py, db.py, scheduler.py, queue.py, cli.py
      models/                SQLAlchemy — fonte di verita' dello schema
      sources/               base.py + un modulo per adapter
      pipeline/              ingest, normalize, dedup, enrich, match
      ai/                    client, embeddings, validator, prompts/
      cv/                    templates/, render.py, fit.py
      apply/                 router, greenhouse, lever, ashby, workable, assisted
      notify/                email_digest, imap_reader, classifier
    alembic/
    pyproject.toml
  web/                       Next.js 16 -> Vercel
    app/(auth)/, app/(dash)/, app/api/
    db/schema.ts             generato da drizzle-kit pull
    components/
  docs/                      questo documento + ROADMAP.md
  scripts/                   calibrate.py e utility one-off
```
