"""Authentication and OAuth support for local-shell-mcp."""

from .middleware import (
    AuthMiddleware,
    CloudflareAccessMiddleware,
    Principal,
    verify_request,
)
from .oauth import (
    authorization_server_metadata,
    issue_access_token,
    oauth_authorize_get,
    oauth_authorize_post,
    oauth_protected_resource,
    oauth_register,
    oauth_server_metadata,
    oauth_token,
    protected_resource_metadata,
    public_base_url,
    resource_url,
    validate_bearer_token,
)

__all__ = [
    "AuthMiddleware",
    "CloudflareAccessMiddleware",
    "Principal",
    "authorization_server_metadata",
    "issue_access_token",
    "oauth_authorize_get",
    "oauth_authorize_post",
    "oauth_protected_resource",
    "oauth_register",
    "oauth_server_metadata",
    "oauth_token",
    "protected_resource_metadata",
    "public_base_url",
    "resource_url",
    "validate_bearer_token",
    "verify_request",
]
