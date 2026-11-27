import asyncio
import re
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.domain.models import IncidentSnapshot
from app.domain.ports import TicketRef

_SITE = re.compile(r"https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.atlassian\.net")
_PROJECT = re.compile(r"[A-Z][A-Z0-9]*")
_ISSUE = re.compile(r"[A-Z][A-Z0-9]*-[1-9][0-9]*")


class JiraSyncError(RuntimeError):
    pass


class _Issue(BaseModel):
    key: str


class _SearchResult(BaseModel):
    issues: list[_Issue]
    isLast: bool = True


class JiraTicketing:
    def __init__(self, client: httpx.AsyncClient, *, site: str, project: str, issue_type_id: str, email: str, token: str) -> None:
        self._site = site.rstrip("/")
        if _SITE.fullmatch(self._site) is None:
            raise ValueError("TRIAGE_JIRA_SITE must be an HTTPS atlassian.net tenant URL")
        if _PROJECT.fullmatch(project) is None or re.fullmatch(r"[1-9][0-9]*", issue_type_id) is None:
            raise ValueError("Jira requires a project key and numeric issue type ID")
        self._client = client
        self._project = project
        self._issue_type_id = issue_type_id
        self._auth = httpx.BasicAuth(email, token)

    async def sync(self, incident: IncidentSnapshot, comment: str, *, allow_create: bool = True) -> TicketRef:
        """Update a known issue, create a reserved one, or recover its key by incident label after an uncertain create."""
        label = f"agent-triage-{incident.id}"
        document = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": f"Incident {incident.id} | {incident.status.value}"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": comment[:2000] or "No analysis recorded"}]},
            ],
        }
        key = incident.ticket_id
        if key is not None:
            if incident.ticket_url != self._ticket_url(key):
                raise JiraSyncError("Stored Jira issue belongs to a different site")
        elif allow_create:
            response = await self._request(
                "POST",
                "/issue",
                {
                    "fields": {
                        "project": {"key": self._project},
                        "issuetype": {"id": self._issue_type_id},
                        "summary": f"Agent Triage incident {incident.id}",
                        "description": document,
                        "labels": [label],
                    }
                },
                expected=201,
            )
            try:
                key = _Issue.model_validate_json(response.content).key
            except ValidationError:
                raise JiraSyncError("Jira create returned an invalid response") from None
            return TicketRef(key, self._ticket_url(key), created=True)
        else:
            key = await self._recover(label)
        url = self._ticket_url(key)
        await self._request("PUT", f"/issue/{key}", {"fields": {"description": document}}, expected=204)
        return TicketRef(key, url, created=False)

    def _ticket_url(self, key: str) -> str:
        if _ISSUE.fullmatch(key) is None or not key.startswith(f"{self._project}-"):
            raise JiraSyncError("Jira returned an issue key outside the configured project")
        return f"{self._site}/browse/{key}"

    async def _recover(self, label: str) -> str:
        response = await self._request(
            "POST",
            "/search/jql",
            {"jql": f'project = "{self._project}" AND labels = "{label}"', "maxResults": 2, "fields": ["key"]},
            expected=200,
        )
        try:
            result = _SearchResult.model_validate_json(response.content)
        except ValidationError:
            raise JiraSyncError("Jira issue search returned an invalid response") from None
        # Updating an arbitrary match could overwrite a different issue when the label is ambiguous.
        if not result.isLast or len(result.issues) > 1:
            raise JiraSyncError("Multiple Jira issues match the incident label")
        if not result.issues:
            raise JiraSyncError("Reserved Jira issue is not visible yet")
        return result.issues[0].key

    async def _request(
        self, method: Literal["POST", "PUT"], path: str, payload: dict[str, object], *, expected: int
    ) -> httpx.Response:
        try:
            async with asyncio.timeout(10):
                response = await self._client.request(
                    method, f"{self._site}/rest/api/3{path}", json=payload, auth=self._auth, follow_redirects=False
                )
        except (httpx.RequestError, TimeoutError):
            raise JiraSyncError("Jira request failed") from None
        if response.status_code != expected:
            raise JiraSyncError(f"Jira request failed (HTTP {response.status_code})")
        return response
