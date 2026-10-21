# Full daily workflow: fetch new items -> synthesize ideas -> build the static site.
# Point the scheduled task at this script.
param(
    [switch]$NoIdeas,
    [switch]$NoSite
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

python "$root\fetch.py"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $NoIdeas) {
    python "$root\ideas.py"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $NoSite) {
    Push-Location "$root\site"
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }
}
exit 0
