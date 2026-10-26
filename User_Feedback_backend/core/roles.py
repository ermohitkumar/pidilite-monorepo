"""Role catalog shared by the admin API and request authorization.

Page permissions are the keys an administrator assigns. API checks still use
the older permission names, so each page also grants the endpoints behind it.
"""
from sqlalchemy.orm import Session

from db.models import Role

PAGE_RESOURCES = (
    "reports",
    "monitor",
    "all_files",
    "file_insight",
    "library",
)

# Frontend page key -> backend RoleChecker resource names.
PAGE_API_GRANTS = {
    "reports": frozenset({"view_dashboard"}),
    "monitor": frozenset({"view_dashboard", "view_jobs"}),
    "all_files": frozenset({"view_dashboard", "view_jobs"}),
    "file_insight": frozenset({"view_dashboard"}),
    "library": frozenset({"view_dashboard", "manage_registry"}),
    "dashboard": frozenset({"view_dashboard"}),
    "metrics": frozenset({"view_dashboard"}),
}

_ALL_PAGES = list(PAGE_RESOURCES)

SYSTEM_ROLES = (
    {
        "slug": "super_admin",
        "label": "Super Admin",
        "description": "Full access, including users and roles.",
        "permissions": _ALL_PAGES,
    },
    {
        "slug": "admin",
        "label": "Admin",
        "description": "Workspace access defined by this role.",
        "permissions": _ALL_PAGES,
    },
    {
        "slug": "user",
        "label": "User",
        "description": "Standard sign-in. Access follows this role.",
        "permissions": ["reports"],
    },
)


def ensure_system_roles(db: Session) -> None:
    """Insert the built-in roles once. Later edits to their permissions are kept."""
    existing = {
        row.slug
        for row in db.query(Role.slug).filter(Role.is_system.is_(True)).all()
    }
    created = False
    for spec in SYSTEM_ROLES:
        if spec["slug"] in existing:
            continue
        db.add(Role(
            slug=spec["slug"],
            label=spec["label"],
            description=spec["description"],
            permissions=list(spec["permissions"]),
            is_system=True,
        ))
        created = True
    if created:
        db.commit()


def clean_permissions(values: list) -> list[str]:
    """Deduplicate page keys and reject anything the admin panel cannot assign."""
    cleaned: list[str] = []
    unknown: list[str] = []
    for value in values:
        if not isinstance(value, str) or value not in PAGE_RESOURCES:
            unknown.append(str(value))
            continue
        if value not in cleaned:
            cleaned.append(value)
    if unknown:
        allowed = ", ".join(PAGE_RESOURCES)
        raise ValueError(
            f"Unknown permission: {', '.join(unknown)}. Choose from: {allowed}."
        )
    return cleaned


def resource_granted(allowed, resource_name: str) -> bool:
    """True when a stored grant matches an API permission directly or via a page."""
    if not allowed:
        return False
    for item in allowed:
        if isinstance(item, str):
            if item == resource_name:
                return True
            if resource_name in PAGE_API_GRANTS.get(item, ()):
                return True
        elif isinstance(item, dict) and resource_name in item.values():
            return True
    return False
