@echo off
REM Scorciatoia per gli script npm della dashboard, da eseguire dalla radice
REM del progetto.
REM
REM Serve perche' su questa macchina la execution policy di PowerShell e'
REM AllSigned: il comando "npm" e' in realta' lo script npm.ps1, non e' firmato
REM digitalmente e viene bloccato con
REM
REM     Impossibile caricare il file C:\Program Files\nodejs\npm.ps1.
REM     Il file non e' firmato digitalmente.
REM
REM npm.cmd non e' uno script PowerShell e quindi passa senza che si debba
REM abbassare una impostazione di sicurezza di tutta la macchina.
REM
REM Uso:  .\web dev        .\web build        .\web lint
cd /d "%~dp0web" && npm.cmd run %*
