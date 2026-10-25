# API reference

Run the backend on `http://127.0.0.1:8000`. Vite proxies `/api` to that address during development. These endpoints are local and unauthenticated; do not expose the server to a network.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Backend status, selected Ollama model availability, and Semgrep CLI presence |
| `POST` | `/api/scans` | Create a scan job |
| `GET` | `/api/scans/{id}` | Read state, events, metrics, findings, and summary |
| `POST` | `/api/scans/{id}/findings/{finding_id}/investigate` | Analyze and propose a fix for one finding after the initial scan |

## Start a scan

```powershell
$job = Invoke-RestMethod -Method Post `
  -Uri 'http://127.0.0.1:8000/api/scans' `
  -ContentType 'application/json' `
  -Body '{"source":"demo"}'
$job.id
```

`source` may be `demo`, a public `https://github.com/owner/repo` URL, or a local directory under `BREAKSMITH_LOCAL_ROOTS`. Invalid input returns HTTP 400. The backend permits at most two active scans; further requests return HTTP 429.

## Read a scan

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/scans/$($job.id)"
```

The response includes `state`, `events`, `metrics`, `findings`, `error`, and a computed `summary`. Each finding includes scanner evidence and may later include `analysis`, `fix`, or `ai_error`. A missing scan ID returns HTTP 404.

## Investigate a finding

```powershell
Invoke-RestMethod -Method Post `
  "http://127.0.0.1:8000/api/scans/$($job.id)/findings/<finding_id>/investigate"
```

The initial job must have reached `COMPLETE`; otherwise the backend returns HTTP 409. This endpoint starts background work and returns a status immediately. Poll the scan endpoint for updated analysis, fix, and events.
