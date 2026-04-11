"""Suggestions tab layout — CSP Screener UI."""

from dash import dash_table, dcc, html

from app.dashboard.tokens import (
    ACCENT_INFO,
    ACCENT_PROFIT,
    ACCENT_WARN,
    BG_CARD,
    BG_CARD_HEADER,
    BORDER,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


def screener_layout():
    return html.Div(
        [
            dcc.Loading(id="scan-loading", type="default", children=html.Div(id="scan-loading-inner")),
            # Header
            html.Div(
                [
                    html.Span(
                        "CSP Screener",
                        style={
                            "fontSize": "1.1rem",
                            "fontWeight": 600,
                            "color": TEXT_PRIMARY,
                        },
                    ),
                    html.Button(
                        "Scan",
                        id="scan-btn",
                        n_clicks=0,
                        style={
                            "backgroundColor": ACCENT_INFO,
                            "color": "#0f0f1a",
                            "border": "none",
                            "borderRadius": "6px",
                            "padding": "0.4rem 1.2rem",
                            "fontWeight": 600,
                            "fontSize": "0.85rem",
                            "cursor": "pointer",
                            "marginLeft": "1rem",
                        },
                    ),
                    html.Span(
                        id="scan-status",
                        style={
                            "fontSize": "0.8rem",
                            "color": TEXT_SECONDARY,
                            "marginLeft": "0.75rem",
                        },
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "marginBottom": "1rem"},
            ),
            # Summary KPI cards
            html.Div(id="screener-summary-cards", className="mb-3"),
            # Watchlist (collapsible)
            html.Details(
                [
                    html.Summary(
                        "Watchlist",
                        style={
                            "cursor": "pointer",
                            "color": TEXT_SECONDARY,
                            "fontWeight": 600,
                            "fontSize": "0.85rem",
                            "marginBottom": "0.5rem",
                        },
                    ),
                    html.Div(
                        [
                            html.Div(id="watchlist-tags", className="mb-2"),
                            html.Div(
                                [
                                    dcc.Input(
                                        id="add-symbol-input",
                                        type="text",
                                        placeholder="e.g. AAPL",
                                        maxLength=10,
                                        style={
                                            "backgroundColor": BG_CARD_HEADER,
                                            "border": f"1px solid {BORDER}",
                                            "borderRadius": "4px",
                                            "color": TEXT_PRIMARY,
                                            "padding": "0.3rem 0.6rem",
                                            "fontSize": "0.85rem",
                                            "width": "120px",
                                        },
                                    ),
                                    html.Button(
                                        "Add",
                                        id="add-symbol-btn",
                                        n_clicks=0,
                                        style={
                                            "backgroundColor": ACCENT_PROFIT,
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
                                        id="add-symbol-status",
                                        style={"fontSize": "0.75rem", "color": ACCENT_WARN, "marginLeft": "0.5rem"},
                                    ),
                                ],
                                className="d-flex align-items-center",
                            ),
                        ],
                        style={"padding": "0.5rem 0"},
                    ),
                ],
                style={"marginBottom": "1rem"},
                open=True,
            ),
            # Criteria (collapsible)
            html.Details(
                [
                    html.Summary(
                        "Criteria",
                        style={
                            "cursor": "pointer",
                            "color": TEXT_SECONDARY,
                            "fontWeight": 600,
                            "fontSize": "0.85rem",
                            "marginBottom": "0.5rem",
                        },
                    ),
                    html.Div(
                        [
                            _filter_row(
                                "Min IV %",
                                dcc.Input(
                                    id="filter-min-iv", type="number", value=30, min=0, max=100, style=_input_style()
                                ),
                                tooltip="Minimum implied volatility. Higher IV = higher premium income. CSP sellers typically target 30-60% IV.",
                            ),
                            _filter_row(
                                "Delta Range",
                                html.Div(
                                    [
                                        dcc.Input(
                                            id="filter-min-delta",
                                            type="number",
                                            value=0.15,
                                            step=0.01,
                                            min=0,
                                            max=1,
                                            style={**_input_style(), "width": "70px"},
                                        ),
                                        html.Span(" \u2013 ", style={"color": TEXT_SECONDARY, "margin": "0 0.3rem"}),
                                        dcc.Input(
                                            id="filter-max-delta",
                                            type="number",
                                            value=0.35,
                                            step=0.01,
                                            min=0,
                                            max=1,
                                            style={**_input_style(), "width": "70px"},
                                        ),
                                    ]
                                ),
                                tooltip="Put delta (absolute). Lower delta = more OTM = lower assignment risk. 0.15-0.35 is typical for CSP.",
                            ),
                            _filter_row(
                                "DTE Range",
                                html.Div(
                                    [
                                        dcc.Input(
                                            id="filter-min-dte",
                                            type="number",
                                            value=7,
                                            min=0,
                                            max=365,
                                            style={**_input_style(), "width": "70px"},
                                        ),
                                        html.Span(" \u2013 ", style={"color": TEXT_SECONDARY, "margin": "0 0.3rem"}),
                                        dcc.Input(
                                            id="filter-max-dte",
                                            type="number",
                                            value=45,
                                            min=0,
                                            max=365,
                                            style={**_input_style(), "width": "70px"},
                                        ),
                                    ]
                                ),
                                tooltip="Days to expiration. Longer DTE = more premium but more exposure. 21-45 days is common for CSP.",
                            ),
                            _filter_row(
                                "Min OTM %",
                                dcc.Input(
                                    id="filter-min-otm", type="number", value=5, min=0, max=50, style=_input_style()
                                ),
                                tooltip="Minimum distance below current price. More OTM = safer but lower premium. 5-10% is typical.",
                            ),
                            _filter_row(
                                "Min Ann.ROC %",
                                dcc.Input(
                                    id="filter-min-roc", type="number", value=12, min=0, max=100, style=_input_style()
                                ),
                                tooltip="Minimum annualized return on capital. Target 12%+ to outperform buy-and-hold.",
                            ),
                            _filter_row(
                                "Max Capital $",
                                dcc.Input(
                                    id="filter-max-capital",
                                    type="number",
                                    value=50000,
                                    min=0,
                                    step=1000,
                                    style=_input_style(),
                                ),
                                tooltip="Maximum cash required per position (strike x 100). Limits position size for account sizing.",
                            ),
                        ],
                        style={"padding": "0.5rem 0"},
                    ),
                ],
                style={"marginBottom": "1rem"},
                open=True,
            ),
            # Table filters
            html.Div(
                [
                    html.Span("Filter:", style={"color": TEXT_SECONDARY, "fontSize": "0.8rem", "marginRight": "0.5rem"}),
                    dcc.Dropdown(
                        id="filter-ticker",
                        placeholder="Ticker",
                        clearable=True,
                        style={"width": "130px", "fontSize": "0.82rem"},
                    ),
                    dcc.Dropdown(
                        id="filter-rating",
                        options=[
                            {"label": "Any", "value": 0},
                            {"label": "FAIR+", "value": 2},
                            {"label": "OK+", "value": 3},
                            {"label": "GOOD+", "value": 4},
                            {"label": "STRONG", "value": 5},
                        ],
                        value=0,
                        clearable=False,
                        style={"width": "110px", "fontSize": "0.82rem", "marginLeft": "0.5rem"},
                    ),
                ],
                className="d-flex align-items-center mb-2",
            ),
            # Results table
            dash_table.DataTable(
                id="screener-table",
                page_size=25,
                sort_action="native",
                sort_by=[{"column_id": "ann_roc_pct", "direction": "desc"}],
                style_table={"overflowX": "auto"},
                style_header={
                    "backgroundColor": BG_CARD_HEADER,
                    "color": TEXT_SECONDARY,
                    "fontWeight": 600,
                    "fontSize": "0.75rem",
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
                    "fontSize": "0.82rem",
                    "padding": "0.4rem 0.6rem",
                    "cursor": "pointer",
                },
                style_data_conditional=[
                    {"if": {"filter_query": "{rating} = 5"}, "borderLeft": f"3px solid {ACCENT_PROFIT}"},
                    {"if": {"filter_query": "{rating} = 4"}, "borderLeft": f"3px solid {ACCENT_INFO}"},
                    {"if": {"filter_query": "{rating} <= 3"}, "borderLeft": f"3px solid {ACCENT_WARN}"},
                ],
            ),
            # Detail panel
            html.Div(id="screener-detail-panel", style={"display": "none"}),
        ]
    )


def _input_style():
    return {
        "backgroundColor": BG_CARD_HEADER,
        "border": f"1px solid {BORDER}",
        "borderRadius": "4px",
        "color": TEXT_PRIMARY,
        "padding": "0.3rem 0.6rem",
        "fontSize": "0.82rem",
        "width": "90px",
    }


def _filter_row(label: str, control, tooltip: str | None = None) -> html.Div:
    label_style = {
        "color": TEXT_SECONDARY,
        "fontSize": "0.8rem",
        "width": "120px",
        "minWidth": "120px",
    }
    if tooltip:
        label_style["cursor"] = "help"
        label_style["textDecoration"] = "underline dotted"
        label_style["textDecorationColor"] = "rgba(136,146,176,0.4)"

    return html.Div(
        [
            html.Span(label, style=label_style, title=tooltip or ""),
            control,
        ],
        className="d-flex align-items-center mb-1",
    )
