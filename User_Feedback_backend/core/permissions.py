# core/permissions.py
from typing import List


class Permissions:
    VIEW_DASHBOARD = "view_dashboard"
    MANAGE_USERS = "manage_users"
    RUN_BATCH_JOBS = "run_batch_jobs"
    VIEW_JOBS = "view_jobs"
    VIEW_PROFILE = "view_profile"
    MANAGE_REGISTRY = "manage_registry"

    @classmethod
    def list_all(cls) -> List[str]:
        """Returns all available system permissions."""
        return [
            cls.VIEW_DASHBOARD,
            cls.MANAGE_USERS,
            cls.RUN_BATCH_JOBS,
            cls.VIEW_JOBS,
            cls.VIEW_PROFILE,
            cls.MANAGE_REGISTRY
        ]
