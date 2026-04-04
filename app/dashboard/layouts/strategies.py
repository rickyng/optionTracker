from dash import html

from app.dashboard.tokens import TEXT_PRIMARY


def strategies_layout():
    return html.Div(
        [
            html.Div(
                "Detected Strategies",
                style={
                    "fontSize": "1rem",
                    "fontWeight": 600,
                    "color": TEXT_PRIMARY,
                    "marginBottom": "1rem",
                },
            ),
            html.Div(id="strategy-cards-container"),
        ]
    )
