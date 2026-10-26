class RecoveryServiceError(Exception):
    """Base error for recovery decision operations."""


class RecoveryNotFoundError(RecoveryServiceError):
    """Requested operational entity was not found."""


class IdempotencyConflictError(RecoveryServiceError):
    """An idempotency key was reused with incompatible inputs."""


class InvalidDecisionInputError(RecoveryServiceError):
    """Decision input is invalid or lacks a timezone-aware evaluation time."""