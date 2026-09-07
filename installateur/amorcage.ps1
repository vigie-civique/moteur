# amorcage.ps1 — la même chose que amorcage.sh, pour Windows.
#
# Trouver un Python ≥ 3.11 ; à défaut en poser un DANS installateur\.outils\,
# par `uv`. Rien sur le système, aucun droit d'administrateur, aucun PATH
# modifié : supprimer le dossier suffit à tout désinstaller.
#
# Windows n'a pas de Python d'origine, et celui du Microsoft Store est un
# raccourci qui ouvre la boutique au lieu de s'exécuter. Ce cas est traité plus
# bas — c'est le piège le plus fréquent de l'installation sur Windows.

$ErrorActionPreference = "Stop"
$ICI     = Split-Path -Parent $MyInvocation.MyCommand.Path
$OUTILS  = Join-Path $ICI ".outils"

function Assez-Recent($chemin) {
  if (-not (Test-Path $chemin)) { return $false }
  try {
    & $chemin -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
  } catch { return $false }
}

function Trouver-Python {
  # Le Python posé par nous d'abord, puis ceux de la machine.
  $candidats = @(Get-ChildItem -Path (Join-Path $OUTILS "python") -Filter "python.exe" `
                   -Recurse -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
  foreach ($nom in @("python3.13", "python3.12", "python3.11", "python3", "python")) {
    $trouve = Get-Command $nom -ErrorAction SilentlyContinue
    foreach ($t in $trouve) {
      # Le raccourci du Microsoft Store porte l'extension .exe et ne fait
      # qu'ouvrir la boutique : il répond à `Get-Command`, il pèse quelques
      # kilo-octets, et il ne sait rien exécuter. Le sauter.
      if ($t.Source -like "*WindowsApps*") { continue }
      $candidats += $t.Source
    }
  }
  foreach ($c in $candidats) { if (Assez-Recent $c) { return $c } }
  return $null
}

function Poser-Python {
  $cible = if ([System.Environment]::Is64BitOperatingSystem -and
                $env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "uv-aarch64-pc-windows-msvc" }
           else { "uv-x86_64-pc-windows-msvc" }

  Write-Host ""
  Write-Host "  Aucun Python récent sur cette machine."
  Write-Host "  Je vais en poser un DANS ce dossier (environ 40 Mo, rien sur le système)."
  Write-Host ""

  New-Item -ItemType Directory -Force -Path $OUTILS | Out-Null
  $zip = Join-Path $OUTILS "uv.zip"
  # `latest` et non une version figée : cet outil ne sert qu'à télécharger un
  # interpréteur. Un numéro figé qui disparaîtrait du dépôt bloquerait toute
  # installation, partout, sans recours pour celui qui la subit.
  Invoke-WebRequest -UseBasicParsing `
    -Uri "https://github.com/astral-sh/uv/releases/latest/download/$cible.zip" `
    -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $OUTILS -Force
  Remove-Item $zip -Force
  $uv = Get-ChildItem -Path $OUTILS -Filter "uv.exe" -Recurse | Select-Object -First 1
  if (-not $uv) { throw "uv téléchargé mais introuvable dans l'archive." }

  # Les deux variables enferment uv dans notre dossier : sans elles il écrit
  # dans le profil de l'utilisateur, hors de ce qu'il croit avoir installé.
  $env:UV_PYTHON_INSTALL_DIR = Join-Path $OUTILS "python"
  $env:UV_CACHE_DIR          = Join-Path $OUTILS "cache-uv"
  & $uv.FullName python install 3.12
  if ($LASTEXITCODE -ne 0) { throw "uv n'a pas pu poser Python." }

  $pose = Get-ChildItem -Path (Join-Path $OUTILS "python") -Filter "python.exe" -Recurse |
          Select-Object -First 1
  if (-not $pose) { throw "Python posé mais introuvable ensuite." }
  return $pose.FullName
}

$PY = Trouver-Python
if (-not $PY) { $PY = Poser-Python }

Write-Host ""
Write-Host "  Python : $PY"
& $PY (Join-Path $ICI "assistant.py")
