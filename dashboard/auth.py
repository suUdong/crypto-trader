"""Cookie-based token authentication for dashboards.

Flow:
1. ?token=<TOKEN> in URL  ->  set cookie (30 days), redirect to clean URL
2. Valid cookie present   ->  pass through
3. Otherwise              ->  403 Forbidden (no login form)
"""

from __future__ import annotations

import hmac
import logging

import streamlit as st

logger = logging.getLogger(__name__)

AUTH_TOKEN = "9ca3aba859b85826"
_COOKIE_NAME = "dashboard_token"
_COOKIE_MAX_AGE_DAYS = 30


def _set_cookie_and_redirect() -> None:
    """Inject JS to set the auth cookie and redirect to the clean URL."""
    max_age = _COOKIE_MAX_AGE_DAYS * 86400
    st.components.v1.html(
        f"""<script>
        document.cookie = "{_COOKIE_NAME}={AUTH_TOKEN}; path=/; max-age={max_age}; SameSite=Lax";
        window.location.href = window.location.pathname;
        </script>""",
        height=0,
    )


def require_auth() -> bool:
    """Gate the dashboard behind cookie-based token auth.

    Returns True if authenticated.  On failure, renders 403 and returns False.
    The caller should ``st.stop()`` when False is returned.
    """
    # 1) Token in query string -> set cookie and redirect
    query_token = st.query_params.get("token")
    if query_token is not None:
        if hmac.compare_digest(str(query_token), AUTH_TOKEN):
            _set_cookie_and_redirect()
            st.stop()
        # Bad token in URL -> fall through to 403

    # 2) Valid cookie -> authenticated
    cookie_token = st.context.cookies.get(_COOKIE_NAME, "")
    if cookie_token and hmac.compare_digest(cookie_token, AUTH_TOKEN):
        return True

    # 3) No valid credentials -> 403
    st.error("403 Forbidden")
    st.stop()
    return False  # unreachable, but keeps type checkers happy
