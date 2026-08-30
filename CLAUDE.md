# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Lingua

**Codice, commenti, docstring, messaggi di commit e risposte sono in italiano.** I nomi
delle API di terzi e i termini tecnici consolidati restano in inglese (`RawJob`,
`server_default`, "embedding"). Non tradurre il codice esistente; scrivi il nuovo nello
stesso registro.

I commenti spiegano **perché**, non cosa: quasi tutti quelli presenti documentano un guasto
già successo. Prima di rimuoverne uno, controlla che il motivo non valga ancora.

## Comandi

Su questa macchina la execution policy di PowerShell è `AllSigned`, che rifiuta `npm.ps1`
e ogni `.ps1` non firmato. I wrapper alla radice esistono per quello — non sono comodità,
sono l'unico modo di eseguire questi comandi senza abbassare un'impostazione di sicurezza
dell'intera macchina.

```bash
.\jb <comando>      # CLI del worker (worker\.venv\Scripts\jobboard.exe)
.\web dev|build|lint
.\setup-scheduler   # crea le due attività di Task Scheduler per la raccolta automatica (una tantum)
```

### Worker

```bash
worker\.venv\Scripts\python.exe -m pytest -q              # 377 test, nessun database
worker\.venv\Scripts\python.exe -m pytest tests/test_jsearch.py -q
worker\.venv\Scripts\python.exe -m pytest -q -k "publisher"   # un singolo test
worker\.venv\Scripts\ruff.exe check . --fix
worker\.venv\Scripts\ruff.exe format .
worker\.venv\Scripts\mypy.exe jobboard                    # strict, deve restare pulito
```

I test **non toccano il database**: sono unit test su schema, parser e pipeline. Un test
che richiede Postgres non esiste ancora e non va aggiunto senza prima costruire la
fixture.

### Pipeline, a mano

```bash
.\jb doctor                       # configurazione, database, embedding, Playwright
.\jb ingest --dry-run             # raccoglie e normalizza senza scrivere
.\jb ingest --commit
.\jb match --commit               # imbuto a 3 stadi; --rescore rivaluta tutto
.\jb matches criteria --top-n 100 --reserved-floor 10   # tetto Stadio 2 e riserva per le fonti a budget
.\jb work                         # consumer della coda + battito; --once per un giro solo
.\jb work trigger                 # accoda un run_pipeline, per Task Scheduler (Fase 8.1/8.2)
.\jb sources list|enable|boards
.\jb profile import|load|embed|show
.\jb cv generate <match-id>       # CV su misura; --no-upload lo lascia solo su disco
.\jb cv check <file.pdf>          # come lo vedrebbe un parser ATS
.\jb apply send <match-id>        # apre il form nel browser, lo compila, si ferma prima del submit
```

**`--dry-run` non prova la scrittura.** Normalizza e stampa, ma non tocca i vincoli di
colonna: una run è già caduta su un `external_id` più lungo della colonna dopo che il
dry-run era passato. Quando cambia una fonte, la verifica che conta è `--commit`.

### Schema del database

I modelli SQLAlchemy in `worker/jobboard/models/` sono **l'unica fonte di verità**.
`web/src/db/schema.ts` è generato: non modificarlo a mano.

```bash
# 1. modifica worker/jobboard/models/
cd worker && .venv\Scripts\alembic.exe revision --autogenerate -m "descrizione"
cd worker && .venv\Scripts\alembic.exe upgrade head
.\jb gen-web-schema               # rigenera i tipi TypeScript
```

`alembic check` segnala oggi una differenza sui vincoli CHECK degli enum: è preesistente e
cosmetica (la migration iniziale li ha scritti con un'espressione diversa da quella che
SQLAlchemy genera). Non è drift dei default.

## Architettura

### Topologia split — e cosa smette di funzionare a PC spento

```
Vercel (Next.js 16)  →  Supabase Postgres + Storage (EU)  ←  worker Python (PC di casa)
```

Vercel non può eseguire Playwright, gli embedding ONNX né una pipeline che macina
centinaia di annunci. Il ponte è la tabella `task`: la dashboard inserisce una riga, il
worker la raccoglie con `SELECT … FOR UPDATE SKIP LOCKED`.

