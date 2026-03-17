#!/bin/bash
set -e
# Install pip if missing (GDAL base image ships without it)
python3 -m ensurepip --upgrade 2>/dev/null || curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3 -q
python3 -m pip install -q -r /app/requirements-pipeline.txt
cd /app

# ── Apply DB migration for future_development table ──────────────────────────
python3 - <<'EOF'
import asyncio, os, sys
sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://homecheck:homecheck_secret@db:5432/homecheck')
from pipeline.ingest.apply_migration import run
asyncio.run(run())
EOF

# ── OSM hazard features (Austin TX) ─────────────────────────────────────────
python3 - <<'EOF'
import asyncio, os, sys
sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://homecheck:homecheck_secret@db:5432/homecheck')
from pipeline.ingest.osm_ingest import run
# Austin TX bbox: south,west,north,east
asyncio.run(run('30.098,-97.938,30.516,-97.474'))
EOF

# ── OSM hazard features (Atlanta GA) ─────────────────────────────────────────
python3 - <<'EOF'
import asyncio, os, sys
sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://homecheck:homecheck_secret@db:5432/homecheck')
from pipeline.ingest.osm_ingest import run
# Atlanta GA bbox: south,west,north,east
asyncio.run(run('33.55,-84.65,34.05,-84.15'))
EOF

# ── TWDB MUD district boundaries (Texas only) ───────────────────────────────
python3 - <<'EOF'
import asyncio, os, sys
sys.path.insert(0, '/app')
os.environ.setdefault('DATABASE_URL', 'postgresql://homecheck:homecheck_secret@db:5432/homecheck')
from pipeline.ingest.mud_ingest import run
asyncio.run(run('30.098,-97.938,30.516,-97.474'))
EOF
