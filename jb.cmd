@echo off
REM Scorciatoia per la CLI del worker, da eseguire dalla radice del progetto.
REM
REM Serve perche' PowerShell non accetta un percorso relativo come comando se non
REM inizia con .\ : "worker\.venv\Scripts\jobboard.exe" viene interpretato come
REM nome di modulo e da' "Impossibile caricare il modulo 'worker'".
REM
REM Uso:  .\jb doctor        .\jb gen-web-schema        .\jb --help
"%~dp0worker\.venv\Scripts\jobboard.exe" %*