- **Sempre disponibile:** consultare, filtrare, aprire un annuncio, modificare il profilo
  CV, cambiare stato a un match.
- **Richiede il worker acceso:** rileggere un CV caricato, generare un CV su misura,
  inviare una candidatura. L'indicatore online/offline in testata esiste perché senza,
  premere un bottone a PC spento darebbe un silenzio indistinguibile da un errore.

Il consumer (`jobboard/queue.py`) preleva in una transazione **a sé** e poi la chiude:
tenerla aperta per tutta la durata di una chiamata LLM bloccherebbe la riga e impedirebbe
al battito di scriversi. I gestori stanno in `jobboard/handlers.py`, registrati con
`@handler(TaskType.X)`; `queue.py` li importa dentro `run_once` per evitare il ciclo di
import.

### `default=` non è `server_default=`

Il tranello più costoso di questo repository, già pagato due volte. In SQLAlchemy
`default=` è un valore **lato Python**: lo applica la sessione al flush e nel DDL non
finisce mai. Ogni `INSERT` che non passa dall'ORM — cioè tutto ciò che arriva da Vercel —
finisce contro il `NOT NULL` senza valore.

Ogni colonna `NOT NULL` con un `default=` deve avere anche `server_default=default_sql(…)`.
`enum_column` lo deriva da solo. Il test
`test_ogni_default_dell_orm_ha_anche_un_default_sul_database` lo impone, e
`gen_web_schema.py` emette `.default()` in TypeScript **solo** a fronte di un
`server_default` vero.

### Matching — imbuto a 3 stadi (`worker/jobboard/pipeline/`)

```
Stadio 0  filtri duri in Python  ~800 → ~150   filters.py, criteria.py
Stadio 1  cosine + BM25 ibrido   ~150 → 40     rank.py, bm25.py
Stadio 2  rubrica pesata via LLM  40 → punteggio   ai/rubric.py
```

Due principi che il codice applica ovunque e che vanno preservati:

- **«Un dato mancante non esclude mai.»** Un terzo degli annunci non dichiara il paese, due
  quinti la seniority. Un filtro che tratta il silenzio della fonte come un rifiuto butta
  via metà della tabella. I predicati stanno in Python e non in una `WHERE` proprio perché
  ogni scarto porta con sé il suo motivo, scritto in `match.filtered_reason`.
- **«Assenza di prove non è prova di eccellenza.»** Nella rubrica `50` significa "non ci
  sono elementi per giudicare", non "mediocre". `neutralize_unknowable()` riporta a 50 i
  criteri su cui l'annuncio tace — senza, un annuncio con quattro righe di descrizione
  prendeva `must_have_coverage: 100` e finiva primo.

Conseguenza sulle soglie: con vari criteri a 50, un annuncio davvero buono si ferma sotto
70. Le fasce in `web/src/lib/format.ts` (60/45) sono basse di proposito.

### Fonti (`worker/jobboard/sources/`)

Un adapter fa **una cosa sola**: interroga la sua API e restituisce dei `RawJob`. Non
normalizza, non deduplica, non scrive. Aggiungerne uno significa creare il modulo e
aggiungerlo all'elenco in `sources/__init__.py`.

- Una fonte con `required_settings` nasce **disattivata**: accenderla senza chiave
  produrrebbe solo un errore a ogni run. Si accende con `.\jb sources enable <slug>`.
- **`publisher`** è il portale su cui l'annuncio vive davvero ("LinkedIn"), distinto
  dall'adapter che l'ha pescato ("jsearch"). È quello che la dashboard mostra nella colonna
  Fonte: da LinkedIn ci si candida in un modo, da una board Greenhouse in un altro.
- `external_id` deve essere **stabile fra due run**, altrimenti lo stesso annuncio risulta
  nuovo ogni giorno. Oltre 300 caratteri viene sostituito dal suo hash — mai troncato, che
  farebbe collidere annunci diversi in silenzio.
- JSearch è l'unica via legale verso LinkedIn/Indeed, con ~200 chiamate al mese: il budget
  conta le richieste HTTP davvero partite, retry inclusi. La sua v5 ha cambiato endpoint,
  forma della risposta e nomi dei campi senza preavviso; `tests/test_jsearch.py` fissa la
  forma perché il prossimo cambio rompa un test invece di una run notturna.

