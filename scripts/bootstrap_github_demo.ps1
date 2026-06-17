# bootstrap_github_demo.ps1
#
# Inicializa el repositorio de demo `meeting-traceability-demo` con:
#  - Un commit inicial en `main` (un README).
#  - Dos ramas (`feat/PAY-001` y `feat/PAY-002`) con un commit cada una
#    que referencia un Jira issue key en el mensaje.
#  - Dos pull requests abiertos contra `main` con esas referencias.
#
# Después del bootstrap, mergea uno de los dos PRs desde la web de GitHub
# para probar el ciclo "in_code_review -> evidenced" del CommitmentRefreshService.
#
# USO (PowerShell, no requiere `gh`):
#
#   1) Edita las dos variables de abajo (OWNER y TOKEN).
#   2) Ejecuta desde la raíz del TFG:
#        .\scripts\bootstrap_github_demo.ps1
#
# El script NO toca el repo de tu TFG: crea un directorio temporal
# `_demo_repo` aparte, hace ahí git init y push, y al terminar lo deja
# enlazado al GitHub remoto.

# ===== CONFIGURA ESTAS DOS VARIABLES =====
$OWNER = "alexcontre03"      # tu usuario o organización de GitHub
$TOKEN = $env:GITHUB_TOKEN   # se lee del entorno, NO se hard-codea
# Ejecuta antes:  $env:GITHUB_TOKEN = "ghp_..."   (solo en esta terminal)

$REPO  = "meeting-traceability-demo"
$DIR   = "_demo_repo"
# =========================================

if ([string]::IsNullOrWhiteSpace($TOKEN)) {
    Write-Host "ERROR: \$env:GITHUB_TOKEN no esta seteado." -ForegroundColor Red
    Write-Host "Ejecuta primero:   `$env:GITHUB_TOKEN = 'ghp_TU_TOKEN'" -ForegroundColor Yellow
    exit 1
}
if ($OWNER -eq "<TU_USUARIO>") {
    Write-Host "ERROR: edita \$OWNER en el script con tu usuario de GitHub." -ForegroundColor Red
    exit 1
}

$ErrorActionPreference = "Stop"
$RemoteUrl = "https://$($TOKEN)@github.com/$OWNER/$REPO.git"

# Limpia ejecuciones previas
if (Test-Path $DIR) { Remove-Item -Recurse -Force $DIR }
New-Item -ItemType Directory -Path $DIR | Out-Null
Set-Location $DIR

# --- Commit inicial en main ---
git init -b main | Out-Null
"# meeting-traceability-demo`n`nRepo de prueba para la integracion GitHub del TFG." | Out-File -Encoding utf8 README.md
git add README.md
git -c user.email="demo@local" -c user.name="demo" commit -m "chore: initial commit" | Out-Null
git remote add origin $RemoteUrl
git push -u origin main

# --- Rama 1: PR que se quedara abierto ---
git checkout -b feat/PAY-001
"export function logRequest() { /* PAY-001 */ }" | Out-File -Encoding utf8 logs.js
git add logs.js
git -c user.email="demo@local" -c user.name="demo" commit -m "PAY-001: add structured logs to payments service" | Out-Null
git push -u origin feat/PAY-001

# --- Rama 2: PR que mergearas a mano desde la web ---
git checkout main
git checkout -b feat/PAY-002
"export function dashboard5xx() { /* PAY-002 */ }" | Out-File -Encoding utf8 dashboard.js
git add dashboard.js
git -c user.email="demo@local" -c user.name="demo" commit -m "PAY-002: create 5xx errors dashboard" | Out-Null
git push -u origin feat/PAY-002

# --- Abrir los dos PRs via API REST ---
function New-PullRequest($head, $title, $body) {
    $payload = @{ title = $title; body = $body; head = $head; base = "main" } | ConvertTo-Json
    Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/$OWNER/$REPO/pulls" `
        -Headers @{
            Authorization  = "Bearer $TOKEN"
            Accept         = "application/vnd.github+json"
            "User-Agent"   = "demo-script"
        } `
        -Body $payload
}

$pr1 = New-PullRequest "feat/PAY-001" "PAY-001: add structured logs" "Implements the logging task discussed in the planning meeting (PAY-001)."
$pr2 = New-PullRequest "feat/PAY-002" "PAY-002: create errors dashboard" "First pass at the 5xx dashboard (PAY-002)."

Set-Location ..
Write-Host ""
Write-Host "OK. Repo + 2 PRs creados:" -ForegroundColor Green
Write-Host "  PR #$($pr1.number)  https://github.com/$OWNER/$REPO/pull/$($pr1.number)"
Write-Host "  PR #$($pr2.number)  https://github.com/$OWNER/$REPO/pull/$($pr2.number)"
Write-Host ""
Write-Host "Para probar el ciclo completo:" -ForegroundColor Cyan
Write-Host "  1) En la app: crea un compromiso, dale 'Crear en Jira'. Cuando el Jira key sea PAY-001, dale 'Refrescar'."
Write-Host "  2) El compromiso deberia pasar a 'En revision de codigo' y mostrar el PR #$($pr1.number)."
Write-Host "  3) Mergea desde GitHub el otro PR (#$($pr2.number)). En la app, refrescar de nuevo."
Write-Host "  4) El compromiso PAY-002 deberia pasar a 'Codigo a medias' (= evidenced)."
