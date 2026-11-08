from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import tempfile
from pathlib import Path

from backend.validation.scanner import CodeValidator
from backend.routers.dashboard import ws_manager

router = APIRouter(prefix="/validation", tags=["Code Validation"])

class ValidateFileRequest(BaseModel):
    filename: str
    content: str

@router.get("/{project_id}/scan")
def scan_project(project_id: str):
    try:
        p_path = ws_manager._safe_path(project_id)
        validator = CodeValidator(p_path)
        return {"validation": validator.scan()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{project_id}/validate-file")
def validate_single_file(project_id: str, req: ValidateFileRequest):
    try:
        # Validate file content in a temp isolated directory
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / req.filename
            tmp_path.write_text(req.content, encoding="utf-8")
            validator = CodeValidator(Path(tmp_dir))
            return {"validation": validator.scan()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
