.PHONY: dev api web test build

api:            ## run the API (uses backend/.env if present)
	cd backend && uvicorn app.main:app --reload --port 8000

web:            ## run the frontend dev server (proxies /api to :8000)
	cd frontend && npm run dev

test:           ## backend test suite
	cd backend && python -m pytest -q

build:          ## build the frontend; the API then serves it on :8000
	cd frontend && npm run build

demo:           ## fully offline demo: simulated prices + news
	cd backend && SINCE_PROVIDER=simulated SINCE_NEWS_PROVIDER=simulated uvicorn app.main:app --port 8000