### Regola sulla retribuzione

Se `salary_is_stated` è falso, si scrive `n.d.` — mai la stima. Il database contiene anche
`salary_eur_year_*`, che serve a ordinare e confrontare, e alcune fonti offrono una stima
algoritmica: nessuna delle due finisce mai nella colonna RAL. Una cifra stimata mostrata
come dichiarata rende inservibile l'unico dato per cui si guarda quella colonna.

### Generazione del CV (`worker/jobboard/cv/`, `ai/tailor.py`, `ai/validator.py`)

**Dal modello passa solo la prosa.** Al generatore si chiedono quattro cose — le cinque
keyword, il summary, i bullet riscritti, le competenze — e nient'altro. Date, aziende,
titoli di studio e recapiti li copia il template dal `MasterProfile` e non entrano
nemmeno nella richiesta: un modello che non tocca le date non può sbagliarle. Per lo
stesso motivo l'ordine cronologico lo impone `render.py`, non il modello.

**Un id è un'affermazione, non una prova.** Ogni bullet dichiara il `source_id` da cui
viene e ogni competenza la sua `source`, ma il validatore non si ferma alla provenienza
dichiarata: verifica anche che **ogni cifra del testo generato compaia nella fonte**. È
la regola che conta di più — un numero falso su un CV non si recupera in un colloquio.

Due falsi positivi già pagati, entrambi capaci di rendere inutile il validatore, perché
uno che blocca i CV giusti viene spento:

