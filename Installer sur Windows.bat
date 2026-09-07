@echo off
rem ---------------------------------------------------------------------
rem  Vigie Civique - installation
rem
rem  DOUBLE-CLIQUER CE FICHIER. Rien d autre a faire, rien a taper.
rem
rem  Si Windows affiche  "Windows a protege votre ordinateur" :
rem  cliquer "Informations complementaires" puis "Executer quand meme".
rem  C est le controle de provenance de Windows, il ne dit rien du contenu.
rem
rem  L installation se passe dans votre navigateur ; cette fenetre affiche
rem  l avancement et doit rester ouverte.
rem ---------------------------------------------------------------------
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "installateur\amorcage.ps1"
echo.
pause
