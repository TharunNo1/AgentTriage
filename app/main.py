import json
import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import settings
from app.dependencies import AgentServiceDep, RedisDep
from app.schemas.triage import TriageRequest, TriageResponse
from app.utils.cache import get_error_metrics
from app.utils.cloud_logging import get_sre_log_source

load_dotenv(dotenv_path="app/.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, Any]:
    print("Starting Lifespan")
    await startup()
    yield
    print("Stopping Lifespan")
    await shutdown()


async def startup() -> None:
    logging.info("Agent Triage startup")
    if settings.MOCKTRACES:
        logging.info("Agent Triage mock traces startup")
        initialize_local_logs()


def initialize_local_logs() -> None:
    """
    On startup, clears the old log file and writes 10 fresh scenarios.
    """
    source = get_sre_log_source()
    if not os.path.exists(settings.LOG_DIR):
        os.makedirs(settings.LOG_DIR, exist_ok=True)
        logger.info(f"📁 Created directory: {settings.LOG_DIR}")

    with open(settings.LOG_FILE_PATH, "w") as f:
        for scenario, data in source.items():
            f.write(f"--- SCENARIO: {scenario} | TRACE: {data['trace_id']} ---\n")
            for line in data["logs"]:
                f.write(f"{line}\n")
            f.write("\n")

    print(f"✅ Startup: {len(source)} SRE Scenarios written to {settings.LOG_FILE_PATH}")
    return


async def shutdown() -> None:
    logging.info("Agent Triage shutdown")


app = FastAPI(title="Agent Triage", version="0.0.1", lifespan=lifespan)

cors_options: dict[str, Any] = {
    "allow_origins": ["*"],  # For development
    "allow_credentials": True,
    "allow_methods": ["GET", "POST"],
}
app.add_middleware(
    CORSMiddleware,  # type: ignore[arg-type]
    **cors_options,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/triage", response_model=TriageResponse)
async def event_handler(
    request: TriageRequest,
    background_tasks: BackgroundTasks,
    agent_service: AgentServiceDep,
    redis_client: RedisDep,
):
    is_new_issue, count = await get_error_metrics(request.service_name, request.message, redis_client)

    if not is_new_issue:
        return TriageResponse(
            status_code=409,
            is_new_issue=False,
            occurrence_count=count,
            message="The same issue is already in remediation status",
        )

    background_tasks.add_task(
        agent_service.analyze_and_report,
        request.message,
        request.service_name,
        request.trace_id,
    )

    return TriageResponse(
        status_code=200,
        is_new_issue=True,
        occurrence_count=count,
        message="Triage Agent started looking into it",
    )


@app.post("/ui/triage")
async def event_handler_ui(request: TriageRequest, agent_service: AgentServiceDep, redis_client: RedisDep):
    is_new_issue, count = await get_error_metrics(request.service_name, request.message, redis_client)

    if not is_new_issue:
        logger.warning("New issue: " + str(is_new_issue) + "Count: " + str(count))

        async def short_event_generator():
            yield f"data: {json.dumps({'type': 'text', 'content': 'OLD_ISSUE_TRIAGE'})}\n\n"

        return StreamingResponse(short_event_generator(), media_type="text/event-stream")
    return await agent_service.analyze_and_report_ui(request.message, request.service_name, request.trace_id)
