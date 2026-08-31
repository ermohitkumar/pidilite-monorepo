"""
Enums matching the ER diagram and flow diagram.
All enums inherit from (str, enum.Enum) so they serialise cleanly in JSON.
"""
import enum


class JobStatus(str, enum.Enum):
    """Lifecycle of a single audio-file job."""
    PENDING          = "PENDING"           # registered, awaiting batch
    BATCHED          = "BATCHED"           # added to a batch, awaiting STT
    STT_SUBMITTED    = "STT_SUBMITTED"     # async STT operation started
    STT_COMPLETED    = "STT_COMPLETED"     # STT output JSON written to GCS
    TRANSLATING      = "TRANSLATING"       # translation Cloud Task in progress
    TRANSLATED       = "TRANSLATED"        # translation done, post-process enqueued
    PROCESSING       = "PROCESSING"        # post-processing started (normalizing)
    NORMALIZED       = "NORMALIZED"        # product names corrected, insights pending
    INSIGHTS         = "INSIGHTS"          # Gemini insights generation in progress
    COMPLETED        = "COMPLETED"         # all steps done
    FAILED           = "FAILED"            # exceeded max retries
    ERROR            = "ERROR"             # transient error, will retry


class BatchStatus(str, enum.Enum):
    PENDING         = "PENDING"
    PROCESSING      = "PROCESSING"
    COMPLETED       = "COMPLETED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"     # some jobs failed
    FAILED          = "FAILED"