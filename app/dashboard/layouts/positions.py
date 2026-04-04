from dash import dash_table, dcc, html

from app.dashboard.tokens import (
    ACCENT_LOSS,
    BG_CARD,
    BG_CARD_HEADER,
    BORDER,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


def positions_layout():
    return html.Div(
        [
            dcc.Store(id="positions-data"),
            html.Div(
                "Open Positions",
                style={
                    "fontSize": "1rem",
                    "fontWeight": 600,
                    "color": TEXT_PRIMARY,
                    "marginBottom": "1rem",
                },
            ),
            dash_table.DataTable(
                id="positions-table",
                page_size=25,
                sort_action="native",
                filter_action="native",
                style_table={"overflowX": "auto"},
                style_header={
                    "backgroundColor": BG_CARD_HEADER,
                    "color": TEXT_SECONDARY,
                    "fontWeight": 600,
                    "fontSize": "0.8rem",
                    "textTransform": "uppercase",
                    "letterSpacing": "0.03em",
                    "borderBottom": f"2px solid {BORDER}",
                },
                style_cell={
                    "backgroundColor": BG_CARD,
                    "color": TEXT_PRIMARY,
                    "textAlign": "center",
                    "border": f"1px solid {BORDER}",
                    "fontFamily": "'Inter', system-ui, sans-serif",
                    "fontSize": "0.85rem",
                },
                style_data_conditional=[
                    {
                        "if": {"filter_query": "{quantity} < 0"},
                        "color": ACCENT_LOSS,
                    },
                    {
                        "if": {"filter_query": "{days_to_expiry} < 7"},
                        "backgroundColor": "#3a1a1a",
                        "color": ACCENT_LOSS,
                    },
                    {
                        "if": {"filter_query": "{days_to_expiry} < 30"},
                        "backgroundColor": "#3a3a1a",
                    },
                ],
            ),
        ]
    )
