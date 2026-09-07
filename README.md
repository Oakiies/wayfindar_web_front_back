# wayfindar web front/back

## Structure
- `frontend-v3/` : current React + Vite UI
- `frontend-v2/`, `frontend/` : earlier frontend versions kept for reference
- `backend/` : FastAPI backend, localization, routing and AR services
- `backend/poc_ar_arrow/`, `backend/poc_cross_camera/` : reproducible PoC source and reports
- `_archive/` : local legacy copies; intentionally excluded from Git

## Run frontend
```powershell
cd frontend-v3
npm install
npm run dev
```

## Run backend
```powershell
cd backend
.\run_backend.ps1
```

Large local assets are intentionally not versioned. This includes walkthrough
videos, generated per-floor `map_data`, runtime uploads, model weights, virtual
environments and build/dependency caches. Keep those assets locally or restore
them from the project data source before running the full localization stack.
