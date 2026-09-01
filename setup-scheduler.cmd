@echo off
REM Crea le tre attivita' di Task Scheduler che rendono automatiche la raccolta
REM giornaliera (Fase 8.1/8.2) e il backup notturno (Fase 10.3, vedi
REM docs/ROADMAP.md e docs/ARCHITECTURE.md): senza di loro nessun processo sul PC
REM esegue mai i task che la dashboard accoda, e i bottoni restano in coda per
REM sempre anche a PC acceso.
REM
REM Ognuna passa da "run-hidden.vbs": senza, ogni tick apre e chiude una console
REM nera visibile sullo schermo - "Nascosta" in Task Scheduler nasconde solo la
REM voce nell'elenco, non la finestra del processo. Restano "solo se l'utente
REM ha eseguito l'accesso" e non "sia connesso o no": serve alla candidatura,
REM che apre un Chromium headful apposta perche' Filippo lo veda prima del
REM submit, e una sessione non interattiva (Session 0) non ha un desktop su cui
REM mostrarlo.
REM
REM Uso: da un prompt cmd.exe (non serve PowerShell), una volta sola:
REM     .\setup-scheduler
REM E' sicuro rilanciarlo: /F sovrascrive un'attivita' con lo stesso nome
REM invece di fallire con "esiste gia'".

echo Creo "JobBoard - worker" (jb work --once ogni minuto, senza finestra)...
schtasks /create /f /tn "JobBoard - worker" ^
  /tr "wscript.exe //B \"%~dp0run-hidden.vbs\" \"%~dp0worker\.venv\Scripts\jobboard.exe\" work --once" ^
  /sc MINUTE /mo 1
if errorlevel 1 goto :errore

echo.
echo Creo "JobBoard - trigger giornaliero" (jb work trigger alle 07:00, senza finestra)...
schtasks /create /f /tn "JobBoard - trigger giornaliero" ^
  /tr "wscript.exe //B \"%~dp0run-hidden.vbs\" \"%~dp0worker\.venv\Scripts\jobboard.exe\" work trigger --scheduled" ^
  /sc DAILY /st 07:00
if errorlevel 1 goto :errore

echo.
echo Creo "JobBoard - backup notturno" (jb backup run alle 03:00, senza finestra, Fase 10.3)...
REM Prima del trigger delle 07:00 e non dopo: se la raccolta di stanotte
REM dovesse rovinare qualcosa, il backup delle 03:00 e' gia' quello di ieri
REM sera, non uno che include gia' il guasto.
REM
REM --scheduled fa leggere l'interruttore "Backup notturno" di Impostazioni:
REM senza, un `jb backup run` lanciato a mano (prima di una migration rischiosa,
REM per dire) resterebbe soggetto a un interruttore pensato solo per il tick
REM automatico, e "fallo prima di questa modifica" potrebbe silenziosamente non
REM succedere.
schtasks /create /f /tn "JobBoard - backup notturno" ^
  /tr "wscript.exe //B \"%~dp0run-hidden.vbs\" \"%~dp0worker\.venv\Scripts\jobboard.exe\" backup run --scheduled" ^
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
echo volta che la apri. Nessuna delle tre attivita' apre piu' una finestra sullo
echo schermo. "Aggiorna adesso" e "Rivaluta tutto" funzionano allo stesso modo:
echo il click accoda, "JobBoard - worker" lo prende entro un minuto ed esegue da
echo solo. Ognuna delle tre si puo' fermare senza toccare Task Scheduler dalla
echo pagina Impostazioni della dashboard ("Attivita' pianificate"), e
echo "jobboard doctor" le controlla tutte a ogni avvio, se un giorno una di loro
echo risultasse di nuovo disabilitata o spenta da li'.
goto :fine

:errore
echo.
echo schtasks ha risposto con un errore - vedi il messaggio sopra. Le attivita'
echo eventualmente gia' create restano; correggi e rilancia .\setup-scheduler.
exit /b 1

:fine
