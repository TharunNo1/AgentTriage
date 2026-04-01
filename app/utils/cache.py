import hashlib

from app.dependencies import RedisDep


async def get_error_metrics(service_name: str, message: str, redis_client: RedisDep) -> tuple[bool, int]:
    fingerprint = hashlib.md5(f"{service_name}{message}".encode()).hexdigest()
    key = f"sre:error:{fingerprint}"

    is_new = await redis_client.set(key, 1, ex=300, nx=True)

    if is_new:
        return (
            True,
            1,
        )

    count = await redis_client.incr(key)
    return False, count
