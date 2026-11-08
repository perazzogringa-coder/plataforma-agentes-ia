"""Public, read-only delivery of persisted workspace logos."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.runtime_settings import COMPANY_LOGO_DIR


router = APIRouter(tags=["company-logos"])

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@router.get("/media/logos/{filename}")
async def get_company_logo(filename: str):
    """Serve a persisted company logo without exposing the containing directory."""
    candidate = Path(filename)
    if candidate.name != filename or candidate.suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Arquivo de logo inválido")

    logo_dir = COMPANY_LOGO_DIR.resolve()
    logo_path = (logo_dir / candidate.name).resolve()
    if logo_path.parent != logo_dir:
        raise HTTPException(status_code=403, detail="Acesso negado")

    if not logo_path.is_file():
        raise HTTPException(status_code=404, detail="Logo não encontrada")

    return FileResponse(
        logo_path,
        headers={"Cache-Control": "public, max-age=604800"},
    )
