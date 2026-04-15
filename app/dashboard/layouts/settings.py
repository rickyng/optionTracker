import dash_bootstrap_components as dbc
from dash import dcc, html

from app.dashboard.components import card
from app.dashboard.tokens import (
    ACCENT_PROFIT,
    ACCENT_WARN,
    BG_INPUT,
    BORDER,
    TEXT_ACCENT,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


def settings_layout():
    return html.Div(
        [
            html.Div(
                "Account Settings",
                style={
                    "fontSize": "1rem",
                    "fontWeight": 600,
                    "color": TEXT_PRIMARY,
                    "marginBottom": "1rem",
                },
            ),
            html.Div(id="accounts-list"),
            dcc.Store(id="remove-account-signal"),
            # ── Edit Account Form (hidden by default) ───────────────────
            html.Div(
                id="edit-account-form",
                className="d-none",
                style={"display": "none"},
                children=[
                    card(
                        "Edit Account",
                        [
                            dcc.Store(id="edit-account-id"),
                            dbc.Row(
                                [
                                    dbc.Col(
                                        [
                                            html.Small("Name", style={"color": TEXT_SECONDARY}),
                                            dbc.Input(
                                                id="edit-account-name",
                                                placeholder="Account Name",
                                                style=_input_style(),
                                                className="mt-1",
                                            ),
                                        ],
                                        lg=3,
                                        md=6,
                                        sm=12,
                                    ),
                                    dbc.Col(
                                        [
                                            html.Small("Flex Token", style={"color": TEXT_SECONDARY}),
                                            dbc.Input(
                                                id="edit-account-token",
                                                placeholder="Flex Token",
                                                style=_input_style(),
                                                className="mt-1",
                                            ),
                                        ],
                                        lg=3,
                                        md=6,
                                        sm=12,
                                    ),
                                    dbc.Col(
                                        [
                                            html.Small("Query ID", style={"color": TEXT_SECONDARY}),
                                            dbc.Input(
                                                id="edit-account-query-id",
                                                placeholder="Query ID",
                                                style=_input_style(),
                                                className="mt-1",
                                            ),
                                        ],
                                        lg=3,
                                        md=6,
                                        sm=12,
                                    ),
                                    dbc.Col(
                                        [
                                            html.Small("Enabled", style={"color": TEXT_SECONDARY}),
                                            dbc.Select(
                                                id="edit-account-enabled",
                                                options=[
                                                    {"label": "Enabled", "value": "true"},
                                                    {"label": "Disabled", "value": "false"},
                                                ],
                                                value="true",
                                                style=_input_style(),
                                                className="mt-1",
                                            ),
                                        ],
                                        lg=2,
                                        md=6,
                                        sm=12,
                                    ),
                                    dbc.Col(
                                        [
                                            html.Small("\u00a0", style={"color": TEXT_SECONDARY}),
                                            dbc.Button(
                                                "Save",
                                                id="save-account-btn",
                                                size="sm",
                                                style={
                                                    "backgroundColor": ACCENT_PROFIT,
                                                    "borderColor": ACCENT_PROFIT,
                                                    "color": "#0f0f1a",
                                                    "fontWeight": 600,
                                                },
                                                className="mt-1",
                                            ),
                                            dbc.Button(
                                                "Cancel",
                                                id="cancel-edit-btn",
                                                size="sm",
                                                color="secondary",
                                                className="ms-2 mt-1",
                                            ),
                                        ],
                                        lg=1,
                                        md=12,
                                        sm=12,
                                    ),
                                ],
                                className="mt-1",
                            ),
                            html.Div(id="edit-account-status", className="mt-2"),
                        ],
                    )
                ],
            ),
            html.Div(style={"height": "1rem"}),
            # ── Add New Account ────────────────────────────────────────
            card(
                "Add New Account",
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Input(
                                    id="new-account-name",
                                    placeholder="Account Name",
                                    style=_input_style(),
                                ),
                                lg=3,
                                md=6,
                                sm=12,
                            ),
                            dbc.Col(
                                dbc.Input(
                                    id="new-account-token",
                                    placeholder="Flex Token",
                                    style=_input_style(),
                                ),
                                lg=3,
                                md=6,
                                sm=12,
                            ),
                            dbc.Col(
                                dbc.Input(
                                    id="new-account-query-id",
                                    placeholder="Query ID",
                                    style=_input_style(),
                                ),
                                lg=3,
                                md=6,
                                sm=12,
                            ),
                            dbc.Col(
                                dbc.Button(
                                    "Add",
                                    id="add-account-btn",
                                    style={
                                        "backgroundColor": TEXT_ACCENT,
                                        "borderColor": TEXT_ACCENT,
                                        "color": "#0f0f1a",
                                        "fontWeight": 600,
                                    },
                                ),
                                lg=1,
                                md=12,
                                sm=12,
                            ),
                        ],
                    ),
                    html.Div(id="add-account-status", className="mt-2"),
                ],
            ),
            # ── Sync All Data ────────────────────────────────────────────
            html.Div(style={"height": "1.5rem"}),
            card(
                "Sync All Data",
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Button(
                                        "Force Sync",
                                        id="sync-force-btn",
                                        size="sm",
                                        style={
                                            "backgroundColor": ACCENT_PROFIT,
                                            "borderColor": ACCENT_PROFIT,
                                            "color": "#0f0f1a",
                                            "fontWeight": 600,
                                        },
                                    ),
                                    dbc.Button(
                                        "Smart Sync",
                                        id="sync-smart-btn",
                                        size="sm",
                                        style={
                                            "backgroundColor": TEXT_ACCENT,
                                            "borderColor": TEXT_ACCENT,
                                            "color": "#0f0f1a",
                                            "fontWeight": 600,
                                            "marginLeft": "0.5rem",
                                        },
                                    ),
                                    html.Span(
                                        id="sync-last-time",
                                        style={
                                            "fontSize": "0.75rem",
                                            "color": TEXT_SECONDARY,
                                            "marginLeft": "0.75rem",
                                        },
                                    ),
                                ],
                                width="auto",
                            ),
                        ],
                    ),
                    html.Div(id="sync-progress-list", className="mt-3"),
                    dcc.Interval(id="settings-stale-check", interval=100, max_intervals=1, disabled=False),
                ],
            ),
            # ── Screener Watchlist ────────────────────────────────────────
            html.Div(style={"height": "1.5rem"}),
            card(
                "Screener Watchlist",
                [
                    html.Div(id="settings-watchlist-tags", className="mb-2"),
                    html.Div(
                        [
                            dcc.Input(
                                id="settings-add-symbol-input",
                                type="text",
                                placeholder="e.g. AAPL",
                                maxLength=10,
                                style=_input_style(),
                            ),
                            html.Button(
                                "Add",
                                id="settings-add-symbol-btn",
                                n_clicks=0,
                                style={
                                    "backgroundColor": TEXT_ACCENT,
                                    "color": "#0f0f1a",
                                    "border": "none",
                                    "borderRadius": "4px",
                                    "padding": "0.3rem 0.8rem",
                                    "fontWeight": 600,
                                    "fontSize": "0.8rem",
                                    "cursor": "pointer",
                                    "marginLeft": "0.5rem",
                                },
                            ),
                            html.Span(
                                id="settings-add-symbol-status",
                                style={"fontSize": "0.75rem", "color": ACCENT_WARN, "marginLeft": "0.5rem"},
                            ),
                        ],
                        className="d-flex align-items-center",
                    ),
                ],
            ),
            # ── Account Sync Status ────────────────────────────────────────
            html.Div(style={"height": "1.5rem"}),
            card(
                "Account Sync Status",
                [html.Div(id="account-sync-status")],
            ),
            # ── Stock Prices (yfinance) Status ──────────────────────────────
            html.Div(style={"height": "1.5rem"}),
            card(
                "Stock Prices Status",
                [html.Div(id="price-sync-status")],
            ),
        ]
    )


def _input_style() -> dict:
    return {
        "backgroundColor": BG_INPUT,
        "borderColor": BORDER,
        "color": TEXT_PRIMARY,
    }
