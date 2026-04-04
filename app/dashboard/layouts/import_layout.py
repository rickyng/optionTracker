import dash_bootstrap_components as dbc
from dash import dcc, html

from app.dashboard.components import card
from app.dashboard.tokens import (
    BG_INPUT,
    BORDER,
    TEXT_ACCENT,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


def import_layout():
    return html.Div(
        [
            html.Div(
                "Import Data",
                style={
                    "fontSize": "1rem",
                    "fontWeight": 600,
                    "color": TEXT_PRIMARY,
                    "marginBottom": "1rem",
                },
            ),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            card(
                                "Upload CSV",
                                [
                                    dcc.Upload(
                                        id="csv-upload",
                                        children=html.Div(
                                            [
                                                html.Span(
                                                    "Drag & Drop or ",
                                                    style={"color": TEXT_SECONDARY},
                                                ),
                                                html.A(
                                                    "Select CSV File",
                                                    style={
                                                        "color": TEXT_ACCENT,
                                                        "textDecoration": "underline",
                                                        "cursor": "pointer",
                                                    },
                                                ),
                                            ],
                                            style={
                                                "width": "100%",
                                                "height": "100px",
                                                "lineHeight": "100px",
                                                "textAlign": "center",
                                            },
                                        ),
                                        style={
                                            "width": "100%",
                                            "borderWidth": "2px",
                                            "borderStyle": "dashed",
                                            "borderColor": BORDER,
                                            "borderRadius": "8px",
                                            "backgroundColor": BG_INPUT,
                                            "transition": "border-color 0.2s ease",
                                        },
                                    ),
                                    html.Div(
                                        "Account:",
                                        style={
                                            "fontSize": "0.8rem",
                                            "fontWeight": 600,
                                            "textTransform": "uppercase",
                                            "letterSpacing": "0.04em",
                                            "color": TEXT_SECONDARY,
                                            "marginTop": "1rem",
                                            "marginBottom": "0.5rem",
                                        },
                                    ),
                                    dcc.Dropdown(
                                        id="import-account-selector",
                                        className="mb-3",
                                    ),
                                    html.Div(id="upload-status"),
                                ],
                            ),
                        ],
                        lg=6,
                        sm=12,
                    ),
                    dbc.Col(
                        [
                            card(
                                "Recent Imports",
                                html.Div(id="recent-imports"),
                            ),
                        ],
                        lg=6,
                        sm=12,
                    ),
                ],
            ),
        ]
    )
