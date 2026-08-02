param(
    [string]$Distro = "Ubuntu",
    [string]$ProjectPath = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath $ProjectPath).Path
$drive = $repoRoot.Substring(0, 1).ToLowerInvariant()
$rest = $repoRoot.Substring(2).Replace('\', '/').TrimStart('/')
$wslRepoRoot = "/mnt/$drive/$rest"

if (-not $wslRepoRoot) {
    throw "Failed to convert project path to a WSL path."
}

wsl.exe -d $Distro -- bash -lc "cd '$wslRepoRoot' && bash scripts/vllm/start_qwen_coder.sh"
