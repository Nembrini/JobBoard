' Esegue un comando senza aprire nessuna finestra visibile — usato da
' setup-scheduler.cmd per le tre attività di Task Scheduler di JobBoard.
'
' Perché non un'opzione di schtasks: "Nascosta" in Task Scheduler nasconde la
' voce nell'elenco (serve "Mostra attività nascoste" per rivederla), non la
' finestra del processo lanciato — sono due impostazioni diverse con un nome
' che suggerisce la stessa cosa. Le tre attività girano "solo se l'utente ha
' eseguito l'accesso" (serve per Playwright *headful* di "jb apply", che deve
' mostrare davvero un browser) e su una sessione interattiva un eseguibile a
' console apre sempre la sua finestra, a meno che chi lo lancia non gliene
' impedisca la creazione: è quello che fa WshShell.Run con windowStyle a 0.
' VBScript invece di PowerShell perché "wscript.exe" di per sé non ha una
' console propria da mostrare o nascondere — zero rischio del lampeggio che
' capita a volte con "powershell -WindowStyle Hidden" su un eseguibile figlio.
'
' Argomenti: il percorso dell'eseguibile, poi i suoi argomenti separati — non
' un'unica riga di comando già composta, per non dover raddoppiare le
' virgolette a ogni livello (cmd.exe -> schtasks /tr -> qui).
'
' Il terzo parametro di Run (True) aspetta la fine del comando prima di
' terminare questo script: senza, Task Scheduler segnerebbe l'attività
' "completata" subito, mentre jobboard.exe lavora ancora, e una seconda
' esecuzione dello stesso tick (o "Esegui" a mano) potrebbe sovrapporsi.
Dim comando, i

comando = Chr(34) & WScript.Arguments(0) & Chr(34)
For i = 1 To WScript.Arguments.Count - 1
    comando = comando & " " & WScript.Arguments(i)
Next

CreateObject("WScript.Shell").Run comando, 0, True
