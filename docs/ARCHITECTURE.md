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

**L'API cambia sotto i piedi, e in silenzio.** La v5 non è una revisione della
v1: endpoint diverso (`/search-v2`; il vecchio risponde `404`, non un redirect),
`data` passato da elenco a oggetto con dentro `jobs`, impaginazione a cursore.
E — cosa che si vede solo guardando una risposta vera — i campi strutturati
arrivano quasi sempre vuoti: su dieci annunci italiani, `job_country` era
valorizzato una volta sola e le due colonne con la data di pubblicazione zero.
Quello che c'è sempre è testo libero e localizzato: `job_location` («Ivrea TO •
tramite LinkedIn») e `job_posted_at` («4 giorni fa»). L'adapter legge quelli, e
`tests/test_jsearch.py` fissa la forma così che il prossimo cambio rompa un test
invece di una run notturna.

**Su RapidAPI la chiave e l'abbonamento sono due cose separate.** Una chiave valida
non dà accesso a niente finché non ci si iscrive alla singola API — anche al suo
piano gratuito. Finché l'iscrizione manca, JSearch risponde `403 You are not
subscribed to this API`, che manda a controllare la chiave, cioè l'unico posto dove
non c'è niente da sistemare. L'adapter traduce quel 403 nel comando da eseguire.

**Il nome del portale è un dato, non un dettaglio.** Adzuna, Jooble e JSearch non
pubblicano: ripubblicano. Sapere che un annuncio sta su LinkedIn e non su una board
Greenhouse cambia come ci si candida, quindi il publisher dichiarato
dall'aggregatore finisce in `job_source_link.publisher` ed è quello che si legge
nella colonna Fonte. È una colonna e non una lettura di `raw` perché la dashboard la
mostra su ogni riga di ogni pagina, e `raw` è un JSONB che Postgres dovrebbe
decomprimere per intero per estrarne una parola.

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
   |  Playwright Chromium · fastembed ONNX · Gemini API · SMTP/IMAP        |
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

### Ritentare non è sempre giusto (Fase 5.4)

Il criterio iniziale era uno solo: un task fallito torna in coda finché `attempts` non
raggiunge `max_attempts`. È corretto per un guasto passeggero — una API che risponde 503,
la rete di casa che cade a metà raccolta — e sbagliato per tutto il resto: un profilo non
ancora confermato non si conferma da solo fra un tentativo e l'altro, e un PDF fatto di
scansioni non diventa testo al secondo passaggio. In entrambi i casi il ritentativo
riscrive lo stesso errore due volte in più e basta.

Con `run_pipeline` smette di essere gratis: **ogni presa rifà la raccolta**, e il piano
JSearch è di circa 200 chiamate al mese. Tre tentativi su un errore che non può cambiare
esito costerebbero il triplo delle chiamate per lo stesso identico messaggio finale.

Da qui `TaskError(..., definitivo=True)`, che spegne il ritentativo per gli errori che il
codice sa già essere definitivi. Tutto il resto — comprese le eccezioni non previste —
resta ritentabile, che è il comportamento giusto quando non si sa.

### Un task `running` sopravvive al worker che lo teneva

`serve()` intercetta il primo Ctrl+C e aspetta la fine del task in corso apposta per non
lasciare una riga a metà; un secondo Ctrl+C forzato, la finestra chiusa a mano o il PC
spento durante una generazione bypassano quella cautela senza passare da nessun gestore
d'eccezione. Il task resta `running` per sempre: nessun processo lo riprenderà, e in
dashboard è indistinguibile da un lavoro ancora in corso — una barra ferma al 20%, non un
errore da leggere.

È il task 14 dell'1 settembre 2026: Gemini ha risposto **503 "high demand"** al primo
tentativo di `generate_cv`, `tenacity` lo ha ritentato in silenzio (nessun log fra un
tentativo e l'altro, per progettazione — vedi sopra), il tentativo ripetuto ha impiegato
un'altra quarantina di secondi a rispondere, e in quella finestra di silenzio totale,
subito dopo un WARNING innocuo dell'SDK Gemini sulla "automatic function calling" (rumore
che l'SDK stampa a ogni chiamata, comprese quelle riuscite), il processo è stato
interrotto da fuori. Risultato: un task orfano senza una riga di errore da nessuna parte,
e senza il WARNING a fare da falso indiziato nessuno l'avrebbe cercato lì.

Due correzioni, non una:

1. **`ai/client.py` logga anche durante l'attesa fra un tentativo e l'altro**
   (`before_sleep` di `tenacity`), cosa che prima non succedeva mai — un errore transitorio
   produceva fino a ~30 secondi di silenzio totale nel log, indistinguibile da un blocco.
   Silenziato anche il WARNING dell'SDK sulla AFC: non riguarda mai questo codice, che non
   passa mai `tools` a `generate_content`.
2. **`queue._recupera_orfani()`** gira a ogni `run_once()` — quindi sia dentro `serve()`
   sia a ogni tick di `jb work --once` da Task Scheduler — e rimette in coda (o fallisce,
   secondo `attempts`, la stessa `_fallisci` di un errore qualsiasi) ogni task `running` da
   più di **un'ora** (`TASK_ORFANO_DOPO`). La soglia è larga apposta: deve restare sopra il
   tempo di un `run_pipeline` con `--rescore` su un database accumulato da settimane, non
   solo sopra "un buon cinque minuti" della rubrica in un giro normale. `jb doctor` lo
   segnala anche prima che scatti da solo.

### La deduplica in coda sta nel database, non nel bottone

Il bottone "Aggiorna adesso" si disabilita mentre una raccolta è aperta, ma quella è una
difesa che vale per una sola scheda. Il caso vero sono due dispositivi — il telefono in
mano e il portatile aperto — o la stessa pagina riaperta a worker spento, dove il tasto
premuto una seconda volta è un gesto ragionevole perché non è successo ancora niente.

`enqueueTask` scarta quindi un accodamento se ne esiste già uno **dello stesso tipo e con
lo stesso payload** in `pending` o `running`. Che il payload conti è il punto: due
`run_pipeline` chiedono la stessa cosa e la seconda è sprecata, mentre due
`reparse_profile` nominano due file diversi e scartare il secondo vorrebbe dire ignorare
in silenzio il CV appena caricato. Il confronto è fra `jsonb`, quindi l'ordine delle
chiavi non conta.

### La raccolta automatica gira su Task Scheduler, non su APScheduler nel processo

Il piano originale (Fase 8.1) prevedeva un APScheduler interno al worker per la run
giornaliera. Costruendo la Fase 5 il codice aveva già preso un'altra strada, in tre
commenti separati (`cli.py`, `queue.py`, `commands/worker.py`): `jb work --once` è
esplicitamente "la forma che userebbe Task Scheduler", pensato fin dall'inizio per essere
invocato a ripetizione da uno scheduler esterno invece che restare in ascolto in un
processo lungo. Un APScheduler nel processo avrebbe duplicato una responsabilità che
Windows offre già gratis, e in modo più affidabile: sopravvive al riavvio del PC senza che
nessuna riga di Python debba occuparsene.

Mancava solo un modo per accodare un `run_pipeline` **da fuori**, senza eseguirlo sul
posto: `jb ingest --commit && jb match --commit` avrebbe fatto il lavoro, ma bypassando la
coda avrebbe anche bypassato tutto quello che la coda porta con sé — `progress`,
`worker_heartbeat.last_run_at`, la barra della dashboard. `jb work trigger` chiude quel
buco in una riga: chiama `queue.enqueue_task()`, lo specchio Python della deduplica appena
descritta per `enqueueTask`, e lascia che sia `jb work` a eseguire — la stessa strada del
bottone "Aggiorna adesso", non una nuova.

Il risultato pratico è lo stesso della Fase 8.1/8.2 originale, "esegui appena possibile se
saltata" compreso — quella parte la dà gratis l'opzione nativa di Task Scheduler, zero
codice. `apscheduler` resta come dipendenza dichiarata in `pyproject.toml`, non rimossa,
ma resta anche inutilizzata: la Fase 8.3 (sotto) non ne ha avuto bisogno.

**Il codice pronto non basta se le attività restano da creare a mano.** Fra Fase 8.1/8.2 e
il primo uso vero è passato del tempo in cui `jb work` non ha mai girato sul PC di
Filippo — non un difetto del meccanismo, solo le schede di Task Scheduler compilate a mano
che si rimandano. `setup-scheduler.cmd` alla radice (stesso stile di `jb.cmd`/`web.cmd`:
niente script PowerShell, `%~dp0` per il percorso assoluto, sicuro da rilanciare) crea tre
attività con `schtasks /create /f` — il consumer (`jb work --once` ogni minuto), il trigger
giornaliero (07:00) e, da Fase 10.3, il backup notturno (03:00).

**Un'attività disabilitata non produce un errore da nessuna parte — è già successo per
davvero.** `JobBoard - worker` è rimasto disabilitato per un giorno e mezzo: non per un
guasto che qualcosa avesse registrato (il log Operational di Task Scheduler è spento di
default e non conserva nulla), semplicemente disattivato e mai riacceso. In quel tempo la
coda ha continuato ad accettare normalmente i task dei bottoni della dashboard — nessun
errore all'accodamento, nessuna riga rossa — ma nessun processo li raccoglieva più.
L'unico sintomo in dashboard era il pallino offline, e "il PC è spento" e "l'attività è
disabilitata" ci arrivano identici mentre solo il secondo richiede di aprire Task
Scheduler invece di aspettare che qualcuno lo riaccenda. Da qui `jobboard doctor`, che ora
controlla anche questo — stesso principio già applicato a Playwright e all'embedding: un
prerequisito silenzioso deve emergere da un comando diagnostico, non da una pipeline
notturna che fallisce senza lasciare testimoni.

**La spunta "esegui appena possibile se un avvio pianificato viene ignorato" non è più un
passo manuale.** La versione precedente di questa nota diceva che andava spuntata a mano
perché `schtasks.exe` da riga di comando non la espone e automatizzarla avrebbe richiesto
un XML di Task Scheduler scritto a mano, non verificabile da un sandbox Linux — vero per
chi scriveva senza il PC vero davanti, ma il modulo PowerShell `ScheduledTasks`
(`Get-ScheduledTask` / `Set-ScheduledTask -Settings`) la espone come proprietà
(`StartWhenAvailable`) senza toccare XML, verificato rileggendola dopo la scrittura invece
di fidarsi del solo codice di uscita. `setup-scheduler.cmd` la imposta ora da sé su trigger
giornaliero e backup notturno con una chiamata a `powershell -Command` inline: non è uno
script `.ps1`, quindi la execution policy `AllSigned` non c'entra — la stessa distinzione
per cui `jb.cmd`/`web.cmd` restano `.cmd` e non `.ps1`. Non serve su `JobBoard - worker`:
una ripetizione al minuto non ha un "avvio mancato" da recuperare, riparte da sola al
minuto buono successivo.

### Ognuna delle tre attività ha un interruttore in `settings`, non un secondo Task Scheduler

Le tre attività di Task Scheduler partono incondizionate appena `.\setup-scheduler` le ha
create, e restano così finché qualcuno non le cancella da Windows — `schtasks` non ha modo di
leggere una riga di Postgres prima di decidere se agire, lo stesso vincolo di "L'orario è solo
la preferenza registrata" qui sopra. Quando i bottoni "Aggiorna adesso" e "Rivaluta tutto"
della dashboard hanno avuto bisogno di un modo per farsi eseguire da soli senza che Filippo
aprisse un terminale, il meccanismo esisteva già — è lo stesso tick di sempre, non uno nuovo —
mancava solo un modo per fermarlo dalla dashboard senza cancellare l'attività:
`jobboard.queue_settings`, tre chiavi (`"auto_worker"`, `"scheduled_trigger"`,
`"scheduled_backup"`, una per attività), stesso pattern di `notify.settings` e
`tracking.settings`.

**Tre interruttori indipendenti, non uno solo per "l'automazione".** Spegnere il worker ferma
anche i bottoni della dashboard (nessuno lo reclama più); spegnere la raccolta giornaliera o il
backup notturno lascia gli altri due intatti. Un solo interruttore avrebbe risparmiato una
sezione nella pagina Impostazioni al prezzo di non poter tenere acceso "Aggiorna adesso" e
spegnere solo la raccolta automatica delle 07:00 — una combinazione ragionevole (raccolta solo
su richiesta, candidature comunque reattive) che un interruttore unico non potrebbe esprimere.

**Accesi di default, tutti e tre — a differenza di notifiche e tracciamento.** Questi ultimi
partono spenti perché accendono un'azione nuova che prima non esisteva — una mail, una lettura
IMAP — e un default acceso sarebbe stata una sorpresa. Qui è l'opposto: chi ha già eseguito
`.\setup-scheduler` conta da tempo su quei tick, e questo file non introduce niente che prima
non ci fosse — nasce solo per poterli fermare. Un default spento avrebbe interrotto in
silenzio, al primo deploy, un'automazione già in uso.

**Il controllo sta nei comandi, non in `queue.claim` o dentro `run_backup`.** `claim()` resta
quello che serve sia a `--once` sia a `serve()` — la lettura della coda con
`FOR UPDATE SKIP LOCKED`, niente di più. Per `jb work trigger` e `jb backup run`, che al
contrario di `--once`/`serve()` non hanno due funzioni diverse per l'invocazione automatica e
quella manuale, l'interruttore si legge solo dietro un flag nuovo, `--scheduled` — quello che
`setup-scheduler.cmd` passa nell'azione delle due attività giornaliere. Lanciati a mano, senza
il flag, restano un'azione esplicita di Filippo: un `jb backup run` prima di una migration
rischiosa, o un `jb work trigger` per forzare una raccolta subito, non devono fermarsi per un
interruttore pensato solo per il tick automatico. Con l'interruttore del worker spento, `--once`
non scrive nemmeno il battito: l'indicatore online/offline deve restare vero al significato che
ha in dashboard — "un bottone premuto verrà preso in carico a breve" — e con l'avvio automatico
fermo quello non è più vero finché qualcuno non rilancia `jb work` a mano.

### Le tre attività non aprono più una finestra sullo schermo

`schtasks /create` con le attività "solo se l'utente ha eseguito l'accesso" (necessario per
Playwright *headful* di "jb apply": una sessione non interattiva, Session 0, non ha un desktop
su cui mostrare davvero un browser) lancia il processo sulla sessione interattiva, e un
eseguibile a console — `jobboard.exe` lo è — apre lì la sua finestra, ogni volta, a meno che chi
lo lancia non gliene impedisca la creazione. "Nascosta" nelle proprietà di Task Scheduler **non
è quello che serve**: nasconde la voce dell'attività dall'elenco (serve "Mostra attività
nascoste" per rivederla), non la finestra del processo — due impostazioni diverse con un nome
che suggerisce la stessa cosa, ed è facile scoprirlo solo dopo averlo provato.

`run-hidden.vbs` alla radice è il wrapper: `WshShell.Run(comando, 0, True)`, dove `0` è lo stile
finestra "nascosta" passato al processo lanciato e `True` fa aspettare che finisca prima che lo
script termini — senza, Task Scheduler segnerebbe l'attività "completata" mentre `jobboard.exe`
lavora ancora. VBScript invece di `powershell -WindowStyle Hidden`: `wscript.exe` non ha una
console propria da dover nascondere, mentre l'host PowerShell a volte lampeggia comunque la sua
prima che lo stile nascosto abbia effetto — un dettaglio riportato spesso da chi risolve lo
stesso problema, non solo teorico. Gli argomenti passano separati (percorso dell'eseguibile, poi
i suoi parametri) e non come un'unica riga già composta, per non dover raddoppiare le virgolette
a ogni livello di quel che la invoca (`cmd.exe` → `schtasks /tr` → il wrapper). **Verificato**
forzando l'esecuzione delle tre attività vere con `schtasks /run` e osservando il battito
aggiornarsi senza che nessun processo restasse visibile o appeso: il primo tentativo, con un
trattino lungo (—) in un commento del `.cmd`, aveva mandato in errore `schtasks` con un
messaggio che non c'entrava nulla (`"M" non riconosciuto...`) — i commenti dei file `.cmd`
restano testo ASCII per lo stesso motivo per cui il resto del file scrive `e'` invece di `è`.

