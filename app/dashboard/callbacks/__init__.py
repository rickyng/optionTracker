import contextlib
import logging
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import requests
from dash import Input, Output, State, html

from app.auth.config import auth_settings
from app.dashboard.components import fmt_money, kpi_card
from app.dashboard.layouts.expiration import expiration_layout
from app.dashboard.layouts.main import make_summary_cards, overview_layout
from app.dashboard.layouts.positions import positions_layout
from app.dashboard.layouts.risk import risk_layout
from app.dashboard.layouts.settings import settings_layout
from app.dashboard.tokens import (
    ACCENT_LOSS,
    ACCENT_PROFIT,
    ACCENT_WARN,
    BG_CARD,
    BG_ROW_ALT,
    BORDER,
    PLOT_LAYOUT,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)

_PORT = os.environ.get("PORT", "8001")
API_BASE = os.environ.get("DASH_API_BASE", f"http://127.0.0.1:{_PORT}")

_INTERNAL_HEADERS = {"X-Internal-API-Key": auth_settings.internal_api_key}
_logger = logging.getLogger(__name__)


def _safe_json_resp(resp):
    """Parse JSON response safely. Returns (dict, error_msg|None)."""
    if not resp.ok:
        try:
            detail = resp.json().get("detail", resp.text[:200])
        except Exception:
            detail = f"HTTP {resp.status_code}"
        return None, detail
    try:
        return resp.json(), None
    except Exception as e:
        return None, str(e)


def _count_badge(items):
    """Position count label for expiration buckets."""
    return html.Div(
        f"{len(items)} position{'s' if len(items) != 1 else ''}",
        style={
            "fontSize": "0.75rem",
            "textTransform": "uppercase",
            "letterSpacing": "0.06em",
            "color": TEXT_SECONDARY,
            "marginBottom": "0.5rem",
        },
    )


def _with_count(items):
    """Prepend a position count badge to an expiration bucket list."""
    return [_count_badge(items), *(items or [html.Small("None", style={"color": TEXT_SECONDARY})])]


def _get_user_headers():
    """Build headers for internal API calls, including user identity from session cookie."""
    from flask import request as flask_request

    from app.auth.session import SESSION_COOKIE_NAME, verify_session

    headers = dict(_INTERNAL_HEADERS)
    try:
        cookie = flask_request.cookies.get(SESSION_COOKIE_NAME)
        if cookie:
            user = verify_session(cookie)
            if user:
                headers["X-User-Sub"] = user.sub
    except Exception:
        pass
    return headers


