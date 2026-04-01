import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_agent_service(mocker):
    return mocker.patch("app.dependencies.AgentServiceDep")


@pytest.fixture
def mock_redis(mocker):
    return mocker.patch("app.dependencies.RedisDep")
