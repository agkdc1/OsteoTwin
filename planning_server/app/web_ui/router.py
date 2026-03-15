"""Web UI routes — serves HTMX + Alpine.js pages and proxies STL files."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["web-ui"])

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
TEMPLATES_DIR.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/viewer", response_class=HTMLResponse)
async def viewer(request: Request):
    return templates.TemplateResponse("viewer.html", {"request": request})


@router.get("/debate", response_class=HTMLResponse)
async def debate_page(request: Request):
    return templates.TemplateResponse("debate.html", {"request": request})


@router.get("/stl-proxy/{filepath:path}")
async def stl_proxy(filepath: str):
    """Serve STL files from the simulation server's mesh cache.

    This allows the Three.js viewer to load STL files without CORS issues.
    """
    # Only allow serving from the mesh_cache directory
    mesh_cache = Path("C:/Users/ahnch/Documents/OsteoTwin/simulation_server/mesh_cache")
    target = (mesh_cache / filepath).resolve()

    # Security: ensure path is within mesh_cache
    if not str(target).startswith(str(mesh_cache.resolve())):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Access denied")

    if not target.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(target),
        media_type="application/sla",
        headers={"Access-Control-Allow-Origin": "*"},
    )
