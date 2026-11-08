from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.routers.dashboard import jenkins_manager

router = APIRouter(prefix="/jenkins", tags=["Jenkins Automation"])

class CreateJobRequest(BaseModel):
    job_name: str
    pipeline_script: str

@router.get("/status")
def get_jenkins_status():
    return {"status": jenkins_manager.get_status()}

@router.get("/jobs")
def list_jenkins_jobs():
    return {"jobs": jenkins_manager.list_jobs()}

@router.post("/jobs/create")
def create_or_update_job(req: CreateJobRequest):
    try:
        return jenkins_manager.create_or_update_job(req.job_name, req.pipeline_script)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/jobs/{job_name}/trigger")
def trigger_job(job_name: str):
    try:
        return jenkins_manager.trigger_build(job_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/jobs/{job_name}/builds/latest")
def get_latest_build_status(job_name: str):
    build = jenkins_manager.get_build_status(job_name)
    if build is None:
        raise HTTPException(status_code=404, detail="Job or build not found")
    return {"build": build}

@router.get("/jobs/{job_name}/builds/{build_number}/console")
def get_build_console(job_name: str, build_number: int):
    logs = jenkins_manager.get_build_console(job_name, build_number)
    return {"console": logs}
