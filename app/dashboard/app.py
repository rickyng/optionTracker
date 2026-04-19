import os

import dash
import dash_bootstrap_components as dbc
from dash import dcc, html

from app.dashboard.tokens import BG_PRIMARY, TEXT_ACCENT, TEXT_SECONDARY

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")

# Custom HTML shell with PWA meta tags, manifest, and service worker registration.
# Dash replaces {%metas%}, {%css%}, {%config%}, {%scripts%}, {%app_entry%} placeholders.
_INDEX_STRING = """<!DOCTYPE html>
<html lang="en">
<head>
  {%metas%}
  <!-- PWA: viewport (no zoom for native feel) -->
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <!-- PWA: theme & status bar -->
  <meta name="theme-color" content="#0f0f1a">
  <meta name="mobile-web-app-capable" content="yes">
  <!-- PWA: iOS Safari -->
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="IBKR Analyzer">
  <link rel="apple-touch-icon" href="/dashboard/assets/icons/apple-touch-icon.png">
  <!-- PWA: manifest -->
  <link rel="manifest" href="/dashboard/assets/manifest.json">
  {%css%}
</head>
<body>
  {%app_entry%}
  <footer>
    {%config%}
    {%scripts%}
    {%renderer%}
  </footer>
  <!-- PWA: install prompt (Android Chrome) & iOS banner -->
  <script src="/dashboard/assets/pwa/pwa-install.js"></script>
  <!-- PWA: service worker registration -->
  <script>
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function() {
        navigator.serviceWorker.register('/dashboard/assets/pwa/sw.js', {scope: '/dashboard/'})
          .then(function(reg) { console.log('[PWA] SW registered, scope:', reg.scope); })
          .catch(function(err) { console.error('[PWA] SW registration failed:', err); });
      });
    }
  </script>
</body>
</html>
"""


def create_dash_app(fastapi_app):
    """Create and mount Dash app on the FastAPI server via WSGI middleware."""
    dash_app = dash.Dash(
        name="IBKROptionsAnalyzer",
        external_stylesheets=[dbc.themes.DARKLY],
        suppress_callback_exceptions=True,
        title="IBKR Options Analyzer",
        requests_pathname_prefix="/dashboard/",
        routes_pathname_prefix="/",
        assets_folder=_ASSETS_DIR,
        index_string=_INDEX_STRING,
    )

    dash_app.layout = html.Div(
        [
            # ── Header ─────────────────────────────────────────────────────
            html.Div(
                [
                    dbc.Container(
                        [
                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            html.Span(
                                                "IBKR",
                                                className="me-1",
                                                style={"fontWeight": 700, "color": TEXT_ACCENT},
                                            ),
                                            html.Span(
                                                "Options Analyzer",
                                                style={"fontWeight": 400, "color": "#e0e0e0"},
                                            ),
                                        ],
                                        width="auto",
                                        className="d-flex align-items-center",
                                    ),
                                    dbc.Col(
                                        [
                                            html.Div(
                                                [
                                                    html.Span(
                                                        "Account ",
                                                        className="me-1",
                                                        style={
                                                            "fontSize": "0.85rem",
                                                            "color": TEXT_SECONDARY,
                                                        },
                                                    ),
                                                    dcc.Dropdown(
                                                        id="account-selector",
                                                        options=[{"label": "All Accounts", "value": "all"}],
                                                        value="all",
                                                        clearable=False,
                                                        style={"minWidth": 180, "maxWidth": 280, "width": "100%"},
                                                    ),
                                                ],
                                                className="d-flex align-items-center",
                                            ),
                                        ],
                                        width="auto",
                                    ),
                                    dbc.Col(
                                        [
                                            html.Div(
                                                [
                                                    html.Span(
                                                        "Market ",
                                                        className="me-1",
                                                        style={
                                                            "fontSize": "0.85rem",
                                                            "color": TEXT_SECONDARY,
                                                        },
                                                    ),
                                                    dcc.Dropdown(
                                                        id="market-selector",
                                                        options=[
                                                            {"label": "All Markets", "value": "all"},
                                                            {"label": "US", "value": "US"},
                                                            {"label": "Japan", "value": "JP"},
                                                            {"label": "Hong Kong", "value": "HK"},
                                                        ],
                                                        value="all",
                                                        clearable=False,
                                                        style={"minWidth": 120, "maxWidth": 160, "width": "100%"},
                                                    ),
                                                ],
                                                className="d-flex align-items-center",
                                            ),
                                        ],
                                        width="auto",
                                    ),
                                    # User menu
                                    dbc.Col(
                                        html.Div(id="user-menu"),
                                        width="auto",
                                        className="d-flex align-items-center",
                                    ),
                                ],
                                justify="between",
                                align="center",
                                className="py-2",
                            ),
                        ],
                        fluid=True,
                    ),
                ],
                style={
                    "borderBottom": "1px solid #2a2a4a",
                    "backgroundColor": "#12121f",
                },
            ),
            # ── Tab Content ────────────────────────────────────────────────
            dbc.Container(
                [
                    dcc.Store(id="risk-cap-pct", data=30),
                    dcc.Store(id="accounts-store", data=[]),
                    dcc.Store(id="user-store", data={}),
                    dcc.Store(id="positions-store", data=[]),
                    dcc.Store(id="sync-status-store", data={}),
                    dcc.Interval(id="sync-banner-poll-interval", interval=3000, disabled=True),
                    dcc.Interval(id="boot-interval", interval=100, max_intervals=1, disabled=False),
                    # ── Global Sync Banner ────────────────────────────────────────
                    html.Div(id="sync-status-banner", style={"marginBottom": "0.5rem"}),
                    dbc.Tabs(
                        [
                            dbc.Tab(label="Overview", tab_id="overview"),
                            dbc.Tab(label="Positions", tab_id="positions"),
                            dbc.Tab(label="Risk", tab_id="risk"),
                            dbc.Tab(label="Expiration", tab_id="expiration"),
                            dbc.Tab(label="Settings", tab_id="settings"),
                        ],
                        id="main-tabs",
                        active_tab="overview",
                        className="mt-3",
                    ),
                    html.Div(id="tab-content", className="mt-3 pb-4"),
                    # ── Footer ──────────────────────────────────────────────
                    html.Div("IBKR Options Analyzer v2.0", className="dash-footer"),
                ],
                fluid=True,
            ),
        ],
        style={"backgroundColor": BG_PRIMARY, "minHeight": "100vh", "color": "#e0e0e0"},
    )

    # Register callbacks
    from app.dashboard.callbacks import register_all_callbacks

    register_all_callbacks(dash_app)

    # Mount Dash's Flask app on FastAPI via WSGIMiddleware
    from starlette.middleware.wsgi import WSGIMiddleware

    fastapi_app.mount("/dashboard", WSGIMiddleware(dash_app.server))

    return dash_app
