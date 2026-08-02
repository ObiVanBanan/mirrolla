$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
    docker build `
      -f deploy/analysis-sandbox/Dockerfile `
      -t mirrolla-analysis-sandbox:py312 `
      .
} finally {
    Pop-Location
}
