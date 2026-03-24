"""URL token authentication for the dashboard."""

from __future__ import annotations

import os

import streamlit as st


DEFAULT_TOKEN = "demo"


def check_auth() -> bool:
    """Check ?token= query param against DASHBOARD_TOKEN env var.

    Returns True if authenticated, False otherwise.
    """
    expected = os.environ.get("DASHBOARD_TOKEN", DEFAULT_TOKEN)
    params = st.query_params
    provided = params.get("token", "")
    return provided == expected


def render_denied() -> None:
    """Render access denied page in Korean."""
    st.set_page_config(
        page_title="Access Denied",
        page_icon="🔒",
        layout="centered",
    )
    st.markdown(
        """
        <div style="text-align:center; padding:4rem 1rem;">
            <h1 style="font-size:3rem;">🔒</h1>
            <h2>접근이 거부되었습니다</h2>
            <p style="color:#888; font-size:1rem;">
                URL에 유효한 토큰을 포함해 주세요.<br>
                예: <code>?token=your_token</code>
            </p>
            <p style="color:#666; font-size:0.875rem; margin-top:2rem;">
                토큰은 <code>DASHBOARD_TOKEN</code> 환경변수로 설정할 수 있습니다.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
