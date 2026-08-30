@echo off
REM Crea le due attivita' di Task Scheduler che rendono automatica la raccolta
REM giornaliera (Fase 8.1/8.2, vedi docs/ROADMAP.md e docs/ARCHITECTURE.md): senza
REM di loro nessun processo sul PC esegue mai i task che la dashboard accoda, e
REM i bottoni restano in coda per sempre anche a PC acceso.
REM
REM Uso: da un prompt cmd.exe (non serve PowerShell), una volta sola:
REM     .\setup-scheduler
REM E' sicuro rilanciarlo: /F sovrascrive un'attivita' con lo stesso nome
REM invece di fallire con "esiste gia'".

echo Creo "JobBoard - worker" (jb work --once ogni minuto)...
schtasks /create /f /tn "JobBoard - worker" ^
  /tr "\"%~dp0worker\.venv\Scripts\jobboard.exe\" work --once" ^
  /sc MINUTE /mo 1
if errorlevel 1 goto :errore

echo.
echo Creo "JobBoard - trigger giornaliero" (jb work trigger alle 07:00)...
schtasks /create /f /tn "JobBoard - trigger giornaliero" ^
  /tr "\"%~dp0worker\.venv\Scripts\jobboard.exe\" work trigger" ^
  /sc DAILY /st 07:00
if errorlevel 1 goto :errore

echo.
echo Fatto. Resta un solo passo, che schtasks non espone da riga di comando:
echo   1. Apri Task Scheduler (cerca "Utilita' di pianificazione" nel menu Start)
echo   2. Trova "JobBoard - trigger giornaliero" e apri le sue Proprieta'
echo   3. Scheda Impostazioni: spunta "Esegui l'attivita' il prima possibile se
echo      un avvio pianificato viene ignorato" - recupera un giorno a PC spento
echo      invece di saltarlo del tutto.
echo.
echo Da qui in poi non serve piu' avviare nulla a mano: ne' la raccolta ne' il
echo refresh della dashboard, che mostra dati freschi ogni volta che la apri.
goto :fine

:errore
echo.
echo schtasks ha risposto con un errore - vedi il messaggio sopra. Le attivita'
echo eventualmente gia' create restano; correggi e rilancia .\setup-scheduler.
exit /b 1

:fine
