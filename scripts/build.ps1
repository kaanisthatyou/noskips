# Builds rateify.exe, a portable zip, and (if Inno Setup is installed) the installer.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$version = (Select-String -Path app.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building rateify $version"

python -m PyInstaller rateify.spec --noconfirm

New-Item -ItemType Directory -Force release | Out-Null
Copy-Item dist\rateify.exe .\rateify.exe -Force

Compress-Archive -Force `
    -Path dist\rateify.exe, README.md, LICENSE `
    -DestinationPath "release\rateify-$version-portable.zip"

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($iscc) {
    & $iscc installer.iss | Select-Object -Last 1
} else {
    Write-Host "Inno Setup not found - skipped installer (winget install JRSoftware.InnoSetup)"
}

Write-Host "Done - artifacts in release\"
Get-ChildItem release | Select-Object Name, Length
