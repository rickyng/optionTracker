import dash_bootstrap_components as dbc
from dash import html

from app.dashboard.tokens import (
    BG_CARD,
    BG_CARD_HEADER,
    BORDER,
    TEXT_SECONDARY,
)


def card(header: str, body) -> dbc.Card:
    """Consistent card component with styled header."""
    if not isinstance(body, list):
        body = [body]
    return dbc.Card(
        [
            dbc.CardHeader(
                header,
                style={
                    "backgroundColor": BG_CARD_HEADER,
                    "borderBottom": f"1px solid {BORDER}",
                    "fontWeight": 600,
                    "fontSize": "0.8rem",
                    "textTransform": "uppercase",
                    "letterSpacing": "0.04em",
                    "color": TEXT_SECONDARY,
                },
            ),
            dbc.CardBody(body, style={"padding": "0.75rem"}),
        ],
        style={
            "backgroundColor": BG_CARD,
            "border": f"1px solid {BORDER}",
            "borderRadius": "8px",
        },
    )


def kpi_card(label: str, value: str, accent_color: str, value_size: str = "1.6rem") -> dbc.Card:
    """Single KPI metric card with accent top-border."""
    return dbc.Card(
        dbc.CardBody(
            [
                html.Div(value, style={"fontSize": value_size, "fontWeight": 700, "color": accent_color}),
                html.Div(
                    label,
                    style={
                        "fontSize": "0.7rem",
                        "textTransform": "uppercase",
                        "letterSpacing": "0.06em",
                        "color": TEXT_SECONDARY,
                        "marginTop": "0.25rem",
                    },
                ),
            ],
            style={"padding": "1rem 1.25rem", "textAlign": "center"},
        ),
        style={
            "backgroundColor": BG_CARD,
            "border": f"1px solid {BORDER}",
            "borderTop": f"3px solid {accent_color}",
            "borderRadius": "8px",
        },
    )


def fmt_money(val) -> str:
    """Format a monetary value that may be 'unlimited' from the API."""
    if isinstance(val, str):
        return val.upper()
    try:
        return f"${float(val):,.2f}"
    except (ValueError, TypeError):
        return str(val)