### Il digest email è un effetto di fine run, non un secondo scheduler (Fase 8.3/8.4)

`GET /api/matches` porta un commento, scritto in Fase 4, che prevedeva il digest come uno
dei suoi client. Costruendo la Fase 8.3 non ha retto: le credenziali SMTP
(`GMAIL_ADDRESS`/`GMAIL_APP_PASSWORD`) stanno solo in `worker/.env`, non nelle Environment
Variables di Vercel — coerente con la regola generale che il worker porta segreti e
comportamento, il database porta i dati. Farebbe quindi il worker a chiamare quella rotta,
ma da un processo Python senza cookie di sessione Auth.js non c'è modo di superare
`requireApiSession()`, e aggiungere una seconda via d'accesso (una chiave di servizio, per
esempio) solo per questo sarebbe una superficie di autenticazione in più per un'esigenza
che non la richiede affatto: a fine `run_matching()` il worker ha già in memoria, nello
stesso processo, esattamente i `Match` appena valutati. Il digest (`jobboard.notify`) li
legge da lì.

**"Nuovo" è `new_job_ids`, non "valutato in questa run".** `pipeline.match.persist()`
confronta gli id degli annunci valutati con quelli che avevano già una riga `match` prima
del salvataggio corrente, calcolato una sola volta prima dei tre cicli di scrittura che
altrimenti lo confonderebbero (`_new_scored_ids`, testato senza sessione come `_row` e
`_write_stage1`). Senza questa distinzione un `jb match --rescore` — che ripassa dalla
rubrica anche gli annunci già visti — spedirebbe una seconda notifica identica alla prima
per lo stesso annuncio.

**Attivazione, soglia e orario vivono in `settings`**, chiave `"notifications"`, stesso
pattern di `pipeline.criteria` (chiave `"matching"`) e `pipeline.ingest` (chiave
`"search"`): una riga letta con un default al primo giro, creata dal worker dai valori di
`.env` (`MATCH_THRESHOLD`, `DAILY_RUN_HOUR`) se non esiste ancora, poi modificabile dalla
pagina Impostazioni senza riavviare il worker. La differenza rispetto a quei due casi è
che qui anche il lato web scrive: `lib/notifications.ts` fa lo stesso upsert su chiave
primaria che il worker farebbe, e la lettura non crea mai la riga da sola — una `GET` non
deve inserire dati, la crea solo la prima run che la trova mancante.

