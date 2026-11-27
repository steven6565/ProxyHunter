# Build ProxyHunter v3.0 portable EXE + installer on Windows 10/11 x64.
# Requires Python 3.11+ on PATH. Inno Setup is optional (Setup.exe only).

param([switch]$SkipInstaller)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$desktop = Join-Path $root "desktop"
$builds = Join-Path $root "builds"
Set-Location $root

Write-Host "==> Creating build environment"
if (-not (Test-Path (Join-Path $root ".venv-win"))) {
    py -3 -m venv .venv-win
}
$python = Join-Path $root ".venv-win\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $desktop "requirements.txt")
& $python -m pip install "pyinstaller>=6.5"

Write-Host "==> Building portable edition"
Push-Location $desktop
& $python -m PyInstaller --noconfirm --distpath $builds ProxyHunter.spec
Pop-Location

Write-Host "==> Portable output: $builds\ProxyHunter_portable\ProxyHunter.exe"
$exe = Join-Path $builds "ProxyHunter_portable\ProxyHunter.exe"
if (-not (Test-Path $exe)) { throw "EXE was not produced" }
Get-Item $exe | Select-Object Name, Length, LastWriteTime

if (-not $SkipInstaller) {
    $isc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $isc) {
        & $isc (Join-Path $desktop "installer.iss")
    } else {
        Write-Warning "Inno Setup not found - Setup.exe not built. Install Inno Setup 6 or use GitHub Actions."
    }
}
Write-Host "==> Done. Executable is UNSIGNED unless a signing certificate is configured."
