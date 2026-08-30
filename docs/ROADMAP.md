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
- [x] Creare un progetto **Supabase** gratuito, region `eu-central-1` (Francoforte).
      Annotare: connection string diretta, connection string pooler, project URL, service role key.
- [x] Creare nel progetto Supabase un bucket Storage **privato** chiamato `resumes`.
- [ ] Creare un account **Vercel** e collegarlo al repository.
- [x] Creare credenziali **Google OAuth** su Google Cloud Console (tipo "Web application"),
      con redirect URI `https://<dominio-vercel>/api/auth/callback/google`.
- [ ] Ottenere una **API key Anthropic** su console.anthropic.com (a consumo, separata
      dall'abbonamento Claude Code).
- [x] Registrare le chiavi gratuite delle fonti: **Adzuna** (app id + key), **Jooble**,
      **RapidAPI** per JSearch.
- [ ] **Iscriversi alla API JSearch su RapidAPI**, piano Basic (gratuito, ~200 chiamate
      al mese): [rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)
      → *Subscribe to Test*. Su RapidAPI la chiave dell'account e l'abbonamento alla
      singola API sono due cose separate: con la chiave e senza iscrizione la fonte
      risponde `403 You are not subscribed to this API`. **È l'unico passo che manca
      per vedere gli annunci LinkedIn e Indeed in tabella.**
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
- [x] **3.7** Riserva per le fonti a budget: `stage2_top_n` 40 → 100, e
      `stage2_reserved_floor` (default 10) garantisce agli annunci di una fonte con un
      tetto di chiamate (oggi JSearch/LinkedIn) un minimo di posti allo Stadio 2 anche
      quando il loro punteggio ibrido da solo non basterebbe a competere con l'arretrato
      delle fonti senza tetto. La riserva è tolta dal totale, non aggiunta sopra: il costo
      di una run resta prevedibile.

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

> **Il tetto condiviso che teneva fuori LinkedIn (3.7, molto più tardi di questa fase).**
> Filippo ha segnalato pochissimi annunci LinkedIn in dashboard nonostante una ricerca
> manuale su LinkedIn stesso ne trovasse molti di più. La causa non era il budget di
> JSearch (~6 chiamate/giorno, invariato): `stage2_top_n` è un tetto **unico e condiviso
> da tutte le fonti insieme**, applicato all'intero arretrato non ancora valutato — non
> "quaranta al giorno fra i nuovi di oggi". JSearch è l'unica delle otto fonti con un
> `daily_call_budget`; le altre sette non ne hanno, riempiono l'arretrato molto più in
> fretta, e i pochi annunci LinkedIn perdevano quasi sempre quella competizione. La
> riserva di 3.7 garantisce un minimo indipendente dal punteggio ibrido.

**Resta aperto:** i punteggi non superano 65 perché `location_fit` e `salary_fit` restano
neutri finché `candidate_profile.json` non dichiara lingue, autorizzazione al lavoro e
RAL attesa. Con `MATCH_THRESHOLD=65` passa un annuncio solo.

---

## Fase 4 — Dashboard pubblica su Vercel · 2 gg

- [x] **4.1** **Auth.js + Google OAuth**, allowlist a una sola email, e **due** livelli di
      protezione: `src/proxy.ts` reindirizza chi non ha un cookie, `src/lib/dal.ts`
      verifica la sessione accanto ai dati. Il secondo non è ridondanza: il proxy gira
      anche sulle rotte prelevate in anticipo dal browser, quindi legge solo il cookie e
      non può interrogare il database.
- [x] **4.2** Route handler `GET /api/matches` con filtri, ordinamento e paginazione
      **lato Postgres**. Il primo caricamento della dashboard non ci passa: lo fa un
      server component che legge dal database senza far fare a Next una richiesta HTTP
      verso sé stesso.
- [x] **4.3** Tabella **Ruolo · Azienda · Luogo · Modalità · RAL · Tipo · Match % · Fonte ·
      Azioni**, renderizzata dal server. Niente TanStack Table: con ordinamento e filtri
      su Postgres resterebbe solo la definizione delle colonne, in cambio di una tabella
      interamente client.
- [x] **4.4** Badge per modalità e fascia di punteggio; **RAL "n.d." quando non
      dichiarata**, mai la stima. Le soglie delle fasce sono basse di proposito: con più
      criteri della rubrica a 50 — il valore che significa "non ci sono elementi per
      giudicare" — un annuncio buono si ferma sotto 70.
- [x] **4.5** Filtri: soglia, modalità, paese, fonte, solo nuovi, shortlist, nascondi già
      visti. Vivono nella query string e non in uno stato React, così un elenco filtrato
      è un URL che si può mandare al telefono e il tasto "indietro" fa quel che deve.
- [x] **4.6** Drawer di dettaglio: rubrica con i pesi, motivazione, **gap evidenziati**,
      requisiti estratti, annuncio integrale. Aperto da `?open=<id>`, quindi il tasto
      "indietro" del telefono lo chiude.
- [x] **4.7** Azioni di riga: shortlist, nascondi, apri. Aprire un annuncio lo segna come
      visto da solo. `applied` non è assegnabile dalla UI: lo scrive il worker quando una
      candidatura parte davvero.
- [x] **4.8** Su mobile la tabella diventa lista di card, commutata dalle media query e
      non da JavaScript: niente da idratare e nessun salto di layout.
- [ ] **4.9** Deploy in produzione e verifica che il login respinga ogni altro account
      Google. **Serve una credenziale OAuth da Google Cloud Console**, che è di Filippo.

**Verifica:** eseguita in locale sulla build di produzione, con i 153 match veri. La
tabella mostra i punteggi ordinati, i filtri girano su Postgres (`mode=remote` 19,
`min=50` 7, `mode=remote&min=40` 5), la paginazione tiene, il drawer mostra rubrica e
gap, il `PATCH` cambia stato e rifiuta `applied`. Senza sessione: le pagine
reindirizzano al login, le API rispondono `401 {"error":"non autorizzato"}`.

> **Due bug che solo l'esecuzione poteva far emergere.**
>
> Il driver `postgres` (postgres-js) sotto Next.js 16 serve **una sola richiesta** e poi
> smette: la prima query risponde in 150 ms, dalla seconda la connessione riutilizzata
> non restituisce più niente. Nessun errore, nessun timeout — la richiesta si chiude solo
> quando è il browser a rinunciare, e da fuori sembra un database lento. Identico in
> sviluppo e in produzione. Fuori da Next lo stesso client fa quattro query di fila senza
> un intoppo. Sostituito con `pg`: 164 ms la prima, 18 ms le successive.
>
> E `pg`, senza configurazione TLS esplicita, si collega **in chiaro** — la connection
> string di Supabase non contiene `sslmode`. Il CV, i dati personali e ogni query
> attraversavano internet senza cifratura. Con la sola `rejectUnauthorized` la
> connessione invece fallisce, perché la catena si chiude su una CA privata di Supabase:
> il certificato radice è ora fissato in `src/db/supabase-ca.ts`, verificato byte per byte contro quello scaricato dalla dashboard Supabase.

---

## Fase 4bis — Sezione CV, tipografia, prestazioni

Lavori chiesti a Fase 4 conclusa, tutti verificati in locale sui dati veri.

- [x] **4b.1** **Sezione CV** (`/cv`): quale CV è caricato, sostituzione, rimozione con
      conferma digitata, e download dell'originale via signed URL.
- [x] **4b.2** **Editor del `MasterProfile`**: contatti, presentazione, esperienze con i
      punti scomposti in ACR, formazione, progetti, certificazioni, competenze, lingue.
      Aggiunta, modifica ed eliminazione di ogni voce, con validazione Zod che rispecchia
      il Pydantic del worker — il round trip dashboard → JSONB → `model_validate` è
      stato verificato sul profilo vero.
- [x] **4b.3** **Scala tipografica ridefinita** (~+7% su ogni gradino, interlinee
      rialzate) e tabella respirabile: padding orizzontale su ogni cella, larghezza
      minima che fa scorrere invece di comprimere, numeri in monospaziato a larghezza
      fissa. Il tema scuro ora segue davvero il sistema: la variante `dark:` rispondeva
      a una classe che nessuno applicava.
- [x] **4b.4** **Dettaglio annuncio come rotta intercettata** (`/annuncio/<id>` +
      slot `@drawer`): aprire un annuncio non rinaviga più la lista, quindi non
      riesegue le sue tre query. Con `loading.tsx` la rotta torna anche prefetchabile.
- [x] **4b.5** Colonna **Fonte** con il nome del portale (`publisher`) invece dello slug
      dell'adapter, filtro per portale, e `jsearch` acceso.

---

## Fase 5 — Ponte UI verso worker · 0.5 gg

- [x] **5.1** Tabella `task` e enum dei tipi: `generate_cv`, `apply`, `run_pipeline`, `reparse_profile`
- [x] **5.2** Consumer nel worker (`jb work`) con `FOR UPDATE SKIP LOCKED`, polling
      configurabile, retry fino a `max_attempts` ed errori persistiti. Anticipato dalla
      Fase 5 perché senza di lui il bottone "Sostituisci" della pagina CV accoderebbe
      un lavoro che nessuno esegue.
- [x] **5.3** `worker_heartbeat` scritto ogni 30 s dal consumer; l'indicatore in testata
      c'era già dalla Fase 4 e ora ha qualcosa da leggere.
- [x] **5.4** Componente di progresso generico (`TaskProgress`): in coda / in corso /
      fatto / errore, uno per tutti i tipi di task. Le quattro frasi difficili sono
      sempre le stesse — «in coda a worker spento non è un errore», «un tentativo
      fallito che tornerà in coda non è un fallimento» — e scritte due volte
      divergerebbero alla prima correzione. Lo usano la pagina CV e la dashboard.
- [x] **5.5** Bottone **"Aggiorna adesso"** che accoda `run_pipeline`, con l'ora
      dell'ultima raccolta accanto. Il polling interroga `/api/tasks`, non ricarica la
      pagina: la dashboard fa cinque query e rifarle ogni quattro secondi per muovere una
      barra sarebbe un carico ricorrente su Supabase. Il ricaricamento vero avviene **una
      volta**, a lavoro concluso, quando c'è davvero qualcosa di nuovo da mostrare. Una
      scheda in secondo piano smette di interrogare.
- [x] **5.6** Gestore `run_pipeline` nel worker: raccolta e poi matching, in **due
      transazioni distinte** — tenerne una sola aperta per i cinque minuti della rubrica
      LLM significherebbe un lock su Supabase per tutto quel tempo e il battito che non
      riesce a scriversi, cioè l'indicatore in testata che dice "offline" proprio mentre
      il worker lavora. A fine run scrive `worker_heartbeat.last_run_at` e
      `last_run_status`, che erano colonne mai popolate.
- [x] **5.7** `TaskError(definitivo=True)`: un errore che non può cambiare esito non
      torna in coda. Su `run_pipeline` il ritentativo rifà l'intera raccolta, e il piano
      JSearch è di ~200 chiamate al mese.

**Verifica:** eseguita end-to-end su Postgres locale con le migration vere.
Premendo il bottone viene inserita **una** riga `run_pipeline` (una seconda pressione da
un altro dispositivo non ne aggiunge una copia), il bottone si spegne e compare
"Raccolta in coda". Muovendo il task a `running` la barra segue l'avanzamento senza
ricaricare la pagina — `remotive (3/9) 22%` → `stadio 2: 12/40 71%` — e alla conclusione
si riaccende il bottone e compare il riepilogo *"7 annunci nuovi · 31 valutati · 2 sopra
la soglia di 65"*. `jb work --once` su un profilo mancante chiude il task come `failed`
con **un solo tentativo** e `last_run_status = partial`; lo stesso errore su un guasto di
rete lo lascia `pending` con `attempts = 1`. Un successo sparisce dalla UI dopo 30
minuti, un errore resta 24 ore.

---

## Fase 6 — Generazione CV su misura · 2 gg

- [~] **6.1** Prompt in `ai/prompts/cv_writer.md` (career coach / executive resume
      writer / ATS specialist, framework ACR, divieto assoluto di inventare), con output
      strutturato `top_keywords[5]`, `summary`, `experience[]`, `skills{hard, soft}`.
      *Il testo "fornito" non è mai arrivato nel repository:* questo è scritto dalla
      specifica di ARCHITECTURE §9 e sta in un file a sé apposta perché sostituirlo sia
      un `git diff` e non una modifica al codice. **Dal modello passa solo la prosa**:
      date, aziende, titoli di studio e recapiti li copia il template dal `MasterProfile`
      e non entrano nemmeno nella richiesta.
- [x] **6.2** **Validatore anti-invenzione** (`ai/validator.py`): ogni bullet dichiara il
      `source_id` da cui viene, ogni competenza la `source`, e ogni cifra del testo
      generato deve comparire nella fonte. Le violazioni bloccano il render; la
      rigenerazione riceve l'elenco degli errori invece di ripartire alla cieca.
- [x] **6.3** Template Jinja2 ATS-safe: colonna singola, nessuna tabella, icona o
      immagine, font di sistema, heading canonici per lingua, date numeriche.
- [x] **6.4** Render Playwright con **loop fit-a-una-pagina**: prima si taglia contenuto
      (max 3 compressioni), solo dopo si stringe interlinea e margini, entro tre gradini
      che restano leggibili. Ogni compressione ripassa dal validatore.
- [x] **6.5** Upload su Supabase Storage in `{job_id}/Filippo_Nembrini_Resume.pdf`, con
      `x-upsert` perché rigenerare deve sostituire, non fallire con 409.
- [x] **6.6** UI di preview nella pagina dell'annuncio: PDF via signed URL, **diff frase
      per frase** contro il CV master, le 5 keyword evidenziate nel testo, e i pulsanti
      Rigenera e Approva.
- [x] **6.7** Lingua del CV dedotta da `job.lang` (it/en/de/es/fr), con l'inglese come
      ripiego: è la lingua che ogni ATS europeo processa.
- [x] **6.8** Gestore `generate_cv` e comandi `jb cv generate` / `jb cv check`, che
      eseguono lo stesso codice: due strade non devono produrre due CV diversi.

**Verifica:** eseguita end-to-end su Postgres locale con le migration vere e un provider
LLM finto. Dal gestore `generate_cv` esce un PDF di **una pagina** con **1276 caratteri
estraibili**, heading riconosciuti da `jb cv check`, ordine cronologico inverso e
recapiti intatti dopo l'estrazione; la riga `application` esce `cv_ready` con percorso,
lingua e payload, e un evento `cv_generated` in timeline. In dashboard: il diff mostra
l'originale italiano accanto al riscritto inglese, Approva porta a `approved`, Rigenera
accoda `generate_cv` con `{"match_id": N}`, e il CV di un altro annuncio non compare su
questa pagina. Suite worker: **337 test**.

**Resta aperto:** il PDF non è ancora stato provato con un LLM vero — serve una
`GEMINI_API_KEY` valida e un profilo confermato — né caricato su Supabase, che richiede
le chiavi di Filippo. Il percorso è verificato fino all'upload compreso, con la chiamata
di rete sostituita.

---

## Fase 7 — Candidatura · 2.5 gg

> **Il Tier A non invia più via API.** Il piano qui sotto lo prevedeva; scritto il
> client contro la documentazione ufficiale delle quattro API, nessuna delle
> quattro permette una `POST` da un candidato esterno — Greenhouse la blocca con
> reCAPTCHA Enterprise, le altre tre richiedono una chiave che genera solo
> l'azienda. Il perché per esteso, con le fonti, è in `docs/ARCHITECTURE.md` §10.
> Tier A e B condividono ora lo stesso motore Playwright e si fermano entrambi
> prima del submit; cambia solo se il form si compila con selettori dedicati
> (A) o con un'euristica su label e attributi (B).

- [x] **7.1** Router per tier in base a `ats_type` **e** `apply_url` — `jobboard/apply/router.py`
- [x] **7.2** **Tier A**: selettori dedicati per Greenhouse / Lever / Ashby / Workable (`jobboard/apply/selectors.py`), piano di campi da `CandidateAnswers` + `MasterProfile` (`jobboard/apply/fields.py`), upload del PDF nel campo curriculum. **Non invia via API** — vedi la nota sopra
- [x] **7.3** **Tier B**: Playwright headful sul PC (`jobboard/apply/browser.py`), autofill euristico su label e attributi (`jobboard/apply/heuristics.py`), **stop prima del submit**, candidatura a `needs_human` con screenshot salvato su disco
- [x] **7.4** **Tier C**: nessun `apply_url` diretto — nessun browser, solo il link pronto da aprire a mano
- [x] **7.5** Guardrail (`jobboard/apply/guardrails.py`): dry-run globale (simula, non apre un browser), cap giornaliero sulle candidature **preparate** (non spedite — è l'azione automatica da limitare), conferma esplicita alla prima candidatura verso ogni azienda nuova (dialogo in dashboard, payload `confirmed_new_company`), idempotenza sul vincolo `UNIQUE` di `application.match_id`
- [x] **7.6** Timeline `application_event`: due voci nuove, `prepared` e `prepare_failed`, per il momento in cui il worker si ferma prima del submit; `submitted` la scrive solo `markApplicationSubmitted` in dashboard, con un click esplicito **dopo** l'invio vero nel browser

**Verifica fatta:** suite worker (337 → **377 test**, i 40 nuovi senza database né
browser reale — coprono router, piano dei campi, motore euristico, selettori
noti, guardrail), `ruff`, `mypy --strict` puliti. Lato web: `tsc --noEmit`,
`eslint` e `next build` puliti con i tipi generati da `next typegen`; la
migration del nuovo CHECK constraint è scritta ma non applicata a un database
vero in questo ambiente (nessuna credenziale Supabase qui).

**Resta aperto:** nessun selettore o euristica è stato provato contro un form
vero — serve un annuncio reale, uno schermo e il PC di Filippo acceso, che
questo ambiente non ha. Prima verifica end-to-end suggerita: approvare un CV,
premere "Invia candidatura" su un annuncio Greenhouse vero, controllare che il
browser si apra precompilato e fermo prima del submit, poi premere "Segna come
inviata" a mano dopo averla spedita davvero.

---

## Fase 8 — Run giornaliera e notifiche · 1 gg

- [x] **8.1/8.2** Raccolta automatica una volta al giorno, con recupero se il PC era
      spento all'ora prevista. *Non con APScheduler nel processo*: con **Windows Task
      Scheduler**, che orchestra due pezzi già scritti per l'occasione —
      1. `jb work --once` ripetuto ogni minuto, la stessa forma "che userebbe Task
         Scheduler" già documentata in tre punti del codice (`cli.py`, `queue.py`,
         `commands/worker.py`) ben prima di questa fase;
      2. `jb work trigger`, comando nuovo che accoda un `run_pipeline` — la stessa riga
         che accoda il bottone "Aggiorna adesso" — usando `queue.enqueue_task()`, lo
         specchio Python di `web/src/lib/tasks.ts::enqueueTask`: stessa deduplica, stesso
         motivo, cosi' un catch-up dopo il PC spento non raddoppia la raccolta se un run
         manuale era già in coda.

      Il "recupero se saltata" lo dà gratis l'opzione nativa di Task Scheduler ("esegui
      appena possibile se un avvio pianificato viene ignorato"): zero codice per quella
      parte. Risultato pratico identico a quanto descritto qui sopra, con zero dipendenze
      nuove — `apscheduler` resta in `pyproject.toml` inutilizzato, per ora. Il perché è
      in `ARCHITECTURE.md`.

      **Le due attività restavano da creare a mano** — il codice era pronto, ma
      compilare due schede di Task Scheduler è un passo che si rimanda. `setup-scheduler.cmd`
      alla radice le crea entrambe con un comando solo; resta manuale solo la spunta
      "esegui appena possibile se un avvio pianificato viene ignorato", che `schtasks`
      non espone da riga di comando (vedi `setup-scheduler.cmd` per il perché).

      **Il testo "PC di casa è spento" era fuorviante quando il PC era acceso** ma
      `jb work` non era mai partito: l'indicatore verifica un battito recente, non lo
      stato di alimentazione, e diceva un fatto diverso da quello che sapeva davvero.
      Corretto in `worker-status.tsx`, `cv-panel.tsx` e `task-progress.tsx` per parlare
      del worker, non del PC.
- [ ] **8.3** Digest email HTML via SMTP Gmail, con i nuovi match sopra soglia e link diretto alla riga sul sito Vercel
- [ ] **8.4** **Toggle notifiche on/off in UI** nella pagina Impostazioni, persistito in `settings`, insieme a soglia e orario
- [ ] **8.5** Pagina Run History: esiti, conteggi ed errori per fonte

**Verifica (8.1/8.2):** eseguita a mano su Postgres locale — `jb work trigger` due volte
di fila accoda **un solo** `run_pipeline` (la seconda chiamata trova quello in coda,
`enqueue_task` restituisce `gia_in_coda=True`); `jb work --once` lo prende ed esegue, fino
alla chiamata LLM (bloccata solo dal proxy di rete del sandbox usato per la verifica, non
un difetto del meccanismo). `ruff`, `mypy --strict` e la suite (337 test, invariata: la
funzione richiede un database vero per essere provata, e questo repository non aggiunge
test a database senza prima costruire la fixture) restano puliti.

**Verifica (8.3-8.5, non ancora fatte):** forzi una run dal telefono e la mail arriva;
spegni il toggle e non arriva più.

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
6. Approva il CV, poi premi **Invia candidatura** su un annuncio Greenhouse (Tier A):
   entro un minuto si apre sul PC un browser con il form precompilato, fermo prima
   del submit. Controllalo, premilo tu, poi torna sul telefono e premi **Segna come
   inviata**: solo a quel punto lo stato diventa "inviata" in tabella.
7. Spegni il worker e premi di nuovo **Invia candidatura** su un altro annuncio: il task
   deve restare in coda, l'indicatore diventare **offline**, e il task partire da solo
   alla riaccensione.
