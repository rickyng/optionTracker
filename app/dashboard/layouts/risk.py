import dash_bootstrap_components as dbc
from dash import dcc, html

from app.dashboard.components import card
from app.dashboard.tokens import TEXT_PRIMARY


def risk_layout():
    return html.Div(
        [
            html.Div(
                "Risk Analysis",
                style={
                    "fontSize": "1rem",
                    "fontWeight": 600,
                    "color": TEXT_PRIMARY,
                    "marginBottom": "1rem",
                },
            ),
            card(
                "Total Est. Loss by Risk Margin",
                html.Div(id="risk-summary"),
            ),
            card(
                "Est. Loss by Underlying",
                dcc.Graph(id="loss-by-underlying-chart"),
            ),
            dbc.Row(
                [
                    dbc.Col(
                        card(
                            "Est. Profit / Loss by Account",
                            dcc.Graph(id="account-risk-chart"),
                        ),
                        lg=6,
                        sm=12,
                    ),
                    dbc.Col(
                        card(
                            "Top 10 Riskiest Positions",
                            html.Div(id="riskiest-positions"),
                        ),
                        lg=6,
                        sm=12,
                    ),
                ],
                className="mt-3",
            ),
        ]
    )
