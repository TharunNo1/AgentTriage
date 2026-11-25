class DomainError(Exception):
    status_code = 400
    title = "Bad Request"


class NotFoundError(DomainError):
    status_code = 404
    title = "Not Found"


class ConflictError(DomainError):
    status_code = 409
    title = "Conflict"


class UnauthorizedError(DomainError):
    status_code = 401
    title = "Unauthorized"


class ForbiddenError(DomainError):
    status_code = 403
    title = "Forbidden"


class PayloadTooLargeError(DomainError):
    status_code = 413
    title = "Payload Too Large"


class RateLimitedError(DomainError):
    status_code = 429
    title = "Too Many Requests"
