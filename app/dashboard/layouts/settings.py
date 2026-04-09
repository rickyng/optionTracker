import dash_bootstrap_components as dbc
from dash import dcc, html

from app.dashboard.components import card
from app.dashboard.tokens import (
    ACCENT_PROFIT,
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
            # ── Flex Sync ──────────────────────────────────────────────
            html.Div(style={"height": "1.5rem"}),
            card(
                "Flex Sync",
                [
                    dbc.Button(
                        "Sync All Accounts",
                        id="sync-all-btn",
                        style={
                            "backgroundColor": ACCENT_PROFIT,
                            "borderColor": ACCENT_PROFIT,
                            "color": "#0f0f1a",
                            "fontWeight": 600,
                        },
                        className="me-2",
                    ),
                    html.Div(id="sync-jobs-list", className="mt-3"),
                ],
            ),
        ]
    )


def _input_style() -> dict:
    return {
        "backgroundColor": BG_INPUT,
        "borderColor": BORDER,
        "color": TEXT_PRIMARY,
    }
