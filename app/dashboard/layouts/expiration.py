import dash_bootstrap_components as dbc
from dash import html

from app.dashboard.tokens import (
    ACCENT_LOSS,
    ACCENT_PROFIT,
    ACCENT_WARN,
    BG_CARD,
    BORDER,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


def expiration_layout():
    return html.Div(
        [
            html.Div(
                "Expiration Calendar",
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
                            _section_card(
                                label="This Week",
                                sublabel="expires this week",
                                accent=ACCENT_LOSS,
                                body=html.Div(id="expiry-this-week"),
                            ),
                        ],
                        lg=3,
                        sm=6,
                    ),
                    dbc.Col(
                        [
                            _section_card(
                                label="Next Week",
                                sublabel="expires next week",
                                accent=ACCENT_WARN,
                                body=html.Div(id="expiry-next-week"),
                            ),
                        ],
                        lg=3,
                        sm=6,
                    ),
                    dbc.Col(
                        [
                            _section_card(
                                label="Next Next Week",
                                sublabel="expires in 2 weeks",
                                accent="#448aff",
                                body=html.Div(id="expiry-next-next-week"),
                            ),
                        ],
                        lg=3,
                        sm=6,
                    ),
                    dbc.Col(
                        [
                            _section_card(
                                label="Beyond",
                                sublabel="expires later",
                                accent=ACCENT_PROFIT,
                                body=html.Div(id="expiry-beyond"),
                            ),
                        ],
                        lg=3,
                        sm=6,
                    ),
                ],
            ),
        ]
    )


def _section_card(label: str, sublabel: str, accent: str, body) -> dbc.Card:
    """Expiration section card with colored top accent border."""
    return dbc.Card(
        [
            dbc.CardBody(
                [
                    html.Div(
                        [
                            html.Span(
                                label,
                                style={
                                    "fontSize": "0.85rem",
                                    "fontWeight": 600,
                                    "color": TEXT_PRIMARY,
                                },
                            ),
                            html.Span(
                                f"  {sublabel}",
                                style={
                                    "fontSize": "0.75rem",
                                    "color": TEXT_SECONDARY,
                                },
                            ),
                        ],
                        style={"marginBottom": "0.75rem"},
                    ),
                    body,
                ],
                style={"padding": "1rem"},
            ),
        ],
        style={
            "backgroundColor": BG_CARD,
            "border": f"1px solid {BORDER}",
            "borderTop": f"3px solid {accent}",
            "borderRadius": "8px",
        },
    )
