from typing import Annotated
from fastapi import Depends
from redis.asyncio import Redis
from app.services.sre_agent_service import SREAgentService
from app.utils.redis_client import create_redis_client


def get_agent_service():
    return SREAgentService()

def get_redis():
    return create_redis_client()

AgentServiceDep = Annotated[SREAgentService, Depends(get_agent_service)]
RedisDep = Annotated[Redis, Depends(get_redis)]