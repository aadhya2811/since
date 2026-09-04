# Deploying

## Render (free tier, one service) — recommended

1. Push the repo to GitHub.
2. Render → New → **Blueprint** → pick the repo. `render.yaml` defines the service (Docker, persistent disk for SQLite).
3. Deploy. First build ~3 min. The URL serves both the app and the API.

Free-tier caveats: there is no persistent disk, so the SQLite database resets on each deploy (fine for judging; use Render's free Postgres via `SINCE_DATABASE_URL=postgresql+psycopg://…` if you want durability). Also the instance sleeps after 15 minutes idle and cold-starts in ~30s. The refresh loop resumes on wake and the first briefing may show *Stale* badges for a minute — which is the honest behaviour. Set `SINCE_PROVIDER=simulated` if you want a demo that never depends on Yahoo.

## Railway / Fly.io

Same Dockerfile (`backend/Dockerfile`, context = repo root). Mount a volume at `/data`.

## Vercel (frontend) + Render (API)

Only if you want the frontend on a CDN:

- Frontend: `cd frontend && VITE_API_BASE=https://<api-host> npm run build`, deploy `dist/` to Vercel.
- API: Render as above. CORS already allows `*.vercel.app`.

## Environment variables

See `backend/.env.example`. Nothing is required; defaults run the app with Yahoo + simulated fallback and dev-mode login codes.
