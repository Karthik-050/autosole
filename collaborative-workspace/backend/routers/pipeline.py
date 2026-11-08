from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from backend.routers.dashboard import pipeline_manager, ws_manager

router = APIRouter(prefix="/pipeline", tags=["Pipeline Orchestration"])

class TriggerPipelineRequest(BaseModel):
    project_id: str
    auto_commit: Optional[bool] = True
    commit_message: Optional[str] = "Automated pipeline commit"
    use_jenkins: Optional[bool] = False
    build_docker: Optional[bool] = True
    deploy_container: Optional[bool] = True
    target_port: Optional[int] = 5001

@router.get("/runs")
def list_runs(project_id: Optional[str] = Query(None)):
    return {"runs": pipeline_manager.get_runs(project_id=project_id)}

@router.get("/runs/{run_id}")
def get_run(run_id: str):
    run = pipeline_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return {"run": run}

@router.post("/trigger")
async def trigger_pipeline(req: TriggerPipelineRequest):
    try:
        p_path = ws_manager._safe_path(req.project_id)
        run_record = await pipeline_manager.trigger_pipeline(
            project_id=req.project_id,
            project_path=p_path,
            auto_commit=req.auto_commit if req.auto_commit is not None else True,
            commit_message=req.commit_message or "Automated pipeline commit",
            use_jenkins=req.use_jenkins or False,
            build_docker=req.build_docker if req.build_docker is not None else True,
            deploy_container=req.deploy_container if req.deploy_container is not None else True,
            target_port=req.target_port,
        )
        return {"run": run_record, "message": "Pipeline execution triggered"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
