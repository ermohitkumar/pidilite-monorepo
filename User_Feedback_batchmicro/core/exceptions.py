"""
STT Exception Hierarchy
───────────────────────
Granular exception classes for every documented Cloud Speech-to-Text error.
Each exception carries a `retryable` flag so callers can decide whether to
retry (increment retry_count → ERROR) or give up immediately (→ FAILED).

Reference: https://cloud.google.com/speech-to-text/docs/error-messages
"""


class STTError(Exception):
    """Base class for all Speech-to-Text errors."""

    def __init__(self, message: str, *, retryable: bool = False):
        self.message = message
        self.retryable = retryable
        super().__init__(message)


# ── Non-retryable (mark FAILED immediately) ──────────────────────────────────

class STTCredentialsError(STTError):
    """Application Default Credentials not found or invalid key file."""

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class STTPermissionDeniedError(STTError):
    """403 — API not enabled in project, or wrong service account."""

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class STTInvalidArgumentError(STTError):
    """400 — Generic invalid argument (encoding, sample rate, language code)."""

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class STTBadEncodingError(STTError):
    """
    Invalid recognition config: bad encoding.
    Audio data encoded with a different codec than declared in RecognitionConfig.
    """

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class STTMultiChannelError(STTError):
    """
    Must use single channel (mono) audio.
    WAV header indicates multi-channel — needs re-encoding or
    multi-channel config flag.
    """

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class STTAudioTooLongError(STTError):
    """
    OUT_OF_RANGE — audio exceeds maximum supported duration.
    For LongRunningRecognize the limit is ~480 minutes.
    """

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class STTPayloadTooLargeError(STTError):
    """
    Request payload size exceeds the 10 MB inline limit.
    Should use GCS URI instead.
    """

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


class STTEmptyResponseError(STTError):
    """
    LRO completed successfully but returned zero transcript results.
    Audio may be silent, inaudible, or in an unsupported language.
    """

    def __init__(self, message: str):
        super().__init__(message, retryable=False)


# ── Retryable (increment retry_count, mark ERROR for checker) ────────────────

class STTQuotaExhaustedError(STTError):
    """
    RESOURCE_EXHAUSTED — per-minute or daily quota exceeded.
    Retryable: wait for quota reset, then resubmit.
    """

    def __init__(self, message: str):
        super().__init__(message, retryable=True)


class STTUnavailableError(STTError):
    """
    UNAVAILABLE / DEADLINE_EXCEEDED — transient infrastructure error.
    Retryable: the service is temporarily down, try again with backoff.
    """

    def __init__(self, message: str):
        super().__init__(message, retryable=True)


class STTGeminiTransientError(STTError):
    """
    Transient Gemini Flash STT failure (429, 5xx, timeout, empty, MAX_TOKENS).
    Cloud Tasks retries up to 3 times, then the worker falls back to Speech v2.
    """

    def __init__(self, message: str):
        super().__init__(message, retryable=True)