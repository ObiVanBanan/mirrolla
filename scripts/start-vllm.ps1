param(
    [string]$Distro = "Ubuntu",
    [string]$ProjectPath = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath $ProjectPath).Path
Push-Location $repoRoot
try {
    $wslRepoRoot = python -m agent.runtime.gemma_local --wsl-path $repoRoot
} finally {
    Pop-Location
}

if (-not $wslRepoRoot) {
    throw "Failed to convert project path to a WSL path."
}

wsl.exe -d $Distro -- bash -lc "cd '$wslRepoRoot' && bash scripts/vllm/start_gemma4.sh"
