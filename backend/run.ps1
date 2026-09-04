# Windows quick start (PowerShell). Run from the backend folder.
#   .\run.ps1            -> real data (Yahoo + Google News, simulated fallback)
#   .\run.ps1 -Demo      -> fully offline demo with scripted events
param([switch]$Demo)
if ($Demo) { $env:SINCE_PROVIDER = "simulated"; $env:SINCE_NEWS_PROVIDER = "simulated" }
python -m uvicorn app.main:app --port 8000
