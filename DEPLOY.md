# Deploying HomeCheck

## Frontend → Vercel
1. Push repo to GitHub
2. Import project in Vercel
3. Set root directory to `frontend`
4. Add env vars: NEXT_PUBLIC_API_URL, NEXT_PUBLIC_MAPBOX_TOKEN

## Backend → Railway
1. Connect GitHub repo in Railway
2. Set root to `backend`, Dockerfile to `Dockerfile.prod`
3. Add PostgreSQL plugin (enable PostGIS: `CREATE EXTENSION postgis;`)
4. Set env vars: DATABASE_URL (auto from Railway), MAPBOX_TOKEN
5. After deploy, run the data pipeline once via Railway shell

## Data pipeline (run once after deploy)
```bash
python -m pipeline.ingest.osm_ingest
python -m pipeline.ingest.mud_ingest
```
