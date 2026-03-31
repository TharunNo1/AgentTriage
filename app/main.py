import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from starlette.middleware.cors import CORSMiddleware

from app.schemas.triage import TriageRequest, TriageResponse
from app.utils.cache import get_error_metrics
from app.dependencies import RedisDep, AgentServiceDep

from dotenv import load_dotenv

load_dotenv(dotenv_path="app/.env")

logging.basicConfig(level=logging.INFO)


app = FastAPI(title="Agent Triage", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For development
    allow_credentials=True,
    allow_methods=["GET", "POST"],
)

@asynccontextmanager
async def lifespan():
    await startup()
    yield
    await shutdown()


async def startup():
    logging.info(f"Agent Triage startup")

async def shutdown():
    logging.info(f"Agent Triage shutdown")

@app.post("/health")
def health():
    return {"status": "healthy"}

@app.post("/triage", response_model=TriageResponse)
async def event_handler(request: TriageRequest, background_tasks: BackgroundTasks, agent_service : AgentServiceDep, redis_client: RedisDep):
    is_new_issue, count = await get_error_metrics(request.service_name, request.message, redis_client)

    if not is_new_issue:
        return TriageResponse(
            status_code=409,
            is_new_issue=False,
            occurrence_count=count,
            message="The same issue is already in remediation status"
        )

    background_tasks.add_task(
        agent_service.analyze_and_report,
        request.message,
        request.trace_id
    )

    return TriageResponse(
        status_code=200,
        is_new_issue=True,
        occurrence_count=count,
        message="Triage Agent started looking into it"
    )