import dash_bootstrap_components as dbc
from dash import dcc, html

from app.dashboard.components import fmt_money, kpi_card
from app.dashboard.tokens import (
    ACCENT_LOSS,
    ACCENT_PROFIT,
    BG_CARD,
    BORDER,
    TEXT_ACCENT,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


def overview_layout():
    return html.Div(
        [
            # ── Summary KPI Cards ──────────────────────────────────────────
            dbc.Row(id="summary-cards", className="mb-4"),
            # ── Risk Cap Control ──────────────────────────────────────────
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Div(
                                [
                                    html.Span(
                                        "Risk margin",
                                        className="me-2",
                                        style={
                                            "fontSize": "0.8rem",
                                            "fontWeight": 600,
                                            "textTransform": "uppercase",
                                            "letterSpacing": "0.05em",
                                            "color": TEXT_SECONDARY,
                                        },
                                    ),
                                    html.Span(
                                        "(%):",
                                        style={"fontSize": "0.8rem", "color": TEXT_SECONDARY},
                                    ),
                                ],
                                className="me-3 d-inline-block",
                            ),
                            html.Div(
                                [
                                    dcc.Input(
                                        id="risk-cap-slider",
                                        type="number",
                                        min=0,
                                        max=100,
                                        step=1,
                                        value=30,
                                        debounce=True,
                                        style={
                                            "width": "70px",
                                            "textAlign": "center",
                                            "backgroundColor": BG_CARD,
                                            "border": f"1px solid {BORDER}",
                                            "borderRadius": "4px",
                                            "color": TEXT_PRIMARY,
                                            "padding": "4px 8px",
                                            "fontSize": "0.9rem",
                                        },
                                    ),
                                    html.Span(
                                        "%",
                                        className="ms-1",
                                        style={"fontSize": "0.9rem", "color": TEXT_SECONDARY},
                                    ),
                                ],
                                className="d-inline-flex align-items-center",
                            ),
                        ],
                        width=12,
                        className="mb-3",
                    ),
                ],
                style={"padding": "0 0.5rem"},
            ),
            # ── Exposure Section ──────────────────────────────────────────
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(
                                "Underlying Exposure",
                                style={
                                    "fontSize": "1rem",
                                    "fontWeight": 600,
                                    "color": TEXT_PRIMARY,
                                },
                            ),
                            html.Span(
                                "  Cross-Account",
                                style={"fontSize": "0.85rem", "color": TEXT_SECONDARY},
                            ),
                            html.Button(
                                "Refresh Prices",
                                id="refresh-prices-btn",
                                n_clicks=0,
                                style={
                                    "fontSize": "0.75rem",
                                    "marginLeft": "1rem",
                                    "padding": "0.25rem 0.75rem",
                                    "backgroundColor": BG_CARD,
                                    "border": f"1px solid {BORDER}",
                                    "borderRadius": "4px",
                                    "color": TEXT_ACCENT,
                                    "cursor": "pointer",
                                },
                            ),
                            html.Span(id="refresh-prices-status", style={"fontSize": "0.75rem", "marginLeft": "0.5rem"}),
                        ],
                        className="mt-4 mb-2",
                    ),
                    html.Div(id="underlying-exposure-table"),
                ],
                className="mt-3",
            ),
        ]
    )


def make_summary_cards(data: dict) -> dbc.Row:
    """Build the three KPI summary cards."""
    specs = [
        ("Total Positions", str(data.get("total_positions", 0)), TEXT_ACCENT),
        ("Est. Profit", fmt_money(data.get("total_est_profit", 0)), ACCENT_PROFIT),
        ("Est. Loss", fmt_money(data.get("total_est_loss", 0)), ACCENT_LOSS),
    ]
    return dbc.Row([dbc.Col(kpi_card(label, val, accent), lg=4, sm=12) for label, val, accent in specs])