def register_all_callbacks(dash_app):
    """Register all dashboard callbacks."""

    @dash_app.callback(
        Output("tab-content", "children"),
        Input("main-tabs", "active_tab"),
    )
    def render_tab(active_tab):
        layouts = {
            "overview": overview_layout,
            "positions": positions_layout,
            "risk": risk_layout,
            "expiration": expiration_layout,
            "settings": settings_layout,
        }
        layout_fn = layouts.get(active_tab, overview_layout)
        return layout_fn()

    @dash_app.callback(
        Output("account-selector", "options"),
        Output("account-selector", "value"),
        Input("main-tabs", "active_tab"),
        Input("add-account-status", "children"),
        Input("edit-account-status", "children"),
        Input("remove-account-signal", "data"),
    )
    def update_account_selector(_, __, ___, ____):
        try:
            resp = requests.get(f"{API_BASE}/api/accounts", headers=_get_user_headers(), timeout=15)
            accounts = resp.json()
            options = [{"label": "All Accounts", "value": "all"}]
            options += [{"label": a["name"], "value": str(a["id"])} for a in accounts]
            return options, dash.no_update
        except Exception:
            return [{"label": "All Accounts", "value": "all"}], dash.no_update

    # ---- Risk cap sync ----
    @dash_app.callback(
        Output("risk-cap-pct", "data"),
        Input("risk-cap-slider", "value"),
    )
    def sync_risk_cap(slider_val):
        if slider_val is None:
            return 30
        return max(0, min(100, int(slider_val)))

    # ---- Overview callbacks ----
    @dash_app.callback(
        Output("summary-cards", "children"),
        Output("underlying-exposure-table", "children"),
        Input("account-selector", "value"),
        Input("risk-cap-pct", "data"),
    )
    def update_overview(account_val, cap_pct):
        cap_pct = cap_pct or 30
        try:
            params = {}
            if account_val and account_val != "all":
                params["account_id"] = int(account_val)
            params["risk_margin_pct"] = cap_pct

            resp = requests.get(
                f"{API_BASE}/api/dashboard/summary", params=params, headers=_get_user_headers(), timeout=30
            )
            data = resp.json()
            cards = make_summary_cards(data)

            exposure = data.get("underlying_exposure", {})
            if not exposure:
                return cards, html.Small("No underlying exposure data.", className="text-muted")

            td_style = {"padding": "0.5rem 0.75rem", "fontSize": "0.85rem"}
            th_style = {
                "color": TEXT_SECONDARY,
                "fontWeight": 600,
                "fontSize": "0.75rem",
                "textTransform": "uppercase",
                "letterSpacing": "0.04em",
                "paddingBottom": "0.5rem",
                "borderBottom": f"2px solid {BORDER}",
            }

            header_bar = html.Div(
                [
                    html.Span("Underlying", style={**th_style, "display": "inline-block", "width": "20%"}),
                    html.Span("Market Price", style={**th_style, "display": "inline-block", "width": "20%"}),
                    html.Span("Est. Profit", style={**th_style, "display": "inline-block", "width": "20%"}),
                    html.Span("Est. Loss", style={**th_style, "display": "inline-block", "width": "20%"}),
                ],
                style={
                    "display": "flex",
                    "paddingBottom": "0.5rem",
                    "borderBottom": f"2px solid {BORDER}",
                    "marginBottom": "0.5rem",
                },
            )

            details_list = []
            for u in sorted(exposure.keys()):
                e = exposure[u]
                mp = e.get("market_price")
                mp_str = f"${mp:,.2f}" if mp else "-"

                summary_row = html.Summary(
                    html.Div(
                        [
                            html.Span(
                                u,
                                style={
                                    **td_style,
                                    "color": TEXT_PRIMARY,
                                    "fontWeight": 600,
                                    "display": "inline-block",
                                    "width": "20%",
                                },
                            ),
                            html.Span(
                                mp_str,
                                style={**td_style, "color": TEXT_PRIMARY, "display": "inline-block", "width": "20%"},
                            ),
                            html.Span(
                                fmt_money(e.get("est_profit", 0)),
                                style={**td_style, "color": ACCENT_PROFIT, "display": "inline-block", "width": "20%"},
                            ),
                            html.Span(
                                fmt_money(e.get("est_loss", 0)),
                                style={**td_style, "color": ACCENT_LOSS, "display": "inline-block", "width": "20%"},
                            ),
                        ],
                        style={"display": "flex", "alignItems": "center"},
                    ),
                    style={
                        "cursor": "pointer",
                        "padding": "0.6rem 0.75rem",
                        "borderBottom": f"1px solid {BORDER}",
                        "backgroundColor": BG_CARD,
                        "listStyle": "none",
                    },
                )

                positions = e.get("positions", [])
                pos_header = html.Thead(
                    html.Tr(
                        [
                            html.Th(
                                h,
                                style={
                                    "color": TEXT_SECONDARY,
                                    "fontWeight": 600,
                                    "fontSize": "0.7rem",
                                    "textTransform": "uppercase",
                                    "letterSpacing": "0.03em",
                                    "padding": "0.4rem 0.6rem",
                                    "borderBottom": f"1px solid {BORDER}",
                                },
                            )
                            for h in [
                                "Account",
                                "Expiry",
                                "Strike",
                                "Right",
                                "Qty",
                                "Risk Margin Price",
                                "Est. Profit",
                                "Est. Loss",
                            ]
                        ]
                    )
                )
                pos_rows = []
                for pos in positions:
                    pos_rmp = pos.get("risk_margin_price")
                    pos_rmp_str = f"${pos_rmp:,.2f}" if pos_rmp else "-"
                    pos_rows.append(
                        html.Tr(
                            [
                                html.Td(
                                    pos.get("account", ""),
                                    style={"color": TEXT_PRIMARY, "padding": "0.35rem 0.6rem", "fontSize": "0.8rem"},
                                ),
                                html.Td(
                                    pos.get("expiry", ""),
                                    style={"color": TEXT_SECONDARY, "padding": "0.35rem 0.6rem", "fontSize": "0.8rem"},
                                ),
                                html.Td(
                                    str(pos.get("strike", "")),
                                    style={"color": TEXT_PRIMARY, "padding": "0.35rem 0.6rem", "fontSize": "0.8rem"},
                                ),
                                html.Td(
                                    pos.get("right", ""),
                                    style={"color": TEXT_PRIMARY, "padding": "0.35rem 0.6rem", "fontSize": "0.8rem"},
                                ),
                                html.Td(
                                    str(pos.get("quantity", "")),
                                    style={"color": TEXT_PRIMARY, "padding": "0.35rem 0.6rem", "fontSize": "0.8rem"},
                                ),
                                html.Td(
                                    pos_rmp_str,
                                    style={
                                        "color": ACCENT_WARN if pos_rmp else TEXT_SECONDARY,
                                        "padding": "0.35rem 0.6rem",
                                        "fontSize": "0.8rem",
                                    },
                                ),
                                html.Td(
                                    fmt_money(pos.get("est_profit", 0)),
                                    style={"color": ACCENT_PROFIT, "padding": "0.35rem 0.6rem", "fontSize": "0.8rem"},
                                ),
                                html.Td(
                                    fmt_money(pos.get("est_loss", 0)),
                                    style={"color": ACCENT_LOSS, "padding": "0.35rem 0.6rem", "fontSize": "0.8rem"},
                                ),
                            ]
                        )
                    )
                pos_table = html.Table(
                    [pos_header, html.Tbody(pos_rows)],
                    style={
                        "width": "100%",
                        "borderCollapse": "collapse",
                        "backgroundColor": BG_ROW_ALT,
                        "marginTop": "0.25rem",
                        "marginBottom": "0.25rem",
                    },
                )

                details_list.append(
                    html.Details(
                        [summary_row, html.Div(pos_table, style={"padding": "0 0.75rem 0.5rem 0.75rem"})],
                        style={
                            "border": f"1px solid {BORDER}",
                            "borderRadius": "6px",
                            "marginBottom": "0.35rem",
                            "backgroundColor": BG_CARD,
                            "overflow": "hidden",
                        },
                    )
                )

            exposure_table = html.Div([header_bar] + details_list, style={"width": "100%", "overflowX": "auto"})
            return cards, exposure_table
        except Exception as e:
            return html.Div(f"Error loading overview: {e}"), html.Div("")

    # ---- Positions callbacks ----
    @dash_app.callback(
        Output("positions-table", "data"),
        Output("positions-table", "columns"),
        Input("account-selector", "value"),
    )
    def update_positions(account_val):
        try:
            params = {}
            if account_val and account_val != "all":
                params["account_id"] = int(account_val)
            resp = requests.get(f"{API_BASE}/api/positions", params=params, headers=_get_user_headers(), timeout=10)
            positions = resp.json()
            for p in positions:
                try:
                    exp = date.fromisoformat(p["expiry"])
                    p["days_to_expiry"] = (exp - date.today()).days
                except (ValueError, KeyError):
                    p["days_to_expiry"] = 999
            cols = [
                {"name": "Account", "id": "account_name"},
                {"name": "Underlying", "id": "underlying"},
                {"name": "Expiry", "id": "expiry"},
                {"name": "Strike", "id": "strike"},
                {"name": "Right", "id": "right"},
                {"name": "Qty", "id": "quantity"},
                {"name": "Entry", "id": "entry_premium"},
                {"name": "Mark", "id": "mark_price"},
                {"name": "DTE", "id": "days_to_expiry"},
            ]
            return positions, cols
        except Exception:
            return [], []

    # ---- Risk callbacks ----
    @dash_app.callback(
        Output("risk-summary", "children"),
        Output("loss-by-underlying-chart", "figure"),
        Output("account-risk-chart", "figure"),
        Output("riskiest-positions", "children"),
        Input("account-selector", "value"),
        State("risk-cap-pct", "data"),
    )
    def update_risk(account_val, cap_pct):
        empty_fig = go.Figure()
        empty_fig.update_layout(**PLOT_LAYOUT)
        cap_pct = cap_pct or 30
        try:
            params = {}
            if account_val and account_val != "all":
                params["account_id"] = int(account_val)

            # Single API call fetches all margin percentages at once
            pcts_to_fetch = sorted(set([0, 5, 10, 20, cap_pct]))
            params["pcts"] = ",".join(str(p) for p in pcts_to_fetch)
            resp = requests.get(
                f"{API_BASE}/api/dashboard/summary-multi", params=params, headers=_get_user_headers(), timeout=30
            )
            pct_data = resp.json()

            comparison_colors = {"0": "#b388ff", "5": "#64ffda", "10": "#448aff", "20": "#ff5252"}

            # Est. Profit is premium-based, same across all margin levels
            est_profit = pct_data.get("5", {}).get("total_est_profit", 0)

            # KPI summary cards — 5 cards, lg=2 each (10/12 cols)
            summary = dbc.Row(
                [
                    dbc.Col(
                        kpi_card("Est. Profit", fmt_money(est_profit), ACCENT_PROFIT),
                        lg=2,
                        sm=6,
                    ),
                    dbc.Col(
                        kpi_card(
                            "0% Margin",
                            fmt_money(pct_data.get("0", {}).get("total_est_loss", 0)),
                            comparison_colors["0"],
                        ),
                        lg=2,
                        sm=6,
                    ),
                    dbc.Col(
                        kpi_card(
                            "5% Margin",
                            fmt_money(pct_data.get("5", {}).get("total_est_loss", 0)),
                            comparison_colors["5"],
                        ),
                        lg=2,
                        sm=6,
                    ),
                    dbc.Col(
                        kpi_card(
                            "10% Margin",
                            fmt_money(pct_data.get("10", {}).get("total_est_loss", 0)),
                            comparison_colors["10"],
                        ),
                        lg=2,
                        sm=6,
                    ),
                    dbc.Col(
                        kpi_card(
                            "20% Margin",
                            fmt_money(pct_data.get("20", {}).get("total_est_loss", 0)),
                            comparison_colors["20"],
                        ),
                        lg=2,
                        sm=6,
                    ),
                ],
            )

            # -- Est. Loss by Underlying grouped bar chart (0%, 5%, 10%, 20%) --
            base_exp = pct_data.get("20", {}).get("underlying_exposure", {})
            underlyings = sorted(base_exp.keys())

            comparison_pcts = [0, 5, 10, 20]
            comparison_loss: dict[str, list[float]] = {}
            for pct in comparison_pcts:
                exp = pct_data.get(str(pct), {}).get("underlying_exposure", {})
                comparison_loss[str(pct)] = [exp.get(u, {}).get("est_loss", 0) for u in underlyings]

            if underlyings:
                loss_fig = go.Figure()
                for pct in comparison_pcts:
                    loss_fig.add_trace(
                        go.Bar(
                            name=f"{pct}%",
                            x=underlyings,
                            y=comparison_loss[str(pct)],
                            marker_color=comparison_colors[str(pct)],
                        )
                    )
                loss_fig.update_layout(barmode="group", **PLOT_LAYOUT)
            else:
                loss_fig = empty_fig

            # -- Per-account est. profit/loss bar chart (uses cap_pct data) --
            acct_exposure = pct_data.get(str(cap_pct), {}).get("underlying_exposure", {})

            all_positions = []
            for u, e in acct_exposure.items():
                for pos in e.get("positions", []):
                    pos["underlying"] = u
                    all_positions.append(pos)

            acct_agg: dict[str, dict] = defaultdict(lambda: {"profit": 0.0, "loss": 0.0})
            for pos in all_positions:
                acct = pos.get("account", "Unknown")
                acct_agg[acct]["profit"] += float(pos.get("est_profit", 0))
                acct_agg[acct]["loss"] += float(pos.get("est_loss", 0))

            if acct_agg:
                names = sorted(acct_agg.keys())
                acct_fig = go.Figure()
                acct_fig.add_trace(
                    go.Bar(
                        name="Est. Profit",
                        x=names,
                        y=[acct_agg[a]["profit"] for a in names],
                        marker_color=ACCENT_PROFIT,
                    )
                )
                acct_fig.add_trace(
                    go.Bar(
                        name="Est. Loss",
                        x=names,
                        y=[acct_agg[a]["loss"] for a in names],
                        marker_color=ACCENT_LOSS,
                    )
                )
                acct_fig.update_layout(barmode="group", **PLOT_LAYOUT)
            else:
                acct_fig = empty_fig

            # -- Top 10 riskiest positions (by est. loss) --
            sorted_positions = sorted(
                all_positions,
                key=lambda p: -float(p.get("est_loss", 0)),
            )[:10]
            if not sorted_positions:
                riskiest = html.Small("No positions found.", style={"color": TEXT_SECONDARY})
            else:
                items = []
                for p in sorted_positions:
                    loss = float(p.get("est_loss", 0))
                    items.append(
                        dbc.Card(
                            [
                                dbc.CardBody(
                                    [
                                        html.Strong(
                                            f"{p.get('underlying', '')} {p.get('right', '')} {p.get('strike', '')}",
                                            style={"color": TEXT_PRIMARY},
                                        ),
                                        html.Small(
                                            f" — {p.get('account', '')}",
                                            style={"color": TEXT_SECONDARY},
                                        ),
                                        html.Br(),
                                        html.Small(
                                            f"Est. Loss: {fmt_money(loss)} | Expiry: {p.get('expiry', '')}",
                                            style={"color": ACCENT_LOSS},
                                        ),
                                    ]
                                )
                            ],
                            style={
                                "backgroundColor": BG_CARD,
                                "border": f"1px solid {BORDER}",
                                "borderRadius": "8px",
                            },
                            className="mb-1",
                        )
                    )
                riskiest = items

            return summary, loss_fig, acct_fig, riskiest
        except Exception as e:
            return (
                html.Div(f"Error: {e}"),
                empty_fig,
                empty_fig,
                html.Small(f"Error: {e}", className="text-danger"),
            )

    # ---- Expiration callbacks ----
    @dash_app.callback(
        Output("expiry-lt7", "children"),
        Output("expiry-7to14", "children"),
        Output("expiry-14to21", "children"),
        Output("expiry-gt21", "children"),
        Input("account-selector", "value"),
    )
    def update_expiration(account_val):
        try:
            params = {}
            if account_val and account_val != "all":
                params["account_id"] = int(account_val)
            resp = requests.get(f"{API_BASE}/api/positions", params=params, headers=_get_user_headers(), timeout=10)
            positions = resp.json()

            lt7, w7to14, w14to21, gt21 = [], [], [], []
            for p in positions:
                try:
                    dte = (date.fromisoformat(p["expiry"]) - date.today()).days
                    item = dbc.Card(
                        [
                            dbc.CardBody(
                                [
                                    html.Strong(p["underlying"], style={"color": TEXT_PRIMARY}),
                                    html.Span(f" {p['right']} {p['strike']}", style={"color": TEXT_SECONDARY}),
                                    html.Br(),
                                    html.Small(f"{p['account_name']} | DTE: {dte}", style={"color": TEXT_SECONDARY}),
                                ]
                            ),
                        ],
                        style={
                            "backgroundColor": BG_CARD,
                            "border": f"1px solid {BORDER}",
                            "borderRadius": "8px",
                        },
                        className="mb-1",
                    )
                    if dte < 7:
                        lt7.append(item)
                    elif dte < 14:
                        w7to14.append(item)
                    elif dte < 21:
                        w14to21.append(item)
                    else:
                        gt21.append(item)
                except (ValueError, KeyError):
                    pass

            return _with_count(lt7), _with_count(w7to14), _with_count(w14to21), _with_count(gt21)
        except Exception:
            empty = [html.Small("Error")]
            return empty, empty, empty, empty

    # ---- Settings callbacks ----

    @dash_app.callback(
        Output("remove-account-signal", "data"),
        Input({"type": "remove-account-btn", "index": dash.dependencies.ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def remove_account(n_clicks):
        if not n_clicks or all(v is None or v == 0 for v in n_clicks):
            return dash.no_update
        triggered = dash.callback_context.triggered_id
        if isinstance(triggered, dict) and triggered.get("type") == "remove-account-btn":
            account_id = triggered["index"]
            with contextlib.suppress(Exception):
                requests.delete(f"{API_BASE}/api/accounts/{account_id}", headers=_get_user_headers(), timeout=10)
            return account_id
        return dash.no_update

    @dash_app.callback(
        Output("accounts-list", "children"),
        Input("account-selector", "value"),
        Input("main-tabs", "active_tab"),
        Input("add-account-status", "children"),
        Input("edit-account-status", "children"),
        Input("remove-account-signal", "data"),
    )
    def update_accounts_list(_, __, ___, ____, _____):
        try:
            resp = requests.get(f"{API_BASE}/api/accounts", headers=_get_user_headers(), timeout=15)
            accounts = resp.json()
            items = []
            for a in accounts:
                items.append(
                    dbc.Card(
                        [
                            dbc.CardBody(
                                [
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                [
                                                    html.Strong(a["name"], style={"color": TEXT_PRIMARY}),
                                                    html.Span(f" (ID: {a['id']})", style={"color": TEXT_SECONDARY}),
                                                    html.Br(),
                                                    html.Small(
                                                        f"Token: {a['token']} | Query ID: {a['query_id']}",
                                                        style={"color": TEXT_SECONDARY},
                                                    ),
                                                ],
                                                width="auto",
                                            ),
                                            dbc.Col(
                                                [
                                                    dbc.Badge(
                                                        "Enabled" if a["enabled"] else "Disabled",
                                                        color="success" if a["enabled"] else "secondary",
                                                    ),
                                                ],
                                                width="auto",
                                                className="me-3",
                                            ),
                                            dbc.Col(
                                                [
                                                    dbc.Button(
                                                        "Edit",
                                                        id={"type": "edit-account-btn", "index": a["id"]},
                                                        size="sm",
                                                        color="info",
                                                        className="me-1",
                                                    ),
                                                    dbc.Button(
                                                        "Remove",
                                                        id={"type": "remove-account-btn", "index": a["id"]},
                                                        size="sm",
                                                        color="danger",
                                                    ),
                                                ],
                                                width="auto",
                                            ),
                                        ],
                                        align="center",
                                        justify="start",
                                    ),
                                ]
                            ),
                        ],
                        style={
                            "backgroundColor": BG_CARD,
                            "border": f"1px solid {BORDER}",
                            "borderRadius": "8px",
                        },
                        className="mb-2",
                    )
                )
            return items
        except Exception as e:
            return html.Div(f"Error: {e}")

    @dash_app.callback(
        Output("edit-account-form", "style"),
        Output("edit-account-id", "data"),
        Output("edit-account-name", "value"),
        Output("edit-account-token", "value"),
        Output("edit-account-query-id", "value"),
        Output("edit-account-enabled", "value"),
        Input({"type": "edit-account-btn", "index": dash.dependencies.ALL}, "n_clicks"),
        Input("cancel-edit-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def show_edit_form(edit_clicks, cancel_clicks):
        triggered = dash.callback_context.triggered_id
        # Cancel button or no trigger → hide form
        if triggered == "cancel-edit-btn" or not triggered:
            return {"display": "none"}, dash.no_update, "", "", "", "true"
        # Edit button clicked
        if isinstance(triggered, dict) and triggered.get("type") == "edit-account-btn":
            account_id = triggered["index"]
            try:
                resp = requests.get(f"{API_BASE}/api/accounts/{account_id}", headers=_get_user_headers(), timeout=15)
                a = resp.json()
                return (
                    {"display": "block"},
                    account_id,
                    a.get("name", ""),
                    a.get("token", ""),
                    a.get("query_id", ""),
                    "true" if a.get("enabled") else "false",
                )
            except Exception:
                return {"display": "none"}, dash.no_update, "", "", "", "true"
        return {"display": "none"}, dash.no_update, "", "", "", "true"

    @dash_app.callback(
        Output("edit-account-status", "children"),
        Input("save-account-btn", "n_clicks"),
        State("edit-account-id", "data"),
        State("edit-account-name", "value"),
        State("edit-account-token", "value"),
        State("edit-account-query-id", "value"),
        State("edit-account-enabled", "value"),
        prevent_initial_call=True,
    )
    def save_account(n_clicks, account_id, name, token, query_id, enabled):
        if not n_clicks or not account_id:
            return ""
        try:
            params = {}
            if name:
                params["name"] = name
            if token:
                params["token"] = token
            if query_id:
                params["query_id"] = query_id
            if enabled:
                params["enabled"] = enabled == "true"
            resp = requests.put(
                f"{API_BASE}/api/accounts/{account_id}",
                params=params,
                headers=_get_user_headers(),
                timeout=10,
            )
            result, err = _safe_json_resp(resp)
            if err:
                return html.Small(f"Error: {err}", style={"color": ACCENT_LOSS})
            return html.Small(
                f"Updated: {result.get('name', '')} (ID: {result.get('id', '')})",
                style={"color": ACCENT_PROFIT},
            )
        except Exception as e:
            return html.Small(f"Error: {e}", style={"color": ACCENT_LOSS})

    @dash_app.callback(
        Output("add-account-status", "children"),
        Input("add-account-btn", "n_clicks"),
        State("new-account-name", "value"),
        State("new-account-token", "value"),
        State("new-account-query-id", "value"),
        prevent_initial_call=True,
    )
    def add_account(n_clicks, name, token, query_id):
        if not n_clicks or not name or not token or not query_id:
            return ""
        try:
            resp = requests.post(
                f"{API_BASE}/api/accounts",
                json={"name": name, "token": token, "query_id": query_id},
                headers=_get_user_headers(),
                timeout=10,
            )
            result, err = _safe_json_resp(resp)
            if err:
                return html.Small(f"Error: {err}", style={"color": ACCENT_LOSS})
            return html.Small(
                f"Created: {result.get('name', '')} (ID: {result.get('id', '')})", style={"color": ACCENT_PROFIT}
            )
        except Exception as e:
            return html.Small(f"Error: {e}", style={"color": ACCENT_LOSS})

    _max_poll_attempts = 30

    @dash_app.callback(
        Output("sync-job-ids", "data"),
        Output("sync-jobs-list", "children"),
        Output("sync-poll-interval", "disabled"),
        Input("sync-all-btn", "n_clicks"),
        Input("sync-poll-interval", "n_intervals"),
        State("sync-job-ids", "data"),
        prevent_initial_call=True,
    )
    def handle_sync(n_clicks, n_intervals, store_data):
        ctx = dash.callback_context
        triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        current_job_ids = (store_data or {}).get("ids", [])
        attempts = (store_data or {}).get("attempts", 0)
        _logger.info("handle_sync triggered=%s jobs=%s attempts=%s", triggered, current_job_ids, attempts)

        # Case 1: Button click — trigger downloads
        if triggered == "sync-all-btn.n_clicks":
            try:
                url = f"{API_BASE}/api/flex/download"
                _logger.info("POST %s", url)
                resp = requests.post(url, headers=_get_user_headers(), timeout=30)
                _logger.info("POST response: status=%s body=%s", resp.status_code, resp.text[:500])
                if not resp.ok:
                    return {}, [html.Small(
                        f"API error {resp.status_code}: {resp.text[:200]}",
                        style={"color": ACCENT_LOSS},
                    )], True
                result = resp.json()
                jobs = result.get("jobs", [])
                _logger.info("Started %d jobs: %s", len(jobs), [j["job_id"] for j in jobs])
                cards = []
                job_ids = []
                for j in jobs:
                    job_ids.append(j["job_id"])
                    cards.append(
                        dbc.Card(
                            [
                                dbc.CardBody(
                                    [
                                        html.Strong(j["account_name"], style={"color": TEXT_PRIMARY}),
                                        html.Span(" — Pending...", style={"color": ACCENT_WARN, "marginLeft": "0.5rem"}),
                                    ]
                                ),
                            ],
                            style={
                                "backgroundColor": BG_CARD,
                                "border": f"1px solid {BORDER}",
                                "borderRadius": "8px",
                            },
                            className="mb-1",
                        )
                    )
                return {"ids": job_ids, "attempts": 0}, cards, len(job_ids) == 0
            except Exception as e:
                _logger.exception("handle_sync button click failed")
                return {}, [html.Small(f"Error: {e}", style={"color": ACCENT_LOSS})], True

        # Case 2: Interval tick — poll for status
        if not current_job_ids:
            return dash.no_update, dash.no_update, True

        attempts += 1
        timed_out = attempts >= _max_poll_attempts

        headers = _get_user_headers()
        _logger.info("Polling %d jobs (attempt %d/%d): %s", len(current_job_ids), attempts, _max_poll_attempts, current_job_ids)

        def _fetch_job(job_id):
            try:
                resp = requests.get(
                    f"{API_BASE}/api/flex/download/{job_id}", headers=headers, timeout=10
                )
                _logger.info("Poll %s: status=%s body=%s", job_id, resp.status_code, resp.text[:200])
                return job_id, resp.json()
            except Exception as e:
                _logger.warning("Poll %s failed: %s", job_id, e)
                return job_id, {"status": "unknown", "error": f"Failed to fetch status: {e}"}

        results: dict[str, dict] = {}
        with ThreadPoolExecutor() as pool:
            futures = {pool.submit(_fetch_job, jid): jid for jid in current_job_ids}
            for future in as_completed(futures):
                jid, data = future.result()
                results[jid] = data

        cards = []
        all_done = True
        for job_id in current_job_ids:
            data = results.get(job_id, {"status": "unknown"})
            status = data.get("status", "unknown")
            if status == "completed":
                badge = dbc.Badge("Completed", color="success")
                detail = html.Small(
                    f" — {data.get('positions_imported', 0)} positions, {data.get('trades_imported', 0)} trades",
                    style={"color": TEXT_SECONDARY, "marginLeft": "0.5rem"},
                )
            elif status == "failed":
                badge = dbc.Badge("Failed", color="danger")
                detail = html.Small(
                    f" — {data.get('error', 'Unknown error')}", style={"color": ACCENT_LOSS, "marginLeft": "0.5rem"}
                )
            elif timed_out:
                badge = dbc.Badge("Timed Out", color="secondary")
                detail = html.Small(" — Max poll attempts reached", style={"color": TEXT_SECONDARY, "marginLeft": "0.5rem"})
            else:
                all_done = False
                label = {"requesting": "Requesting...", "polling": "Polling..."}.get(status, "Pending...")
                badge = dbc.Badge(label, color="warning")
                detail = ""

            cards.append(
                dbc.Card(
                    [
                        dbc.CardBody([html.Strong(job_id, style={"color": TEXT_PRIMARY}), badge, detail]),
                    ],
                    style={
                        "backgroundColor": BG_CARD,
                        "border": f"1px solid {BORDER}",
                        "borderRadius": "8px",
                    },
                    className="mb-1",
                )
            )

        # Stop polling if all done or timed out
        stop = all_done or timed_out
        new_store = {"ids": current_job_ids, "attempts": attempts}
        return new_store, cards, stop

    # ---- User Menu callback ----
    @dash_app.callback(
        Output("user-menu", "children"),
        Input("main-tabs", "active_tab"),
    )
    def update_user_menu(_):
        """Populate user info (avatar, name, logout) from /api/me."""
        try:
            resp = requests.get(f"{API_BASE}/api/me", headers=_get_user_headers(), timeout=5)
            data = resp.json()
        except Exception:
            return html.Div()

        if not data.get("authenticated"):
            return html.Div()

        name = data.get("name", "")
        picture = data.get("picture", "")
        email = data.get("email", "")

        if picture:
            avatar = html.Img(
                src=picture,
                style={
                    "width": "28px",
                    "height": "28px",
                    "borderRadius": "50%",
                    "marginRight": "0.5rem",
                },
            )
        elif name:
            avatar = html.Div(
                name[0].upper(),
                style={
                    "width": "28px",
                    "height": "28px",
                    "borderRadius": "50%",
                    "backgroundColor": ACCENT_PROFIT,
                    "color": "#0f0f1a",
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "fontWeight": 700,
                    "fontSize": "0.8rem",
                    "marginRight": "0.5rem",
                },
            )
        else:
            avatar = html.Div()

        return html.Div(
            [
                avatar,
                html.Span(
                    name or email,
                    style={"color": TEXT_PRIMARY, "fontSize": "0.85rem", "marginRight": "0.75rem"},
                ),
                html.A(
                    "Logout",
                    href="/auth/logout",
                    style={"color": TEXT_SECONDARY, "fontSize": "0.8rem", "textDecoration": "none"},
                ),
            ],
            className="d-flex align-items-center",
        )