- **i numeri a lettere.** Il profilo conserva il CV come è scritto ("da sei ore a venti
  minuti", "dal quaranta all'ottanta percento"), il CV generato usa le cifre. Il
  vocabolario in `validator.py` traduce entrambi i versi, italiano e inglese. E
  «per cento» non è il numero cento;
- **le competenze tradotte.** Un profilo italiano che dichiara "Lavoro in team" produce
  un CV inglese che dice "Teamwork". Il rimedio non è il match sfocato — con quello
  `Java` giustificava `JavaScript` — ma la provenienza dichiarata: `text` è come si
  scrive, `source` è la voce del profilo, confrontata esatta.

**Il loop di fit toglie prima di stringere.** Stringere è gratis, ed è per questo che è
la tentazione sbagliata. Quanto sfora si misura guardando dove arriva l'ultima riga
sull'ultima pagina, perché "due pagine" non distingue tre righe di troppo da mezza
pagina. Ogni compressione ripassa dal validatore: una riscrittura è una generazione.

Il prompt sta in `ai/prompts/cv_writer.md`, in un file a sé perché si possa sostituire
senza toccare il codice. Non chiedergli quello che il codice già verifica.

### Candidatura (`worker/jobboard/apply/`)

**Il Tier A non invia via API.** Il piano iniziale lo prevedeva; verificato leggendo la
documentazione ufficiale prima di scrivere il client: Greenhouse blocca il form pubblico
con reCAPTCHA Enterprise, Lever/Ashby/Workable richiedono una chiave API che genera solo
l'azienda, mai il candidato. Tier A e Tier B condividono quindi lo stesso motore —
Playwright headful sul PC — e **si fermano entrambi prima del submit**: cambia solo se il
form si compila con selettori dedicati a un ATS noto (`selectors.py`) o con un'euristica
su label e attributi (`heuristics.py`). Il perché per esteso, con le fonti delle quattro
API, è in `docs/ARCHITECTURE.md` §10. Non riproporre il piano originale senza aver riletto
quella sezione.

Conseguenza sugli stati: nessun codice del worker scrive mai `ApplicationStatus.SUBMITTED`.
Lo scrive un click esplicito in dashboard (`markApplicationSubmitted`, chiamata solo da
`segnaCandidaturaInviata` in `web/src/lib/cv-actions.ts`), **dopo** che l'invio è avvenuto
davvero nel browser. Il worker porta una candidatura solo fino a `needs_human`.

I guardrail (`guardrails.py`) sono decisioni pure su numeri già contati, non query: il cap
giornaliero conta le candidature **preparate**, non quelle spedite — è l'apertura di un
browser verso un sito di terzi l'azione automatica da limitare, non un invio che ormai non
succede mai senza un click umano.

## Lato web (`web/`)

Leggi `web/AGENTS.md`: **questa non è la Next.js che conosci.** La documentazione della
versione installata sta in `web/node_modules/next/dist/docs/` e va consultata prima di
scrivere codice. In particolare `middleware.ts` è diventato `proxy.ts`, `params`,
`searchParams`, `cookies()` e `headers()` sono asincroni, e i tipi `PageProps<'/rotta'>` /
`LayoutProps<'/'>` arrivano da `npx next typegen`.

### Database dal lato Next.js

- **`pg`, non `postgres-js`.** Non è preferenza: sotto Next.js 16 `postgres-js` serve una
  sola richiesta e poi la connessione riutilizzata non restituisce più niente. Nessun
  errore, nessun timeout.
- **Singleton di modulo, non `globalThis`.** Next valuta i moduli in più contesti e
  `globalThis` è condiviso fra questi, il socket TCP no.
- **Il certificato radice di Supabase è fissato** in `src/db/supabase-ca.ts`: senza,
  `pg` si collega **in chiaro**, perché la connection string di Supabase non contiene
  `sslmode` e la catena si chiude su una CA privata assente dal trust store.

### Autenticazione a due livelli

`src/proxy.ts` reindirizza chi non ha un cookie, ma gira anche sulle rotte prelevate in
anticipo dal browser: legge solo il cookie e non tocca il database. Il controllo che decide
se dei dati possono uscire sta **accanto ai dati**, in `src/lib/dal.ts`, e lo chiama ogni
funzione di lettura in `queries.ts` e `profile.ts`. Una rotta nuova eredita la protezione
perché passa di lì, non perché qualcuno si ricorda di aggiungerla a un elenco.

Le Server Action sono endpoint pubblici: validano l'input anche quando a chiamarle è codice
nostro.

### Il profilo CV è definito due volte

`worker/jobboard/schemas/profile.py` (Pydantic) e `web/src/lib/master-profile.ts` (Zod)
descrivono lo stesso oggetto. Il profilo è una colonna JSONB e il database non ne verifica
la forma: se le due definizioni divergono, la dashboard scrive un JSON che il worker non
riesce più a rileggere, e l'errore arriva la sera dopo. **Toccandone una, aggiorna
l'altra.** Il Pydantic ha `extra="forbid"`, quindi lo Zod usa `strictObject`.

Gli `id` delle voci sono chiavi stabili: il validatore anti-invenzione della Fase 6 le userà
per dire *quale* voce del CV giustifica una frase di quello generato. Si assegnano alla
creazione e non si modificano.

### `.env`: il commento che diventa il valore

python-dotenv riconosce un commento in coda **solo quando davanti c'è un valore**. Scrivere

```
RAPIDAPI_KEY=            # per JSearch
```

non lascia la variabile vuota: le assegna la stringa `# per JSearch`. Ne sono già derivate
due diagnosi sbagliate. I commenti vanno **sopra** la variabile, e `.\jb doctor` giudica la
forma del valore e non la sua presenza.

## Documentazione

- `docs/ARCHITECTURE.md` — le decisioni e il perché, comprese quelle rovesciate dai fatti.
- `docs/ROADMAP.md` — fasi, sottofasi, criteri di verifica e cosa può fare solo Filippo.
- `README.md` — cosa fa il sistema e come si installa.

Quando una decisione cambia per un motivo scoperto eseguendo, aggiorna `ARCHITECTURE.md`
con il motivo, non solo con la conclusione.

## Formato delle risposte

Filippo chiede che ogni risposta si chiuda con quattro sezioni:
**COSA È STATO FATTO · MIO INTERVENTO · PROBLEMI/ERRORI · PROSSIMA FASE/I**, dove
*MIO INTERVENTO* elenca passo passo cosa deve fare lui.

Le istruzioni su console di terze parti (RapidAPI, Google Cloud, Vercel, Supabase) vanno
**verificate aprendo il sito**, non scritte a memoria: nomi di schede e bottoni cambiano, e
un passo sbagliato manda a cercare un bottone che non esiste. Dove serve il suo login e non
si può guardare, dillo invece di riempire il buco.
