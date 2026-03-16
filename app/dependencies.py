from fastapi import Header, HTTPException
from app.repositories.organisation_repository import get_org_by_api_key, get_default_org_id


def get_current_org_api(x_api_key: str = Header(...)):
    """
    Dependency for REST API endpoints.
    Resolves the tenant from the X-API-Key request header.
    """
    org = get_org_by_api_key(x_api_key)
    if not org:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return org


def get_web_org_id() -> int:
    """
    Dependency for web UI routes.
    Returns the default org ID until SSO/login is implemented.
    """
    return get_default_org_id()
