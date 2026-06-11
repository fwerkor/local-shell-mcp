"""Backward-compatible imports for OAuth helpers.

New code should import from local_shell_mcp.auth or local_shell_mcp.auth.oauth.
"""

from .auth.oauth import *  # noqa: F403
