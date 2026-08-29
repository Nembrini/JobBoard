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
  range +/-1, location fuori dai mercati scelti, contratto escluso, azienda in
  blocklist, annuncio troppo vecchio, gia' visto o gia' candidato
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

#### Mercato e diritto al lavoro sono due domande diverse

*Mercato* è dove Filippo vuole lavorare; *autorizzazione* è dove può, senza che l'azienda
debba sponsorizzarlo. Un annuncio a Londra fallisce il secondo e non il primo, uno a
Bangalore fallisce entrambi.

Un annuncio remoto salta il controllo sul mercato — è il motivo per cui lo si guarda — ma
**non** quello sull'autorizzazione: un remote da azienda statunitense chiede quasi sempre
di poter già lavorare negli Stati Uniti, e scoprirlo alla domanda del form è tardi.

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

### 7.4 Taratura dei pesi

`scripts/calibrate.py export` scrive un CSV con i sotto-punteggi già calcolati e una
colonna `voto` da riempire a mano; `evaluate` cerca su tutte le 53 130 combinazioni di
pesi a passo 0.05 quella che riproduce meglio i giudizi, misurata in **correlazione di
rango** — perché quello che la dashboard mostra è un ordine, non un valore assoluto.

Sei pesi liberi su trenta esempi trovano sempre *qualcosa*, anche nel rumore. Per questo
lo script non si limita a stampare il vincitore: divide gli esempi in due metà, cerca su
ciascuna e verifica che il vincitore dell'una regga sull'altra. Se le due metà non sono
d'accordo, il messaggio lo dice e i pesi vanno lasciati stare.

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

Il **caricamento** di un CV nuovo segue l'architettura split: la dashboard mette il
file nel bucket privato e accoda un `reparse_profile`; a estrarre il testo, farlo
strutturare a un LLM e ricalcolare l'embedding è il PC di casa, perché nessuna delle
tre cose sta in una funzione serverless. Il profilo che ne esce è `reviewed = False`
e il matching non riparte finché non lo si conferma dalla pagina: un'estrazione
automatica non è una revisione. Se l'accodamento fallisce, il file appena caricato
viene rimosso dal bucket — altrimenti resterebbe un PDF che nessuna riga del
database nomina.

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
      pipeline/              ingest, normalize, dedup, salary, text
                             criteria, filters, bm25, rank, match
      ai/                    client, embeddings, rubric, validator, prompts/
      cv/                    templates/, render.py, fit.py
      apply/                 router, greenhouse, lever, ashby, workable, assisted
      notify/                email_digest, imap_reader, classifier
    alembic/
    pyproject.toml
  web/                       Next.js 16 -> Vercel
    src/auth.ts              Auth.js: Google + allowlist a una email
    src/proxy.ts             redirect ottimistico (ex middleware.ts)
    src/app/                 page.tsx, login/, api/matches/, api/auth/
    src/components/          tabella, drawer, filtri, badge, azioni di riga
    src/lib/                 dal.ts (sessione), queries.ts, filters.ts, format.ts
    src/db/schema.ts         generato da: jobboard gen-web-schema
    src/db/supabase-ca.ts    radice TLS del pooler, fissata
  docs/                      questo documento + ROADMAP.md
  scripts/                   calibrate.py e utility one-off
```
