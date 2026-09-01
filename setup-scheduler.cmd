@echo off
REM Crea le tre attivita' di Task Scheduler che rendono automatiche la raccolta
REM giornaliera (Fase 8.1/8.2) e il backup notturno (Fase 10.3, vedi
REM docs/ROADMAP.md e docs/ARCHITECTURE.md): senza di loro nessun processo sul PC
REM esegue mai i task che la dashboard accoda, e i bottoni restano in coda per
REM sempre anche a PC acceso.
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
echo Creo "JobBoard - backup notturno" (jb backup run alle 03:00, Fase 10.3)...
REM Prima del trigger delle 07:00 e non dopo: se la raccolta di stanotte
REM dovesse rovinare qualcosa, il backup delle 03:00 e' gia' quello di ieri
REM sera, non uno che include gia' il guasto.
schtasks /create /f /tn "JobBoard - backup notturno" ^
  /tr "\"%~dp0worker\.venv\Scripts\jobboard.exe\" backup run" ^
  /sc DAILY /st 03:00
if errorlevel 1 goto :errore

echo.
echo Imposto il recupero delle due attivita' giornaliere se il PC era spento
echo all'ora prevista ("esegui appena possibile se un avvio pianificato viene
echo ignorato")...
REM schtasks.exe non espone questa spunta da riga di comando, ma il modulo
REM PowerShell ScheduledTasks si': niente XML scritto a mano, e verificato che
REM la proprieta' regge davvero (Get-ScheduledTask la rilegge True dopo la
REM scrittura), non solo che il comando sia uscito senza errori.
powershell -NoProfile -NonInteractive -Command "foreach ($n in 'JobBoard - trigger giornaliero','JobBoard - backup notturno') { $t = Get-ScheduledTask -TaskName $n; $s = $t.Settings; $s.StartWhenAvailable = $true; Set-ScheduledTask -TaskName $n -Settings $s | Out-Null }"
if errorlevel 1 goto :errore

echo.
echo Fatto. Da qui in poi non serve piu' avviare nulla a mano: ne' la raccolta,
echo ne' il backup, ne' il refresh della dashboard, che mostra dati freschi ogni
echo volta che la apri. "jobboard doctor" controlla anche queste tre attivita',
echo se un giorno una di loro risultasse di nuovo disabilitata.
goto :fine

:errore
echo.
echo schtasks ha risposto con un errore - vedi il messaggio sopra. Le attivita'
echo eventualmente gia' create restano; correggi e rilancia .\setup-scheduler.
exit /b 1

:fine
