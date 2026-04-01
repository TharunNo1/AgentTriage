from pydantic import BaseModel


class TriageRequest(BaseModel):
    message: str
    trace_id: str
    service_name: str
    severity: str = "ERROR"


class TriageResponse(BaseModel):
    status_code: int
    is_new_issue: bool
    occurrence_count: int
    analysis: str | None = None
    message: str | None = None
