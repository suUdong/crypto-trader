"""Password-based login authentication for dashboards.

Reusable across multiple dashboards (crypto-trader, y2i, etc.).
Uses st.session_state to persist login across reruns.
Token is checked against the DASHBOARD_TOKEN env var (default: "demo").
"""

from __future__ import annotations

import os

import streamlit as st

DEFAULT_TOKEN = "demo"

# Session state key used to track authentication.
_AUTH_KEY = "dashboard_authenticated"


def check_auth(
    *,
    env_var: str = "DASHBOARD_TOKEN",
    default_token: str = DEFAULT_TOKEN,
    session_key: str = _AUTH_KEY,
) -> bool:
    """Return True if the user is authenticated via session state.

    On first visit, this always returns False so the login form is shown.
    After successful login, the session flag is set and persists across reruns.

    Args:
        env_var: Environment variable holding the expected token.
        default_token: Fallback token when env var is not set.
        session_key: Key in st.session_state to store auth flag.
    """
    return bool(st.session_state.get(session_key, False))


def render_login(
    *,
    env_var: str = "DASHBOARD_TOKEN",
    default_token: str = DEFAULT_TOKEN,
    session_key: str = _AUTH_KEY,
) -> None:
    """Render a password login form. Sets session_state on success.

    Args:
        env_var: Environment variable holding the expected token.
        default_token: Fallback token when env var is not set.
        session_key: Key in st.session_state to store auth flag.
    """
    st.markdown(
        '<div class="login-brand">'
        "<h2>크립토 트레이더</h2>"
        '<p>실시간 자동매매 모니터링 대시보드</p>'
        "</div>",
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
        password = st.text_input(
            "비밀번호",
            type="password",
            placeholder="비밀번호를 입력하세요",
        )
        submitted = st.form_submit_button("로그인", use_container_width=True)

    if submitted:
        expected = os.environ.get(env_var, default_token)
        if password == expected:
            st.session_state[session_key] = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")


# Keep render_denied as an alias for backward compatibility during transition.
render_denied = render_login
