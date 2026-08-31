from typing import Any, Optional


class APIException(Exception):
    """
    Custom exception for standardizing API failures with a specific HTTP status code.
    This integrates seamlessly with the global exception handlers to return standard APIResponse envelopes.
    """

    def __init__(self, status_code: int, message: str, error: Optional[Any] = None):
        self.status_code = status_code
        self.message = message
        self.error = error
        super().__init__(message)