**L'orario è solo la preferenza registrata, non lo scheduler vero.** Chi decide quando la
raccolta parte davvero resta l'attività Windows creata da `setup-scheduler.cmd`, fissa alle
07:00: `schtasks` non ha modo di leggere una riga di Postgres prima di partire, e
costruire quel ponte (un secondo processo che sveglia `jb work trigger` all'orario
salvato, sostituendo l'attività fissa) è più macchina di quanta ne serva per una
preferenza che oggi cambia raramente. La pagina Impostazioni lo dice esplicitamente
invece di lasciarlo credere: cambiare l'ora qui non sposta l'attività di Task Scheduler,
serve rilanciare `.\setup-scheduler` con un orario diverso per quello. Se in futuro
questo diventa una frizione vera, è il punto in cui `apscheduler` — già dichiarato in
`pyproject.toml`, mai usato — troverebbe finalmente un impiego.

**Una mail non partita non fa fallire la run.** `handlers.run_pipeline` chiama
`notify.digest.send_digest` fuori dal blocco che può sollevare `TaskError`: raccolta e
punteggi sono già salvati a quel punto, e un `MailError` (SMTP giù, credenziali scadute)
diventa un avviso registrato in `task.result` (`notifica_errore`), non un tentativo che
rifarebbe daccapo raccolta e quaranta chiamate LLM per un problema che riguarda solo
l'ultimo passo. Stesso principio di `MatchReport.errors` per gli annunci che lo Stadio 2
non riesce a valutare.

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

Entrambi i lati passano dal pooler **Supavisor**, ma da due porte diverse:

| Chi | Porta | Modalità | Perché |
|---|---|---|---|
| Worker, Alembic | `5432` | **Session pooler** | La connessione resta assegnata per tutta la sessione: prepared statement e transazioni lunghe funzionano come su una connessione diretta |
| Vercel | `6543` | **Transaction pooler** | La connessione torna nel pool a fine transazione. Le funzioni serverless ne aprono e chiudono di continuo, e senza pooler esaurirebbero i posti disponibili |

Il transaction pooler impone `prepare: false` lato client: i prepared statement
sopravvivono alla connessione logica e il pooler li reindirizzerebbe a sessioni diverse,
facendo fallire query che in locale funzionano.

> **Perché non la connessione diretta per il worker.** Sembrerebbe la scelta naturale per
> un processo long-running, ed era il piano iniziale. Ma l'host diretto
> `db.<ref>.supabase.co` pubblica **solo un record AAAA**: è raggiungibile unicamente via
> IPv6, e l'indirizzo IPv4 è un add-on a pagamento. Su una rete senza IPv6 la
> risoluzione DNS fallisce prima ancora di tentare la connessione. Il session pooler ha
> record A regolari e offre le stesse garanzie di sessione, quindi è la scelta corretta
> anche a prescindere.

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

384 dimensioni, **multilingua** — essenziale con annunci misti IT/EN/DE. Gira su CPU
senza toccare la GPU da 4 GB, che non basterebbe comunque per un LLM decente. Misurato
su questa macchina: **154 ms per annuncio**, cioè ~80 secondi per una run da 500 annunci.
Irrilevante per un processo notturno.

I vettori stanno come `bytea` in Postgres — float32 little-endian esplicito, non il byte
order nativo — e vengono caricati in un array numpy dal worker: sotto i 10.000 annunci
il cosine brute-force è istantaneo. Nessuna estensione vettoriale da installare e
mantenere.

Tre vincoli di questo modello, tutti verificati sul campo e tutti nascosti nella
documentazione di terzi:

- **fastembed 0.8 non lo include** fra i modelli integrati: ha solo la variante `large`
  da 2.24 GB. Viene registrato a mano dal repo ufficiale con `add_custom_model`, con
  pooling *mean* e normalizzazione L2 come da model card.
- **Occupa 449 MB su disco**, non i ~120 MB che il nome "small" suggerisce: i pesi stanno
  quasi tutti nella matrice di embedding da 250.000 token del vocabolario multilingua,
  non nei layer. Esiste nello stesso repo una variante int8 a un quarto dello spazio:
  è un cambio di `model_file` nella `ModelSpec`, se un giorno servisse.
- **I prefissi `query:` e `passage:` sono obbligatori.** La famiglia E5 è addestrata
  così. Ometterli non solleva niente: peggiora i risultati in silenzio. Stanno nella
  `ModelSpec`, non nel chiamante, e un modello senza `ModelSpec` viene rifiutato invece
  di essere usato con i prefissi sbagliati.
- **Il troncamento è a 512 token**, circa 350 parole. Il testo di un annuncio va quindi
  composto mettendo davanti ciò che conta: titolo, azienda, requisiti. Quello che sta
  dopo non viene letto.

### LLM: provider intercambiabile, Gemini free tier di default

L'imbuto è progettato perché il costo LLM sia trascurabile: gli stadi 0 e 1 — quelli
che scartano 460 annunci su 500 — girano **interamente in locale e a costo zero**. Solo
i ~40 annunci superstiti, più i pochi CV generati su richiesta, arrivano a un modello.

Quel volume entra nel **free tier di Google AI Studio**, che è il default:

| Modello | Uso | Perché |
|---|---|---|
| `gemini-2.5-flash-lite` | estrazione requisiti dalla JD, rubrica di scoring | alto volume, il modello più economico che regge un'estrazione strutturata |
| `gemini-2.5-flash` | riscrittura del CV | basso volume: qui si usa il modello migliore che il free tier consente |

`LLM_PROVIDER` accetta anche `anthropic` e `ollama`. Il layer in `jobboard/ai/client.py`
espone una sola interfaccia, quindi cambiare fornitore è una variabile in `.env` e non
una riscrittura — utile se un giorno la qualità sul tailoring del CV dovesse contare più
del costo.

> **Nota sull'abbonamento Claude.** Claude Pro copre claude.ai e Claude Code, **non**
> l'API: sono prodotti a fatturazione separata e non esiste un modo legittimo di usare
> l'abbonamento da uno script. Per questo il default è un free tier vero.

### Alembic è l'unica fonte di verità dello schema

I modelli SQLAlchemy nel worker definiscono lo schema; Alembic genera e applica le
migration. Il lato Next.js riceve i tipi TypeScript da un generatore
(`jobboard gen-web-schema`) che legge `Base.metadata` ed emette
`web/src/db/schema.ts`.

> Inizialmente si usava `drizzle-kit pull`, ma va in crash su questo database:
> Postgres espone i vincoli `NOT NULL` come pseudo-CHECK in
> `information_schema.check_constraints` — 101 righe su 104 — e drizzle-kit 0.31.10
> non li gestisce. Generare dai modelli mantiene la stessa garanzia di fonte unica
> e in piu' produce i **tipi union degli enum**, che l'introspezione non potrebbe
> dedurre: nel database quelle colonne sono semplici VARCHAR.

Risultato: un solo posto dove si cambia una colonna, e nessuna possibilità di drift fra
i due linguaggi.

#### Il `default=` dell'ORM non è un default del database

Vale la pena scriverlo perché è costato una diagnosi. In SQLAlchemy `default=` è un
valore **lato Python**: lo applica la sessione al momento del flush, e nel DDL non
finisce mai. Trentacinque colonne `NOT NULL` dello schema lo avevano senza avere un
`DEFAULT` vero, e finché a scrivere era solo il worker la differenza non si vedeva.

Si è vista alla prima `INSERT` arrivata da Vercel. Drizzle, per una colonna che il
suo schema dichiara con un default, scrive la parola chiave `default` nella `VALUES`
— cioè chiede a Postgres il default della colonna, che non c'era:

    null value in column "progress" of relation "task"
    violates not-null constraint

Il generatore ci metteva del suo: copiava `col.default` — quello Python — in un
`.default()` TypeScript, e il lato web credeva quindi in un default che il database
non aveva. Tre correzioni, tutte necessarie: i modelli dichiarano `server_default`
accanto a `default` (`enum_column` lo deriva da solo), la migration `d5b3e97c1a08` li
scrive sul database, e il generatore emette `.default()` **solo** a fronte di un
`server_default`. Un test senza database (`test_ogni_default_dell_orm_ha_anche_un_default_sul_database`)
impedisce che la cosa si ripresenti alla prossima colonna.

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

I numeri della colonna di destra sono misurati sulla prima run vera, su 153 annunci
raccolti:

```
STADIO 0 — FILTRI DURI          (costo zero)                     153 -> 44
  esclude: lingua non parlata, work authorization mancante, seniority fuori
  range +/-1, location fuori dai mercati scelti, citta' diversa da quella del
  candidato (se non remoto), contratto escluso, azienda in blocklist, annuncio
  troppo vecchio, gia' visto o gia' candidato
  scarti misurati: livello 85, eta' 21, paese 3

STADIO 1 — SEMANTICO            (embedding locale, costo zero)    44 -> 40
  cosine(profile_emb, job_emb)  su testo normalizzato
  spread(...)  <- riscalamento min-max DENTRO il lotto del giorno
  + BM25 sulle competenze del profilo   <- cattura i match esatti di tecnologia
    che l'embedding da solo diluisce
  score_ibrido = 0.6*spread(cosine) + 0.4*spread(bm25)

STADIO 2 — RUBRICA LLM          (Gemini Flash Lite)               40 -> punteggio
  must_have_coverage      40%
  nice_to_have_coverage   10%
  seniority_fit           15%
  domain_fit              10%
  location_fit            15%
  salary_fit              10%
  output: punteggio 0-100 + rationale in 2 righe + gaps[]
  costo misurato: 40 chiamate, 101k token, ~5 minuti
```

### 7.1 Stadio 0 — perché i predicati stanno in Python e non in una `WHERE`

La coda della query sarebbe più elegante, ma **una riga assente da un result set non dice
perché è assente**, e `match.filtered_reason` è una colonna che abbiamo promesso di
riempire: senza, l'unico modo di capire perché un annuncio buono non compare in dashboard
sarebbe rieseguire i filtri a mano uno per uno. La SQL restringe a ciò che è attivo e non
già deciso; i predicati con motivazione girano su qualche centinaio di righe già in
memoria.

#### Un dato mancante non esclude mai

È la regola trasversale dello Stadio 0. Nel raccolto reale un terzo degli annunci non
dichiara il paese e due quinti non dichiarano il livello. Trattare quel silenzio come una
risposta negativa trasformerebbe un buco nei dati della fonte in un'offerta persa — e la
fonte non la ripubblica il giorno dopo. Il filtro esclude solo quando l'annuncio
*afferma* qualcosa di incompatibile.

Stessa logica sulla retribuzione: la soglia minima morde solo su una RAL **dichiarata**.
Il silenzio non è una cifra bassa.

#### Mercato, diritto al lavoro e città sono tre domande diverse

*Mercato* è dove Filippo vuole lavorare; *autorizzazione* è dove può, senza che l'azienda
debba sponsorizzarlo; *città* è dove vive davvero (Fase 11). Un annuncio a Londra fallisce
il secondo e non il primo, uno a Bangalore fallisce entrambi, uno a Roma non fallisce
nessuno dei due ma fallisce il terzo.

Un annuncio remoto salta il controllo sul mercato e su quello sulla città — è il motivo per
cui lo si guarda — ma **non** quello sull'autorizzazione: un remote da azienda
statunitense chiede quasi sempre di poter già lavorare negli Stati Uniti, e scoprirlo alla
domanda del form è tardi.

Il filtro sulla città è l'unica eccezione voluta alla regola "un dato mancante non esclude
mai" appena sopra: qui è la lista degli ammessi a essere implicita e non esplicita — vedi
§11quater per il perché.

#### La seniority si deduce, e si può sovrascrivere

Il livello di Filippo viene dai mesi di esperienza del `master_profile`, contando **una
sola volta i periodi sovrapposti**: iniziare il lavoro nuovo prima di chiudere il vecchio
è normale, e sommare le durate una per una promuoverebbe un junior a senior sulla carta.
Il valore dedotto finisce nella riga `settings` e da lì è modificabile: il mercato non
ragiona solo in mesi.

Sui dati reali questo filtro è il più selettivo dei sei — 85 scarti su 153 — e sono tutti
titoli *Senior*, *Staff* o *Lead*, cioè fuori portata per chi ha due anni di esperienza.

### 7.2 Stadio 1 — perché è ibrido e non solo embedding

L'embedding capisce che "sviluppatore backend" e "backend engineer" sono la stessa cosa,
ma **diluisce le tecnologie**: un annuncio Java e uno Python con la stessa struttura di
frasi hanno vettori quasi identici, e la differenza è esattamente ciò che decide se puoi
candidarti. BM25 fa il lavoro opposto — pesa le corrispondenze esatte e premia i termini
rari — e i due errori non si sommano perché non sono lo stesso errore.

Tre dettagli dell'implementazione che non sono ovvi:

**Le competenze sono frasi, non parole.** "Spring Boot", "REST API", "CI/CD" spezzettati
in unigrammi diventano rumore: "boot" e "api" compaiono ovunque. Un termine di ricerca è
un n-gramma fino a tre parole e viene cercato come tale.

**Il tokenizzatore tiene i simboli finali.** `[a-z0-9]+(?:[.+#/][a-z0-9]+)*[+#]*`: senza
la coda, "C++" diventa "c" — un token che non corrisponde a niente — e una competenza
dichiarata nel profilo smette di contare senza dare errore. È un bug che un test ha
trovato prima della prima run.

**La IDF è quella smussata,** `ln(1 + (N-n+0.5)/(n+0.5))`. La formula classica di
Robertson diventa *negativa* per un termine presente in più di metà dei documenti: in un
corpus di annunci per sviluppatori "developer" ne fa parte, e un contributo negativo
farebbe scendere il punteggio di un annuncio *perché* contiene la parola giusta.

Il titolo pesa tre volte il corpo, ripetendolo nel testo indicizzato: un "Java" nel
titolo dice molto più di un "Java" in fondo all'elenco dei requisiti graditi, e BM25 da
solo non conosce la struttura del documento.

#### Perché il coseno va riscalato prima di essere combinato

Misurato con il modello di embedding scelto, contro il profilo reale:

| Annuncio | cosine |
|---|---|
| Mobile Developer Flutter/Android | 0.8966 |
| Junior Software Engineer fullstack | 0.8830 |
| Backend Developer Java | 0.8790 |
| Cuoco per ristorante di pesce | 0.8177 |
| Senior ML Research Scientist, PhD | 0.8102 |
| Infermiere professionale | 0.7993 |

L'ordinamento è corretto — i tre pertinenti stanno sopra i tre non pertinenti — ma
**l'intero intervallo utile è largo 0.08**, e un lavoro che non ha nulla a che vedere
con il profilo prende comunque 0.80. È una proprietà nota dei modelli E5, non un difetto
di questi dati. La run reale lo conferma: i primi dodici annunci stanno tutti fra 0.827 e
0.875.

Due conseguenze operative:

1. **Nessuna soglia assoluta sul coseno.** "Scarta sotto 0.75" non scarterebbe niente;
   "sotto 0.85" scarterebbe metà dei lavori giusti. Lo Stadio 1 ordina e prende i
   primi N, non filtra per valore.
2. **Il coseno grezzo non si somma a BM25.** Sommato così com'è contribuirebbe con una
   costante di ~0.8 più una variazione di 0.08: peso dichiarato 60%, peso reale ~5%. La
   funzione `spread()` porta il lotto del giorno sull'intervallo 0-1 prima della
   combinazione, così i pesi significano quello che dicono.

Un annuncio senza embedding viene **saltato**, non valutato zero: uno zero lo manderebbe
in fondo alla classifica come se fosse stato giudicato e bocciato.

### 7.3 Stadio 2 — una chiamata, non due

Il piano descriveva l'estrazione dei requisiti e la rubrica come due passi. Sono
implementati come **una sola chiamata** che produce entrambi, per due ragioni: due
chiamate manderebbero due volte la stessa job description, che è il 90% dei token; e le
due risposte potrebbero contraddirsi, con un punteggio che dice "copre tutti i must have"
accanto a una lista di must have che ne contiene uno mancante.

**L'ordine dei campi nello schema è parte del prompt.** Il modello genera i campi
nell'ordine in cui sono dichiarati: prima estrae i requisiti, poi assegna i punteggi
*avendoli già scritti*. Invertire l'ordine gli farebbe dare un voto prima di aver
guardato cosa sta valutando. Un test protegge quest'ordine, perché non è il genere di
regressione che si nota guardando i numeri.

**La media pesata la fa il codice, non il modello.** Gli LLM fanno aritmetica in modo
inaffidabile, ma la ragione principale è un'altra: un totale prodotto dal modello non si
può ritarare. Con i sei sotto-punteggi salvati in `match.subscores`, `scripts/calibrate.py`
prova pesi diversi sugli stessi dati senza rifare una sola chiamata.

#### Assenza di prove non è prova di eccellenza

**È la regola che ha richiesto il maggior numero di correzioni, e l'ha imposta la prima
run vera.** Al primo giro il punteggio più alto di tutto il raccolto — 65, primo in
classifica — è andato a un annuncio da contabile a Pune con quattro righe di descrizione.
La motivazione scritta dal modello stesso diceva: *"ruolo amministrativo completamente
slegato dal profilo tecnico del candidato"*, e `domain_fit` valeva 0.

Il colpevole era `must_have_coverage: 100`. L'annuncio non elencava **nessun** requisito,
il modello ha estratto `must_have = []` e ne ha dedotto, con logica vacua impeccabile,
che il candidato copre il 100% di zero requisiti. Quel criterio pesa il 40%: quaranta
punti nati dal nulla, più i neutri degli altri criteri, fanno 65.

La correzione è deterministica e sta nel codice, non in una preghiera al prompt: quando
l'elenco dei requisiti è vuoto, la copertura **non è conoscibile** e vale 50. Stessa
regola per `salary_fit` quando la RAL non è dichiarata, e per `nice_to_have_coverage`.
Dopo la correzione quell'annuncio è passato da 65 a **25**, e i primi dodici posti sono
tutti ruoli da sviluppatore.

#### Niente Batch API con Gemini

Il piano prevedeva la Message Batches API di Anthropic, che sconta del 50% le richieste
non urgenti. Non ha equivalente sul provider attivo, quindi le chiamate sono sequenziali
con **una pausa di 4 secondi** l'una dall'altra: il free tier conta le richieste al
minuto, e quaranta chiamate consecutive esaurirebbero la quota in venti secondi facendo
tornare 429 tutte le altre. La run dura due minuti in più, che per un processo notturno
non è un costo.

Un annuncio su cui la chiamata fallisce viene registrato in `report.errors` e la run
prosegue: gli altri trentanove non devono pagare per uno.

#### La riserva per le fonti a budget

**`stage2_top_n` è un tetto condiviso da tutte le fonti insieme, applicato all'intero
arretrato non ancora valutato — non "quaranta al giorno fra gli annunci di oggi".**
`filters.candidates()` con `rescore=False` prende ogni annuncio attivo che non ha ancora
raggiunto lo Stadio 2, a prescindere da quando è stato raccolto; lo Stadio 1 lo ordina per
punteggio ibrido e i primi `stage2_top_n` — di *tutto* quell'arretrato — passano alla
rubrica. Con otto fonti registrate e una sola a budget (JSearch, `default_daily_budget =
6`), le sette senza tetto riempiono l'arretrato molto più in fretta di quanto JSearch
riesca a portare candidati: i pochi annunci LinkedIn/Indeed che arrivano ogni giorno
devono competere per un numero fisso di posti contro un arretrato che cresce da fonti
senza limite, e perdono quasi sempre — indipendentemente da quanto siano buoni.

L'ha scoperto Filippo usando la dashboard per davvero: pochissimi annunci LinkedIn in
tabella, contro una ricerca manuale su LinkedIn che ne trovava molti di più. Alzare
`daily_call_budget` di JSearch non avrebbe risolto niente: il collo di bottiglia non era
quante chiamate JSearch potesse fare, era quanti dei suoi risultati sopravvivevano alla
competizione collettiva per lo Stadio 2.

`pipeline.match.select_finalists` separa i posti in due gruppi invece di fare uno slice
ingenuo: `stage2_top_n - stage2_reserved_floor` per merito puro (come prima), e fino a
`stage2_reserved_floor` riservati ai migliori annunci di una fonte con un
`daily_call_budget`, presi *dall'arretrato che il merito puro avrebbe scartato* — mai
aggiunti sopra il tetto. Due proprietà che il codice mantiene di proposito:

- **La riserva è tolta dal totale, non aggiunta.** Il costo di una run resta prevedibile:
  al più `stage2_top_n` chiamate LLM, mai di più, indipendentemente da quanti annunci a
  budget ci sono in coda quel giorno.
- **Non si riempiono posti fittizi.** Se gli annunci a budget in coda sono meno della
  riserva richiesta, la run ne valuta semplicemente di meno — non si scelgono annunci a
  caso per arrivare al numero.
- **Un annuncio a budget che vince già un posto per merito non consuma la riserva.** La
  riserva serve solo a chi altrimenti resterebbe fuori: JSearch non è penalizzato quando i
  suoi annunci sono davvero i migliori.

Il criterio è "ha un `daily_call_budget`", non il nome dell'adapter: quando arriverà una
seconda fonte a consumo la riserva la copre da sola, senza toccare `select_finalists`.

### 7.4 Taratura dei pesi

`scripts/calibrate.py export` scrive un CSV con i sotto-punteggi già calcolati e una
colonna `voto` da riempire a mano; `evaluate` cerca su tutte le 53 130 combinazioni di
pesi a passo 0.05 quella che riproduce meglio i giudizi, misurata in **correlazione di
rango** — perché quello che la dashboard mostra è un ordine, non un valore assoluto.

Sei pesi liberi su trenta esempi trovano sempre *qualcosa*, anche nel rumore. Per questo
lo script non si limita a stampare il vincitore: divide gli esempi in due metà, cerca su
ciascuna e verifica che il vincitore dell'una regga sull'altra. Se le due metà non sono
d'accordo, il messaggio lo dice e i pesi vanno lasciati stare.

### 7.5 «Rivaluta tutto»: `--rescore` esposto in dashboard, non solo da terminale

`filters.candidates()` esclude di default chi ha già `reached_stage >= 2` (vedi 7.3): un
cambio di filtri, criteri o `MasterProfile` non tocca gli annunci già valutati finché
qualcuno non rilancia `jb match --rescore` — che ripassa dalla rubrica **tutto** l'attivo,
non solo l'arretrato. Prima di questa fase quel "qualcuno" doveva aprire un terminale sul
PC del worker; il bottone "Aggiorna adesso" della dashboard accodava sempre un
`run_pipeline` senza quell'opzione.

"Rivaluta tutto" è lo stesso bottone con un payload in più: `handlers.run_pipeline` legge
`ctx.payload["rescore"]` e lo inoltra a `run_matching()`, invece di un secondo tipo di
task o un secondo gestore — `run_pipeline` resta uno, la deduplica di `enqueueTask` (per
tipo *e* payload) distingue da sola una richiesta normale da una con rescore, e le due non
si scavalcano: il worker le lavora in coda, mai insieme. Il bottone chiede conferma con un
`window.confirm` prima di accodare, perché il costo è reale e non ovvio dal solo testo:
una chiamata LLM per ogni annuncio già valutato, non solo per i nuovi.

**Il digest non duplica in nessuno dei due casi.** `MatchReport.new_job_ids` — annunci
senza una riga `match` prima del salvataggio corrente — è già la distinzione che serve
(vedi Fase 8.3 in ROADMAP.md): un annuncio rivalutato da `--rescore` non è "nuovo" anche
se il suo punteggio è cambiato, quindi non genera una seconda notifica per lo stesso
annuncio.

## 8. Deduplicazione

Chiave canonica: `normalize(company) + normalize(title) + normalize(city)`.

In caso di collisione si confronta il **SimHash** della description a 64 bit, con soglia
di 10 bit di distanza di Hamming — l'85% di somiglianza. Due testi indipendenti ne
differiscono di una trentina, quindi la soglia non è delicata. Due vincoli imparati
sul campo:

- **Il confronto per contenuto vale solo dentro la stessa azienda.** Le agenzie
  ripubblicano lo stesso testo per clienti diversi: unirli nasconderebbe un annuncio vero.
- **Sotto i 300 caratteri il SimHash non si usa.** L'estratto di due righe che
  restituisce Jooble produce impronte sostanzialmente casuali.

### Le varianti si fondono, non si scelgono

Quando lo stesso annuncio arriva da tre fonti non se ne tiene una buttando le altre:
ognuna può avere il pezzo che manca alle altre. L'aggregatore conosce la RAL, la board
ATS ha la descrizione completa e il link al form vero.

| Campo | Chi vince |
|---|---|
| `apply_url`, `ats_*` | La variante con ATS di Tier A — è l'unica che abilita l'invio automatico |
| `description` | La più lunga: Jooble dà due righe, Lever l'annuncio intero |
| RAL | La prima che la dichiara davvero |
| `posted_at` | La **più vecchia**: gli aggregatori riportano quando hanno indicizzato, non quando l'annuncio è uscito |

### Le classificazioni si ricalcolano a ogni run

`job_family`, `work_mode`, `seniority` e `contract_type` vengono riscritti a ogni
passaggio, non solo alla prima comparsa. Le regole di normalizzazione cambiano, e senza
questo un annuncio resterebbe classificato con il codice del giorno in cui è stato visto
per la prima volta. È successo davvero: dopo aver insegnato al classificatore i nomi
composti tedeschi, ventidue annunci già in tabella continuavano a non avere famiglia.

## 8bis. Le fonti

Dieci adapter dietro la stessa interfaccia. Rate limiting e retry stanno nel client HTTP
condiviso: sono errori che si fanno una volta per fonte, e con dieci fonti diventano
dieci occasioni di farli.

| Fonte | Chiave | Copre | Note |
|---|---|---|---|
| Adzuna | gratuita | IT, DE, NL, ES, FR, UK | La più importante per il mercato italiano on-site |
| Jooble | gratuita | multi-paese | Restituisce un **estratto**, non la descrizione: è una fonte di segnalazione |
| JSearch | RapidAPI | LinkedIn, Indeed, Glassdoor | ~6 chiamate al giorno: budget esplicito, query in ordine di priorità |
| Arbeitnow | nessuna | Germania + remote | Board intera, filtrata in locale |
| Remotive | nessuna | remote worldwide | Tre chiamate per categoria, filtro in locale |
| RemoteOK | nessuna | remote worldwide | I ToS chiedono di citare la fonte e linkare l'annuncio |
| Greenhouse, Lever, Ashby, Workable | nessuna | board delle aziende seguite | **Le fonti migliori**: descrizione completa e link al form vero |

Tre trappole trovate provandole, tutte silenziose:

1. **Il primo elemento dell'array di RemoteOK non è un annuncio**, è l'avviso legale.
2. **Le RAL assenti di RemoteOK valgono `0`, non `null`.** Uno zero preso per buono
   diventa un annuncio "da 0 €" ordinato in fondo come se la cifra fosse dichiarata.
3. **Greenhouse e Arbeitnow restituiscono l'HTML con le entità già codificate**: senza
   `unescape` la descrizione è un muro di `&lt;p&gt;`.

### Il filtro per parole chiave confronta parole, non frasi

Le fonti che restituiscono l'intera board vanno filtrate in locale, altrimenti una sola
azienda grande porta centinaia di annunci di vendita e amministrazione nella pipeline —
e ognuno costa un embedding. La prima versione cercava la frase come sottostringa: con
`"software developer"` non trovava né *Senior Software Engineer* né *Backend Developer*,
cioè esattamente gli annunci da tenere. Quattro fonti su dieci restituivano zero
risultati. Ora basta che una parola significativa compaia nel titolo, con match per
prefisso dai quattro caratteri in su (`developer` trova anche `developers`,
`software` trova anche `Softwareentwickler`).

I termini di ricerca vengono seminati dal CV — headline più le famiglie dei ruoli svolti
— **e tradotti in italiano**: un annuncio milanese si intitola "Sviluppatore Backend", e
cercando solo in inglese il mercato principale resta invisibile.

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

### Dal modello passa solo la prosa

La decisione che rende governabile tutto il resto, presa scrivendo la fase. Al generatore
si chiedono quattro cose — le cinque keyword, il summary, i bullet riscritti, le
competenze — e **nient'altro**. Nomi delle aziende, date di inizio e fine, titoli di
studio, recapiti, certificazioni e lingue non entrano nemmeno nella richiesta: li copia il
template leggendoli dal `MasterProfile`.

Un modello che può sbagliare una data è un modello che va riletto per intero ogni volta.
Un modello che le date non le tocca ha una superficie di invenzione ristretta a quello che
il validatore sa verificare, ed è la differenza fra un CV da controllare e uno da spedire.

Per lo stesso motivo **l'ordine delle esperienze non lo decide il modello**: sceglie quali
tenere, ma a metterle in fila è il codice, in ordine cronologico inverso. Riordinare una
carriera non è una scelta editoriale.

### Un id è un'affermazione, non una prova

Ogni bullet generato dichiara il `source_id` del bullet del profilo da cui viene. Non
basta: il modello può scrivere qualunque cosa e attribuirla a `acme-be-1`. Il validatore
verifica quindi tre cose diverse, tutte deterministiche:

1. **la provenienza esiste** — e appartiene all'esperienza sotto cui il bullet è stato
   messo. Un bullet vero sotto il datore di lavoro sbagliato è comunque falso;
2. **le cifre risalgono alla fonte** — ogni numero del testo generato deve comparire nel
   bullet di partenza. È la regola che conta di più: un numero falso su un CV è l'unico
   errore che in un colloquio non si recupera;
3. **le competenze risalgono al profilo**.

Una quarta regola, aggiunta in Fase 11, applica la stessa identità di controllo (1+2) a
`additional_info` — le voci scelte dal pool di informazioni applicante, un elenco separato
dal `MasterProfile`. Il perché di un pool a sé, e non un'estensione del profilo o delle
risposte ai form, è in §11quater.

### Due falsi positivi che avrebbero reso inutile il validatore

Entrambi trovati provando, ed entrambi gravi allo stesso modo: **un validatore che blocca
i CV giusti viene spento**, e da quel momento non protegge più da niente.

*I numeri scritti a lettere.* Il `MasterProfile` conserva il CV come è scritto, e i CV
italiani scrivono "da sei ore a venti minuti", "quaranta milioni di righe", "dal quaranta
all'ottanta percento". Il CV generato usa le cifre, perché così si scrive un CV. Senza un
vocabolario dei numeri a parole — italiano e inglese, composti compresi — ogni riscrittura
corretta risultava un'invenzione. Sottocaso trovato subito dopo: **"per cento" non è il
numero cento**, e senza quell'eccezione una percentuale scritta a parole introduceva un
100 fantasma.

*Le competenze tradotte.* La Fase 6.7 scrive il CV nella lingua dell'annuncio, quindi un
profilo italiano che dichiara "Lavoro in team" produce un CV inglese che dice "Teamwork".
Nessuna somiglianza di stringa lega le due cose. Il primo rimedio — match per prefisso dai
quattro caratteri, la regola già usata dal filtro delle fonti — aveva il difetto opposto e
peggiore: `"javascript".startswith("java")`, quindi un profilo che dichiara Java
giustificava un CV che dichiara JavaScript.

La soluzione è la stessa disciplina dei bullet: **ogni competenza dichiara la sua
provenienza**. `text` è come va scritta nel CV — con la grafia dell'annuncio, tradotta se
serve — e `source` è la voce del profilo, ricopiata alla lettera e confrontata in modo
esatto. Il profilo dice "PostgreSQL", l'annuncio dice "Postgres", il CV scrive "Postgres"
e resta vero.

### Prima si toglie, poi si stringe

L'ordine dei rimedi del loop di fit non è casuale. Stringere interlinea e margini è
gratis e istantaneo, ed è esattamente per questo che è la tentazione sbagliata: un CV a
8pt con margini da un centimetro sta in una pagina e non lo legge nessuno. Il contenuto di
troppo va tolto perché è di troppo; la densità è la riserva per l'ultimo centimetro, in
tre gradini che restano leggibili.

Due dettagli che l'esecuzione ha imposto:

- **quanto sfora si misura, non si indovina.** Il conteggio delle pagine dice "due" sia per
  un CV che sfora di tre righe sia per uno che sfora di mezza pagina, e chiedere di
  tagliare il 50% al primo restituisce un CV dimezzato. Si guarda dove arriva l'ultima riga
  di testo sull'ultima pagina, e si chiede un taglio proporzionato. Sotto il 6% non si
  chiama nemmeno il modello: si stringe e basta;
- **ogni compressione ripassa dal validatore.** Una riscrittura è una generazione, e una
  generazione può inventare. Se una compressione introduce una violazione si scarta *lei*,
  non il documento, e si tiene la versione approvata prima.

## 10. Router della candidatura

### Il Tier A non è un invio via API: scoperto scrivendo la Fase 7

Il piano qui sotto, scritto prima di implementare la Fase 7, prevedeva per il
Tier A una `POST` diretta all'endpoint pubblico di Greenhouse, Lever, Ashby e
Workable. Verificato leggendo la documentazione ufficiale delle quattro API
prima di scrivere il client: **nessuna delle quattro lo permette a un
candidato esterno.**

- **Greenhouse** protegge oggi il form pubblico di apply con reCAPTCHA
  Enterprise e un fingerprint minato lato client (`g-recaptcha-enterprise-token`,
  `csrfToken`, `fingerprint` nel corpo della richiesta) — una `POST` da uno
  script senza browser viene rifiutata. L'endpoint documentato
  (`POST /v1/boards/{token}/jobs/{id}`) esiste ancora, ma richiede comunque
  Basic Auth con una **Job Board API key**, che genera solo un amministratore
  dell'azienda che ospita la board: non è qualcosa che un candidato possiede.
- **Lever** ha un endpoint pubblico per la lista annunci, ma l'endpoint di
  apply (`POST /v0/postings/{account}/{id}`) richiede una **Postings API key**
  generata da un Super Admin dell'account Lever dell'azienda.
- **Workable** espone in lettura solo il widget pubblico (`GET
  /api/v1/widget/accounts/{account}`): la creazione di un candidato passa
  dall'API REST v3 autenticata con un bearer token dell'azienda.
- **Ashby** non pubblica un'API generica per i job board ospitati;
  `applicationForm.submit` richiede il permesso `candidatesWrite`, quindi
  anch'esso una chiave lato azienda.

Tentare comunque l'invio via API — con credenziali che non si possiedono, o
aggirando il reCAPTCHA di Greenhouse — avrebbe violato il guardrail "nessun
aggiramento di CAPTCHA o sistemi anti-bot" scritto **prima** di scoprire il
problema, in fondo a questa stessa sezione. Il guardrail non è cambiato: è il
piano che gli sbatteva contro, e la correzione era obbligata.

**La correzione:** Tier A e Tier B condividono lo stesso motore — Playwright
headful sul PC di Filippo — e si fermano **entrambi** prima del submit. Cambia
solo come si compila il form:

| Tier | Quando | Comportamento |
|---|---|---|
| **A** | `ats_type` fra greenhouse, lever, ashby, workable, **e** un `apply_url` diretto | Playwright headful con selettori dedicati a quell'ATS (`jobboard/apply/selectors.py`), **si ferma prima del submit** |
| **B** | qualsiasi altro ATS con un `apply_url` diretto | stesso Playwright headful, precompilazione euristica su label e attributi (`jobboard/apply/heuristics.py`) |
| **C** | nessun `apply_url` diretto (solo il link dell'aggregatore) | apre l'URL, candidatura da fare a mano |

Il codice sta in `jobboard/apply/`: `router.py` decide il tier, `fields.py`
trasforma `CandidateAnswers` + `MasterProfile` in un piano di valori,
`heuristics.py`/`selectors.py` decidono dove scriverli, `browser.py` e' l'unico
modulo che parla con Playwright. Nessuno di questi selettori è stato
verificato su un form vero — richiede un annuncio reale e uno schermo, che
questo repository non ha in CI — e resta "verificato fino a qui" come il resto
della Fase 7 che tocca siti di terzi.

**Conseguenza sugli stati.** `ApplicationStatus.SUBMITTED` non lo scrive più
nessun codice del worker: lo scrive un click nella dashboard (`markApplicationSubmitted`),
**dopo** che l'invio è avvenuto davvero nel browser aperto sullo schermo. Il
worker porta una candidatura solo fino a `needs_human` — due nuovi eventi,
`prepared` e `prepare_failed`, segnano se ci è arrivato o no.

### Guardrail non negoziabili

- **dry-run globale** attivo al primo avvio: nessun browser si apre, la
  preparazione è simulata
- **cap giornaliero** configurabile, default 10 candidature **preparate** al
  giorno (non spedite: è l'apertura di un browser verso un sito di terzi
  l'azione automatica da limitare)
- **conferma esplicita** alla prima candidatura verso ogni nuova azienda
- **idempotenza**: lo stesso annuncio non può partire due volte (`match_id`
  è `UNIQUE` su `application`)
- **nessun aggiramento** di CAPTCHA o sistemi anti-bot — il vincolo che ha
  reso necessaria la correzione qui sopra, non un'aggiunta successiva

## 10bis. Tracciamento post-candidatura (Fase 9)

Simmetrico al digest della Fase 8.3 ma con lo scopo opposto: quello scrive verso
Filippo, questo **legge** — le risposte dei recruiter nella stessa casella Gmail — e
aggiorna lo stato della candidatura di conseguenza. Vive in `jobboard/tracking/`, non
in `jobboard/notify/`: leggere e scrivere la stessa casella sono due responsabilità
diverse, e il modulo che scrive non deve sapere come si legge, né viceversa.

### La lettura IMAP è a scope ristretto, non uno scan della casella

Una casella personale ha anni di posta che non riguardano nessuna candidatura.
`imap_reader.py` applica due restrizioni, entrambe misurabili nel codice e non solo
dichiarate:

1. **`SEARCH SINCE`** parte dalla data della candidatura (`submitted_at`) o
   dall'ultimo controllo (`last_email_checked_at`), mai dall'inizio della casella.
2. **Il corpo si scarica solo per chi supera la correlazione.** Due chiamate IMAP
   separate — `BODY.PEEK[HEADER...]` per gli header, `BODY.PEEK[]` per il corpo — e la
   seconda parte solo per i messaggi che `looks_related()` (o la corrispondenza di
   thread, sotto) ha già giudicato pertinenti. `PEEK` in entrambe, così nessuna mail
   viene marcata come letta dal passaggio del worker.

**La correlazione è un'euristica lessicale, non una certezza**, e questo è un limite
noto, non un difetto nascosto: i token del nome azienda normalizzato
(`job.company_normalized`, la stessa chiave della dedup della Fase 2) devono comparire
nel mittente o nell'oggetto. Da sola non basta — un recruiter risponde spesso da un
indirizzo Gmail personale che non contiene il nome dell'azienda da nessuna parte —
quindi si aggiunge la correlazione **per thread**: una mail il cui `In-Reply-To`/
`References` cita un `Message-ID` già classificato per quella candidatura resta
correlata anche quando il mittente cambia. Quello che l'euristica lascia fuori (falsi
negativi) è il motivo per cui la Fase 9.1 rende gli stati **modificabili a mano** dalla
pagina Candidature: non serve che il worker riconosca tutto, serve che correggerlo
costi dieci secondi.

### Il classificatore usa il provider attivo, non "Haiku" alla lettera

Il piano originale nominava Claude Haiku. Con Gemini come provider attivo (la stessa
decisione del §5 sotto "LLM: provider intercambiabile") il classificatore passa dalla
stessa interfaccia `ai.client.LLMProvider` di rubrica e CV, con un modello dedicato
(`model_classify`, di default lo stesso economico di `model_scoring`) invece di
un'implementazione Anthropic separata. "Haiku" nel piano descriveva un requisito —
economico, veloce, adatto a un compito a basso volume — non un vincolo di provider:
introdurre un secondo client LLM solo per questo stadio avrebbe raddoppiato la
superficie da mantenere senza cambiare cosa il sistema fa.

**La regola che sposta lo stato è nel codice** (`classifier.STATUS_BY_CLASS` e
`next_status`), non nel prompt: al modello si chiede un giudizio fra cinque classi
fisse, la mappatura verso `ApplicationStatus` si ritara senza rifare una chiamata,
stesso principio della media pesata della rubrica (§7.3). `next_status` impone anche
che uno stato non retroceda (un "ack" arrivato in ritardo dopo un colloquio già
fissato non deve tornare indietro) e che uno stato terminale non si riapra da solo.

### Il controllo email gira una volta al giorno dentro `run_pipeline`, non su un secondo scheduler

Stessa scelta della Fase 8.3 per il digest, per lo stesso motivo: aggiungere una terza
attività di Task Scheduler per un controllo che può girare subito dopo la raccolta
notturna avrebbe significato più codice di orchestrazione senza una necessità reale —
le risposte dei recruiter non sono urgenti al minuto. `run_email_check()` gira quindi
in coda al digest, nella stessa `run_pipeline`, con lo stesso principio "un effetto
collaterale non deve far fallire il lavoro già salvato": un IMAP giù o una chiave LLM
scaduta finiscono in `task.result.controllo_email_errore`, non in un task fallito.

Il bottone **"Controlla posta adesso"** nella pagina Candidature accoda lo stesso
`TaskType.CHECK_EMAIL` a comando, per chi ha appena acceso il tracciamento e non vuole
aspettare la run notturna — stessa relazione fra "Aggiorna adesso" e la raccolta
automatica della Fase 5.5/8.1.

### Il silenzio si misura da quando la candidatura è partita, non dall'ultimo controllo

`follow_up_after_days` (impostabile in `/impostazioni`, prudente e spento di default
come le notifiche) confronta `now` con `application.submitted_at`, **non** con
`last_email_checked_at`. Quest'ultimo esiste per un motivo diverso — è la finestra
`SINCE` della prossima ricerca IMAP — e usarlo per il conteggio del silenzio lo
azzererebbe a ogni controllo: con un controllo al giorno il conteggio non
supererebbe mai un giorno. Una volta segnato `follow_up_due_at`, la stessa
candidatura non ricompare finché una risposta vera non la sposta fuori dagli stati "in
attesa", o finché la data non viene corretta a mano.

## 11. Sicurezza

La dashboard è su internet e contiene il CV, i dati personali e un bottone che invia
candidature a nome di Filippo. Requisiti minimi:

- **Auth.js + Google OAuth con allowlist di una sola email.** Il rifiuto avviene nel
  callback `signIn`, cioè *prima* che esista un cookie di sessione: chiunque altro può
  arrivare fino alla schermata di Google e non oltre. Si controlla anche
  `email_verified`, altrimenti un account con un'email non verificata potrebbe
  dichiarare un indirizzo che non gli appartiene. In produzione, senza
  `AUTH_ALLOWED_EMAIL` l'applicazione si rifiuta di avviarsi: meglio un deploy che non
  parte di uno che parte aperto a tutti.
- **Due livelli, non uno.** `src/proxy.ts` (in Next.js 16 il vecchio `middleware.ts`)
  reindirizza chi non ha un cookie, ma gira anche sulle rotte che il browser preleva in
  anticipo: legge solo il cookie e non tocca il database. Il controllo che decide se dei
  dati possono uscire sta accanto ai dati, in `src/lib/dal.ts`, e lo chiama **ogni**
  funzione di lettura. Cancellare il proxy per sbaglio farebbe smettere di
  reindirizzare, non di proteggere.
- **Le API rispondono 401, non un redirect.** Un client che ha chiesto JSON e riceve una
  pagina HTML di login con stato 307 non vede un errore di autenticazione: vede un
  errore di parsing.
- **Nessun open redirect nel login.** Il parametro `next` viene accettato solo se inizia
  per `/`. Altrimenti sarebbe possibile far atterrare qualcuno, dopo un login vero, su
  un sito che somiglia a questo.
- **Connection string e service key mai nel bundle client**: solo server component e
  route handler, variabili senza prefisso `NEXT_PUBLIC_`, e `import "server-only"` sui
  moduli che le toccano.
- **TLS verso il database, con la radice fissata.** `pg` non abilita TLS da solo e la
  connection string di Supabase non contiene `sslmode`: senza configurazione esplicita
  la connessione va **in chiaro**, ed è stato verificato che accadeva davvero. Con la
  sola `rejectUnauthorized` fallisce, perché la catena si chiude su una CA privata di
  Supabase assente dal trust store di sistema. Il certificato radice sta in
  `web/src/db/supabase-ca.ts`, ed è stato **confrontato byte per byte** con il
  `prod-ca-2021.crt` scaricato dalla dashboard Supabase (Database Settings → SSL
  Configuration): impronta SHA-256 `80:70:25:AD:…:CA:FA`, valido fino al 26 aprile 2031.
- **`noindex, nofollow` su tutta l'applicazione**, login compreso.
- **Bucket PDF privato**, servito esclusivamente con signed URL a scadenza breve. Mai
  URL pubblici, neanche con la scusa che tanto non sono indicizzati.
- **Rate limiting** sui route handler che creano task, così un bug nella UI non può
  accodare 200 invii.
- **Region EU** su Supabase, trattandosi di dati personali.
- Segreti in `.env` git-ignored lato worker, Environment Variables lato Vercel.
- Vercel piano Hobby: uso personale e non commerciale, questo caso rientra.

### Perché `pg` e non `postgres-js`

Non è una preferenza di stile ma un guasto misurato. Con `postgres` (postgres-js) sotto
Next.js 16 la dashboard serviva **una sola richiesta**: la prima query rispondeva in
150 ms, dalla seconda in poi la connessione riutilizzata non restituiva più niente.
Nessun errore, nessun timeout — la richiesta si chiudeva solo quando era il browser a
rinunciare, il che dall'esterno somiglia a un database lento e non a un difetto del
driver. Succedeva identico in sviluppo e nella build di produzione, mentre fuori da
Next lo stesso client faceva quattro query a distanza di secondi senza un intoppo.

Nella diagnosi è emerso anche un secondo tranello, questo di nostra responsabilità: il
client tenuto su `globalThis` — il rimedio che si trova ovunque per l'accumulo di
connessioni in sviluppo — peggiora le cose. Next valuta i moduli in più contesti e
`globalThis` è condiviso fra questi, il socket TCP no: il primo contesto a creare il
client lo deposita lì, e se non è quello che serve le richieste il risultato è di nuovo
una query che non torna mai. Il singleton è quindi **di modulo**, e le connessioni non
si accumulano lo stesso grazie a `idleTimeoutMillis`.

## 11bis. La sezione CV

La dashboard mostra **il profilo come lo legge la macchina**, non un'anteprima del
PDF. Il PDF si può già aprire; quello che decide ogni punteggio e ogni frase di ogni
CV generato è il `MasterProfile` strutturato che ci sta sotto, e un'estrazione
sbagliata lì non si vede da nessun'altra parte — si vede solo nei punteggi, mesi
dopo, come una compatibilità che non torna.

**Ogni punto è mostrato scomposto in ACR** (Azione, Contesto, Risultato), con il suo
id stabile in evidenza e un avviso esplicito quando manca il risultato misurabile:
il CV su misura potrà riformulare la frase, non aggiungerci un numero che nel CV di
partenza non c'è. È lo stesso limite che il validatore anti-invenzione della Fase 6
farà rispettare, reso visibile prima invece che dopo.

Tre regole di scrittura, tutte con un motivo:

- **Gli id non sono modificabili.** Sono le chiavi con cui il validatore dirà *quale*
  voce giustifica una frase: si assegnano alla creazione e restano. Si vedono perché
  servono a leggere i suoi messaggi, non perché ci sia da metterci mano.
- **Si salva tutto insieme.** Il profilo è una colonna JSONB: si riscrive per intero
  o non si riscrive. Form indipendenti che salvano a turno darebbero l'illusione di
  modifiche parziali su un dato che parziale non è.
- **Il salvataggio azzera l'embedding.** Se cambiano le esperienze e il vettore resta
  quello di prima, lo Stadio 1 continua a lavorare sul CV vecchio senza che niente lo
  segnali. Meglio nessun vettore che uno che mente: il worker vede
  `embedding_model` nullo e lo ricalcola.

Sotto l'editor del profilo, la stessa pagina ospita anche **Informazioni applicante**
(Fase 11): un elenco a parte, salvato su una tabella diversa, con lo stesso modello di
scrittura ("un solo stato, un solo salvataggio") ma senza l'azzeramento dell'embedding —
il pool non entra nello Stadio 1, solo, facoltativamente, nella Fase 6. Vedi §11quater per
il perché è una tabella a sé e non una sezione in più del `MasterProfile`.

Il **caricamento** di un CV nuovo segue l'architettura split: la dashboard mette il
file nel bucket privato e accoda un `reparse_profile`; a estrarre il testo, farlo
strutturare a un LLM e ricalcolare l'embedding è il PC di casa, perché nessuna delle
tre cose sta in una funzione serverless. Il profilo che ne esce è `reviewed = False`
e il matching non riparte finché non lo si conferma dalla pagina: un'estrazione
automatica non è una revisione. Se l'accodamento fallisce, il file appena caricato
viene rimosso dal bucket — altrimenti resterebbe un PDF che nessuna riga del
database nomina.

## 11ter. Rifinitura: dashboard costi e backup (Fase 10)

**Il consumo si registra come aggregato, non come chiamata.** `llm_usage_log` prende
una riga per ogni volta che un gestore finisce di parlare con l'LLM — una run di
matching (fino a un centinaio di chiamate allo Stadio 2), una generazione di CV
(uno o più tentativi del loop di fit), una lettura di profilo, un giro di
classificazione email — non una riga per singola chiamata al modello. Quegli
aggregati (`MatchReport.llm_calls`/`.input_tokens`, `GeneratedCV.llm_calls`, ...)
il codice li calcola già da soli per il proprio riepilogo in `task.result`;
sommarli di nuovo riga per riga in `llm_usage_log` non aggiungerebbe un dato in
più, solo righe da paginare per una dashboard che li rilegge.

**Il prezzo è "n.d." finché non lo si registra a mano, mai una stima nel codice.**
Vale la stessa regola della RAL non dichiarata (§1): un listino sbagliato è peggio
di nessun listino, perché sembra un dato invece di un'invenzione. Ha reso il
problema concreto il fatto che questa fase è arrivata dopo un cambio di modelli —
`config.py` nomina oggi `gemini-3.5-flash-lite` e `gemini-3.6-flash`, successivi a
questo codice — quindi qualunque prezzo scritto a memoria in un commit sarebbe
stato una supposizione su un listino mai verificato. `jb costs price set` lo
registra leggendolo dalla console del provider attivo (l'unico posto dove è
verificabile davvero, e cambia nel tempo), in una riga `settings` — stesso
pattern di `notify.settings`/`tracking.settings` — non nel codice.

**Nessun monitoraggio automatico di Supabase/Vercel.** Il rischio "free tier
esaurito" in §12 resta mitigato guardando le rispettive console: automatizzarlo
avrebbe richiesto un token API in più per ciascuno dei due servizi, nessuno dei
quali è fra i Prerequisiti (ROADMAP.md) — un costo di configurazione per un
rischio che una run giornaliera regolare, che tiene Supabase sveglio da sola, già
rende improbabile.

**Il backup è CSV, non `pg_dump`.** Un dump binario sarebbe un ripristino più
fedele, ma richiede il client Postgres installato sulla macchina che lo esegue —
su Windows non è garantito, e questo progetto ha già scelto Python 3.12 apposta
per evitare dipendenze di sistema fragili (§5, `onnxruntime`/`fastembed`). Un CSV
per tabella lo scrive `csv` della libreria standard, si apre in Excel per un
controllo al volo, e un `json.loads` rilegge le colonne JSONB se mai servisse un
ripristino a mano. Le colonne binarie (`profile.embedding`, `job.embedding`)
restano fuori: sono ricalcolabili al prossimo `jb match`, e in un CSV
diventerebbero solo byte illeggibili che gonfiano ogni backup senza permettere
niente in più.

**Solo su disco locale, per scelta e non per omissione.** Un bucket Supabase
Storage dedicato ai backup avrebbe richiesto un passo manuale in più di Filippo
sulla console (come è stato per `resumes`, §0.2) prima ancora di scrivere una
riga di codice. La cartella `data/backups/` è già quella con CV e screenshot: zero
credenziali nuove, zero passi di setup in più, a costo di non avere una copia
fuori dal PC di casa — lo stesso compromesso già accettato per l'intero worker
(vedi "il PC spento" in §12). Se in futuro servirà una copia remota, la funzione
pura che scrive i CSV (`write_csv_backup`) non cambia: cambia solo dove va a
finire l'archivio.

**La rotazione conta i file, non i giorni.** Uno scenario già in §12 — il PC di
casa spento per settimane — non deve lasciare zero backup solo perché l'ultimo
supera una soglia di età. `rotate_backups` tiene sempre gli ultimi
`BACKUP_KEEP_COUNT` (default 14), qualunque sia la data dell'ultimo.

## 11quater. Città e informazioni applicante (Fase 11)

**Il filtro sulla città è l'unica eccezione voluta a "un dato mancante non esclude mai"
(§7).** La dashboard mostrava annunci sparsi su decine di città in cui Filippo non si
sarebbe mai trasferito per un lavoro in sede: rumore che il filtro sul paese, pensato per
un mercato molto più ampio ("l'Italia" contro "l'Unione Europea"), non toglieva. La
soluzione non ribalta la regola generale — un annuncio che *non dichiara* la città non
viene comunque scartato, esattamente come un annuncio senza paese dichiarato — ma per una
volta è la lista degli ammessi a essere implicita: un annuncio che *dichiara* una città
diversa da `home_city` viene scartato per difetto, a meno che non sia remoto (che è
esattamente il motivo per cui lo si guarda). `home_city` si deduce con lo stesso ordine di
priorità delle altre soglie derivate dal profilo — prima `candidate_profile.city` (il dato
pensato apposta per "dove vivi davvero"), poi `master_profile.contact.city` — ed è
spegnibile da `restrict_to_home_city` in `settings` per chi preferisce vedere anche gli
annunci fuori sede.

**Il pool di informazioni applicante è una terza tabella, non un'estensione delle due
esistenti.** La domanda naturale è perché non aggiungere questi fatti al `MasterProfile` o
a `CandidateAnswers` (§9, §10). La risposta è che nessuno dei due risponde alla domanda che
questa funzionalità pone:

- Il `MasterProfile` è il CV **rivisto**: ogni voce vi entra dopo che Filippo l'ha
  controllata a mano, ed è il presupposto su cui si regge tutto il resto della Fase 6 — il
  validatore anti-invenzione lo tratta come l'unica fonte di verità possibile. Imporre la
  stessa revisione a un pool pensato per crescere velocemente ("un fatto in più, subito")
  avrebbe reintrodotto l'attrito che la Fase 1.3 esiste apposta per contenere.
- `CandidateAnswers` risponde "cosa scrivere nei campi di un form" — telefono, permesso di
  lavoro, preavviso — e non entra nel matching né nella prosa di un CV: cambia raramente e
  descrive dati anagrafici, non risultati o fatti da argomentare.

Il pool sta in mezzo: fatti veri, spesso specifici per candidatura, non ancora (o mai)
formalizzati in una voce del CV master. Una tabella a sé rende esplicito che la Fase 6 li
tratta diversamente — materiale **facoltativo**, citato solo se pertinente, mai un
sostituto del profilo.

**La Fase 6 sceglie, non ricopia tutto.** Il pool entra nel prompt come blocco a parte
(`## INFORMAZIONI APPLICANTE`), presente solo se non vuoto: un pool con dieci voci vere ma
irrilevanti per un annuncio specifico deve poter produrre un `additional_info` vuoto, allo
stesso modo in cui un'esperienza che non aggiunge nulla resta fuori da `experience` (§9).
Il tetto di tre voci non è arbitrario: è la stessa logica delle cinque `top_keywords`,
abbastanza piccolo da restare una scelta editoriale e non un elenco scaricato in fondo al
documento.

**La quarta regola del validatore non è una regola nuova, è la stessa regola 1+2 applicata
a un'altra fonte.** `additional_info` dichiara un `source_id` che deve esistere nel pool, e
ogni cifra nel testo riscritto deve comparire nella voce citata — identica identità di
controllo dei bullet (§9), separata in una funzione a parte
(`_verifica_informazioni_aggiuntive`) perché il pool non è il `MasterProfile` e i due
elenchi, nel dominio, sono già due cose diverse. Un `additional_info` non vuoto con un pool
vuoto o assente è sempre una violazione: non esiste nessuna fonte a cui l'id potrebbe
appartenere, quindi il caso non richiede un ramo speciale, la stessa verifica lo intercetta.

**La derivazione delle proposte non chiama un LLM.** Certificazioni e progetti sono già
fatti veri e strutturati nel `MasterProfile`: non serve chiedere a un modello di "trovarli"
quando l'informazione è già lì, strutturata, e la si può leggere con un confronto di
stringhe. La sezione web (§11bis) ricalcola le proposte dal profilo e dal pool correnti a
ogni render — non c'è un'estrazione nascosta dietro al bottone "Carica informazioni tramite
CV", che offre solo un punto esplicito per accorgersene, e con lo stesso costo di zero
chiamate LLM che ha reso conveniente derivare la seniority dal profilo invece di chiederla
(§7).

## 12. Rischi noti e mitigazioni

| Rischio | Mitigazione |
|---|---|
| **Il PC spento blocca CV e candidature** | Indicatore online/offline sempre visibile, task in coda che partono al riavvio, digest che dice quando è stata l'ultima run. Il worker è scritto 12-factor: spostarlo su un container da ~5€/mese è mezza giornata di lavoro |
| JSearch free tier stretto (~6 chiamate/giorno) e copre solo ciò che Google indicizza | Query batchate e prioritizzate; le board ATS restano la fonte primaria; l'upgrade a pagamento è una scelta successiva, non un prerequisito |
| Dati personali su servizi terzi | Region EU, bucket privato con signed URL, auth a singolo account, nessun dato in URL o query string |
| `onnxruntime` / `fastembed` senza wheel su Windows | Motivo per cui si usa Python 3.12; fallback su embedding API (Voyage) dietro la stessa interfaccia |
| I selettori noti (Tier A) o l'euristica (Tier B) non trovano un campo, o un ATS cambia il markup | Un campo non trovato non blocca la preparazione — resta nell'elenco "campi non trovati" del risultato — e lo stop prima del submit è comunque una revisione umana obbligatoria come ultima rete: nessun form parte senza che tu l'abbia guardato |
| `MasterProfile` estratto male avvelena tutto a valle | Revisione manuale obbligatoria in Fase 1.3 prima di procedere |
| Free tier Supabase/Vercel esauriti o in pausa | Con una run giornaliera Supabase non va mai in pausa; si monitora dalle rispettive console (nessun token API in più per farlo dal codice, vedi §11ter) |
| Gmail IMAP/SMTP richiede 2FA + App Password | Documentato nel README; il tracking automatico è l'ultima fase e non blocca nulla |
| Il database cresce senza una copia fuori dal PC di casa | `jb backup run` (Fase 10.3) esporta ogni tabella su disco ogni notte; restare solo locale è una scelta esplicita, vedi §11ter |

## 13. Layout del repository

```
Job Board/
  worker/                    Python 3.12 — tutto il lavoro pesante
    jobboard/
      main.py, config.py, db.py, scheduler.py, queue.py, cli.py
      models/                SQLAlchemy — fonte di verita' dello schema
      sources/               base.py + un modulo per adapter
      pipeline/              ingest, normalize, dedup, salary, text
                             criteria, filters, bm25, rank, match
      ai/                    client, embeddings, rubric, validator, prompts/, pricing.py
      cv/                    templates/, render.py, fit.py
      apply/                 router, fields, selectors (Tier A), heuristics (Tier B), browser, guardrails
      notify/                email_digest, imap_reader, classifier
      store/                 profile.py, llm_usage.py (Fase 10.2)
      backup.py              esportazione CSV del database, con rotazione (Fase 10.3)
    alembic/
    pyproject.toml
  web/                       Next.js 16 -> Vercel
    src/auth.ts              Auth.js: Google + allowlist a una email
    src/proxy.ts             redirect ottimistico (ex middleware.ts)
    src/app/                 page.tsx, login/, api/matches/, api/auth/, (dash)/costi/
    src/components/          tabella, drawer, filtri, badge, azioni di riga, costs-table.tsx
    src/lib/                 dal.ts (sessione), queries.ts, filters.ts, format.ts, costs.ts
    src/db/schema.ts         generato da: jobboard gen-web-schema
    src/db/supabase-ca.ts    radice TLS del pooler, fissata
  docs/                      questo documento + ROADMAP.md
  scripts/                   calibrate.py e utility one-off
```
