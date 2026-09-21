param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & $Python -m PyInstaller --noconfirm --onefile --windowed --name JochJell-Controller --version-file 'scripts/version_info.txt' --icon 'frontend/assets/logo.ico' --add-data 'frontend:frontend' --distpath dist --workpath build desktop_app.py
    if ($LASTEXITCODE -ne 0) { throw 'Windows executable build failed.' }
    Get-FileHash -Algorithm SHA256 -LiteralPath "$projectRoot\dist\JochJell-Controller.exe"
} finally {
    Pop-Location
}
