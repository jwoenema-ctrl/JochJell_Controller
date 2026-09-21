param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & $Python -m PyInstaller --noconfirm --onefile --windowed --name JochJell-Controller-Native --version-file 'scripts/version_info.txt' --icon 'frontend/assets/logo.ico' --add-data 'frontend:frontend' --collect-all webview --hidden-import pythonnet --distpath dist --workpath build native_app.py
    if ($LASTEXITCODE -ne 0) { throw 'Embedded Windows build failed.' }
    Get-FileHash -Algorithm SHA256 -LiteralPath "$projectRoot\dist\JochJell-Controller-Native.exe"
} finally {
    Pop-Location
}
