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
from app.dashboard.layouts.screener import screener_layout
from app.dashboard.layouts.settings import settings_layout
from app.dashboard.tokens import (
    ACCENT_INFO,
    ACCENT_LOSS,
    ACCENT_PROFIT,
    ACCENT_WARN,
    BG_CARD,
    BG_CARD_HEADER,
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
            else:
                _logger.warning("Session cookie found but verification failed")
        else:
            _logger.debug("No session cookie '%s' in Flask request", SESSION_COOKIE_NAME)
    except Exception as e:
        _logger.warning("Failed to extract user from session: %s", e)
    return headers


def _api_get(path, params=None, timeout=5):
    """GET from internal API. Returns parsed JSON or None on error."""
    try:
        resp = requests.get(f"{API_BASE}{path}", params=params, headers=_get_user_headers(), timeout=timeout)
        return resp.json()
    except Exception as e:
        _logger.warning("API GET %s failed: %s", path, e)
        return None


def _filter_params(account_val, market_val):
    """Build query params dict from account and market dropdown values."""
    params = {}
    if account_val != "all":
        params["account_id"] = int(account_val)
    if market_val != "all":
        params["market"] = market_val
    return params


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
            "suggestions": screener_layout,
            "settings": settings_layout,
        }
        layout_fn = layouts.get(active_tab, overview_layout)
        return layout_fn()

    # ---- Data loaders: populate stores on load + on account changes ----
    @dash_app.callback(
        Output("accounts-store", "data"),
        Input("boot-interval", "n_intervals"),
        Input("main-tabs", "active_tab"),
        Input("add-account-status", "children"),
        Input("edit-account-status", "children"),
        Input("remove-account-signal", "data"),
    )
    def load_accounts(_, __, ___, ____, _____):
        """Fetch accounts list into store. Used by account selector and settings."""
        return _api_get("/api/accounts") or []

    @dash_app.callback(
        Output("user-store", "data"),
        Input("boot-interval", "n_intervals"),
        Input("main-tabs", "active_tab"),
    )
    def load_user(_, __):
        """Fetch user info into store. Session-scoped, doesn't change."""
        return _api_get("/api/me") or {}

    @dash_app.callback(
        Output("account-selector", "options"),
        Input("accounts-store", "data"),
    )
    def update_account_selector(accounts):
        """Build dropdown options from cached accounts store."""
        options = [{"label": "All Accounts", "value": "all"}]
        if accounts:
            options += [{"label": a["name"], "value": str(a["id"])} for a in accounts]
        return options

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
        Input("market-selector", "value"),
    )
    def update_overview(account_val, cap_pct, market_val):
        cap_pct = cap_pct or 30
        try:
            params = _filter_params(account_val, market_val)
            params["risk_margin_pct"] = cap_pct

            resp = requests.get(
                f"{API_BASE}/api/dashboard/summary", params=params, headers=_get_user_headers(), timeout=15
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
            unavailable_underlying_count = 0
            for u in sorted(exposure.keys()):
                e = exposure[u]
                mp = e.get("market_price")
                price_unavail = e.get("price_unavailable", False)
                if price_unavail:
                    unavailable_underlying_count += 1
                mp_str = f"${mp:,.2f}" if mp is not None else "N/A"
                mp_style = {**td_style, "color": TEXT_PRIMARY, "display": "inline-block", "width": "20%"}
                if mp is None:
                    mp_style["color"] = ACCENT_WARN
                    mp_style["fontStyle"] = "italic"

                loss_val = e.get("est_loss", 0)
                loss_str = fmt_money(loss_val)
                loss_style = {**td_style, "color": ACCENT_LOSS, "display": "inline-block", "width": "20%"}
                if price_unavail:
                    loss_str = f"{loss_str} *"
                    loss_style["color"] = ACCENT_WARN

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
                                style=mp_style,
                            ),
                            html.Span(
                                fmt_money(e.get("est_profit", 0)),
                                style={**td_style, "color": ACCENT_PROFIT, "display": "inline-block", "width": "20%"},
                            ),
                            html.Span(
                                loss_str,
                                style=loss_style,
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
                    pos_rmp_str = f"${pos_rmp:,.2f}" if pos_rmp is not None else "N/A"
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

            if unavailable_underlying_count:
                warning = dbc.Alert(
                    f"Price data unavailable for {unavailable_underlying_count} underlying(s). "
                    "Estimated losses shown as $0.00 may not reflect actual risk.",
                    color="warning",
                    style={"fontSize": "0.85rem", "marginBottom": "1rem"},
                )
                exposure_table = html.Div([warning, exposure_table])

            return cards, exposure_table
        except Exception as e:
            return html.Div(f"Error loading overview: {e}"), html.Div("")

    # ---- Refresh Prices callback ----
    @dash_app.callback(
        Output("refresh-prices-status", "children"),
        Input("refresh-prices-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def refresh_prices(n_clicks):
        if not n_clicks:
            return ""
        try:
            resp = requests.post(f"{API_BASE}/api/prices/refresh", headers=_get_user_headers(), timeout=120)
            data = resp.json()
            refreshed = data.get("refreshed", 0)
            failed = data.get("failed", 0)
            if failed > 0:
                return f"Updated {refreshed}, failed {failed}"
            return f"Updated {refreshed} prices"
        except Exception as e:
            return f"Error: {e}"

    # ---- Positions data loader ----
    @dash_app.callback(
        Output("positions-store", "data"),
        Input("account-selector", "value"),
        Input("market-selector", "value"),
    )
    def load_positions(account_val, market_val):
        """Fetch positions into store, shared by positions tab and expiration tab."""
        params = _filter_params(account_val, market_val)
        data = _api_get("/api/positions", params=params)
        if data is None:
            return []
        # Enrich with days-to-expiry once
        for p in data:
            try:
                p["days_to_expiry"] = (date.fromisoformat(p["expiry"]) - date.today()).days
            except (ValueError, KeyError):
                p["days_to_expiry"] = 999
        return data

    # ---- Positions callbacks ----
    @dash_app.callback(
        Output("positions-table", "data"),
        Output("positions-table", "columns"),
        Input("positions-store", "data"),
    )
    def update_positions(positions):
        if not positions:
            return [], []
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

    # ---- Risk callbacks ----
    @dash_app.callback(
        Output("risk-summary", "children"),
        Output("loss-by-underlying-chart", "figure"),
        Output("account-risk-chart", "figure"),
        Output("riskiest-positions", "children"),
        Input("account-selector", "value"),
        Input("market-selector", "value"),
        State("risk-cap-pct", "data"),
    )
    def update_risk(account_val, market_val, cap_pct):
        empty_fig = go.Figure()
        empty_fig.update_layout(**PLOT_LAYOUT)
        cap_pct = cap_pct or 30
        try:
            params = _filter_params(account_val, market_val)

            # Single API call fetches all margin percentages at once
            pcts_to_fetch = sorted(set([0, 5, 10, 20, cap_pct]))
            params["pcts"] = ",".join(str(p) for p in pcts_to_fetch)
            resp = requests.get(
                f"{API_BASE}/api/dashboard/summary-multi", params=params, headers=_get_user_headers(), timeout=15
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

            # -- Top 10 riskiest positions (price-unavailable first, then by est. loss) --
            def _risk_sort_key(p):
                """Sort by: price-unavailable first (highest priority), then by est_loss descending."""
                if p.get("price_unavailable"):
                    return (0, float("inf"))
                return (1, -float(p.get("est_loss", 0)))

            sorted_positions = sorted(all_positions, key=_risk_sort_key)[:10]
            if not sorted_positions:
                riskiest = html.Small("No positions found.", style={"color": TEXT_SECONDARY})
            else:
                items = []
                for p in sorted_positions:
                    loss = float(p.get("est_loss", 0))
                    unavail = p.get("price_unavailable", False)
                    loss_color = ACCENT_WARN if unavail else ACCENT_LOSS
                    loss_text = f"Est. Loss: {fmt_money(loss)}"
                    if unavail:
                        loss_text = f"{loss_text} (price unavailable)"
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
                                            f"{loss_text} | Expiry: {p.get('expiry', '')}",
                                            style={"color": loss_color},
                                        ),
                                        *(
                                            [
                                                html.Br(),
                                                html.Small(
                                                    "Risk unknown — price fetch failed",
                                                    style={"color": ACCENT_WARN, "fontStyle": "italic"},
                                                ),
                                            ]
                                            if unavail
                                            else []
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
        Input("positions-store", "data"),
    )
    def update_expiration(positions):
        if not positions:
            empty = [html.Small("No positions")]
            return empty, empty, empty, empty

        lt7, w7to14, w14to21, gt21 = [], [], [], []
        for p in positions:
            try:
                dte = p.get("days_to_expiry", 999)
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
                requests.delete(f"{API_BASE}/api/accounts/{account_id}", headers=_get_user_headers(), timeout=5)
            return account_id
        return dash.no_update

    @dash_app.callback(
        Output("accounts-list", "children"),
        Input("accounts-store", "data"),
    )
    def update_accounts_list(accounts):
        """Build accounts list in settings from cached store."""
        if not accounts:
            return []
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

    @dash_app.callback(
        Output("edit-account-form", "style"),
        Output("edit-account-form", "className"),
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
            return {"display": "none"}, "d-none", dash.no_update, "", "", "", "true"
        # Edit button clicked
        if isinstance(triggered, dict) and triggered.get("type") == "edit-account-btn":
            account_id = triggered["index"]
            try:
                resp = requests.get(f"{API_BASE}/api/accounts/{account_id}", headers=_get_user_headers(), timeout=5)
                a = resp.json()
                return (
                    {"display": "block"},
                    "",
                    account_id,
                    a.get("name", ""),
                    a.get("token", ""),
                    a.get("query_id", ""),
                    "true" if a.get("enabled") else "false",
                )
            except Exception:
                return {"display": "none"}, "d-none", dash.no_update, "", "", "", "true"
        return {"display": "none"}, "d-none", dash.no_update, "", "", "", "true"

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
                timeout=5,
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

        # Case 1: Button click — trigger downloads (guard against DOM-mount trigger)
        if triggered == "sync-all-btn.n_clicks" and n_clicks:
            try:
                url = f"{API_BASE}/api/flex/download"
                _logger.info("POST %s", url)
                resp = requests.post(url, headers=_get_user_headers(), timeout=15)
                _logger.info("POST response: status=%s body=%s", resp.status_code, resp.text[:500])
                if not resp.ok:
                    return (
                        {},
                        [
                            html.Small(
                                f"API error {resp.status_code}: {resp.text[:200]}",
                                style={"color": ACCENT_LOSS},
                            )
                        ],
                        True,
                    )
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
                                        html.Span(
                                            " — Pending...", style={"color": ACCENT_WARN, "marginLeft": "0.5rem"}
                                        ),
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
                return {"ids": job_ids, "attempts": 0, "statuses": {}, "fail_counts": {}}, cards, len(job_ids) == 0
            except Exception as e:
                _logger.exception("handle_sync button click failed")
                return {}, [html.Small(f"Error: {e}", style={"color": ACCENT_LOSS})], True

        # Case 2: Interval tick — poll for status
        if not current_job_ids:
            return dash.no_update, dash.no_update, True

        attempts += 1
        timed_out = attempts >= _max_poll_attempts
        last_statuses = (store_data or {}).get("statuses", {})
        fail_counts: dict = (store_data or {}).get("fail_counts", {})

        headers = _get_user_headers()
        _logger.info(
            "Polling %d jobs (attempt %d/%d): %s", len(current_job_ids), attempts, _max_poll_attempts, current_job_ids
        )

        def _fetch_job(job_id):
            try:
                resp = requests.get(f"{API_BASE}/api/flex/download/{job_id}", headers=headers, timeout=15)
                _logger.info("Poll %s: status=%s body=%s", job_id, resp.status_code, resp.text[:200])
                return job_id, resp.json()
            except Exception as e:
                _logger.warning("Poll %s failed: %s", job_id, e)
                return job_id, None

        results: dict[str, dict] = {}
        with ThreadPoolExecutor() as pool:
            futures = {pool.submit(_fetch_job, jid): jid for jid in current_job_ids}
            for future in as_completed(futures):
                jid, data = future.result()
                results[jid] = data

        cards = []
        all_done = True
        for job_id in current_job_ids:
            data = results.get(job_id)
            poll_failed = data is None
            if not poll_failed:
                status = data.get("status", "unknown")
                last_statuses[job_id] = data
                fail_counts[job_id] = 0
            else:
                # Poll failed — reuse last-known result if available
                data = last_statuses.get(job_id, {"status": "unknown"})
                status = data.get("status", "unknown")
                fail_counts[job_id] = fail_counts.get(job_id, 0) + 1
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
                detail = html.Small(
                    " — Max poll attempts reached", style={"color": TEXT_SECONDARY, "marginLeft": "0.5rem"}
                )
            else:
                all_done = False
                label = {"requesting": "Requesting...", "polling": "Polling..."}.get(status, "Pending...")
                badge = dbc.Badge(label, color="warning")
                retry_count = fail_counts.get(job_id, 0)
                detail = html.Small(
                    f" — retrying ({retry_count})" if retry_count else "",
                    style={"color": ACCENT_WARN, "marginLeft": "0.5rem"},
                )

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
        new_store = {
            "ids": current_job_ids,
            "attempts": attempts,
            "statuses": last_statuses,
            "fail_counts": fail_counts,
        }
        return new_store, cards, stop

    # ---- User Menu callback ----
    @dash_app.callback(
        Output("user-menu", "children"),
        Input("user-store", "data"),
    )
    def update_user_menu(data):
        """Build user menu from cached user store."""
        if not data or not data.get("authenticated"):
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

    # ---- Screener callbacks ----

    @dash_app.callback(
        Output("screener-watchlist-store", "data"),
        Output("add-symbol-status", "children"),
        Input("main-tabs", "active_tab"),
        Input("add-symbol-btn", "n_clicks"),
        Input({"type": "remove-symbol-btn", "index": dash.dependencies.ALL}, "n_clicks"),
        State("add-symbol-input", "value"),
        prevent_initial_call=True,
    )
    def manage_watchlist(active_tab, add_clicks, remove_clicks, new_symbol):
        ctx = dash.callback_context
        triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

        headers = _get_user_headers()
        status_msg = ""

        # Remove symbol
        if "remove-symbol-btn" in triggered:
            triggered_id = dash.callback_context.triggered_id
            if isinstance(triggered_id, dict) and triggered_id.get("type") == "remove-symbol-btn":
                sym = triggered_id["index"]
                try:
                    requests.delete(
                        f"{API_BASE}/api/screener/watchlist/{sym}",
                        headers=headers,
                        timeout=5,
                    )
                    status_msg = f"Removed {sym}"
                except Exception as e:
                    status_msg = f"Failed: {e}"

        # Add symbol
        elif "add-symbol-btn" in triggered and add_clicks and new_symbol:
            symbol_upper = new_symbol.strip().upper()
            if not symbol_upper:
                status_msg = "Enter a symbol"
            else:
                try:
                    resp = requests.post(
                        f"{API_BASE}/api/screener/watchlist",
                        json={"symbol": symbol_upper},
                        headers=headers,
                        timeout=5,
                    )
                    if resp.ok:
                        status_msg = f"Added {symbol_upper}"
                    else:
                        detail = resp.json().get("detail", resp.text[:50])
                        status_msg = detail
                except Exception as e:
                    status_msg = f"Failed: {e}"

        # Fetch current watchlist
        try:
            resp = requests.get(f"{API_BASE}/api/screener/watchlist", headers=headers, timeout=5)
            data = resp.json()
            symbols = data.get("symbols", [])
        except Exception:
            symbols = []

        return symbols, status_msg

    @dash_app.callback(
        Output("watchlist-tags", "children"),
        Input("screener-watchlist-store", "data"),
    )
    def render_watchlist_tags(symbols):
        if not symbols:
            return []
        tags = []
        for sym in symbols:
            tags.append(
                html.Span(
                    [
                        html.Span(sym, style={"marginRight": "0.3rem"}),
                        html.Span(
                            "x",
                            id={"type": "remove-symbol-btn", "index": sym},
                            style={
                                "cursor": "pointer",
                                "fontWeight": 700,
                                "fontSize": "0.7rem",
                                "color": TEXT_SECONDARY,
                            },
                        ),
                    ],
                    style={
                        "backgroundColor": BG_CARD_HEADER,
                        "border": f"1px solid {BORDER}",
                        "borderRadius": "4px",
                        "padding": "0.2rem 0.5rem",
                        "fontSize": "0.8rem",
                        "color": TEXT_PRIMARY,
                        "marginRight": "0.4rem",
                        "display": "inline-block",
                    },
                )
            )
        return tags

    @dash_app.callback(
        Output("filter-min-iv", "value"),
        Output("filter-min-delta", "value"),
        Output("filter-max-delta", "value"),
        Output("filter-min-dte", "value"),
        Output("filter-max-dte", "value"),
        Output("filter-min-otm", "value"),
        Output("filter-min-roc", "value"),
        Output("filter-max-capital", "value"),
        Input("main-tabs", "active_tab"),
        State("screener-filters-store", "data"),
        prevent_initial_call=True,
    )
    def restore_filters(active_tab, saved):
        if active_tab != "suggestions" or not saved:
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
        return (
            saved.get("min_iv", 30),
            saved.get("min_delta", 0.15),
            saved.get("max_delta", 0.35),
            saved.get("min_dte", 21),
            saved.get("max_dte", 45),
            saved.get("min_otm", 5),
            saved.get("min_roc", 12),
            saved.get("max_capital", 50000),
        )

    @dash_app.callback(
        Output("screener-results-store", "data"),
        Output("scan-status", "children"),
        Output("screener-filters-store", "data"),
        Input("scan-btn", "n_clicks"),
        State("filter-min-iv", "value"),
        State("filter-min-delta", "value"),
        State("filter-max-delta", "value"),
        State("filter-min-dte", "value"),
        State("filter-max-dte", "value"),
        State("filter-min-otm", "value"),
        State("filter-min-roc", "value"),
        State("filter-max-capital", "value"),
        prevent_initial_call=True,
    )
    def run_scan(
        n_clicks,
        min_iv,
        min_delta,
        max_delta,
        min_dte,
        max_dte,
        min_otm,
        min_roc,
        max_capital,
    ):
        if not n_clicks:
            return {}, "", dash.no_update

        # Save filter values for restoration on tab switch
        saved_filters = {
            "min_iv": min_iv,
            "min_delta": min_delta,
            "max_delta": max_delta,
            "min_dte": min_dte,
            "max_dte": max_dte,
            "min_otm": min_otm,
            "min_roc": min_roc,
            "max_capital": max_capital,
        }

        try:
            payload = {}
            if min_iv is not None:
                payload["min_iv"] = min_iv / 100
            if min_delta is not None:
                payload["min_delta"] = min_delta
            if max_delta is not None:
                payload["max_delta"] = max_delta
            if min_dte is not None:
                payload["min_dte"] = min_dte
            if max_dte is not None:
                payload["max_dte"] = max_dte
            if min_otm is not None:
                payload["min_otm_pct"] = min_otm
            if min_roc is not None:
                payload["min_ann_roc"] = min_roc
            if max_capital is not None:
                payload["max_capital"] = max_capital

            headers = _get_user_headers()
            resp = requests.post(
                f"{API_BASE}/api/screener/scan",
                json=payload,
                headers=headers,
                timeout=120,
            )
            data = resp.json()
            status = f"Found {data.get('opportunities_found', 0)} opportunities"
            failed = data.get("failed_tickers", [])
            if failed:
                status += f" ({len(failed)} failed: {', '.join(failed)})"
            return data, status, saved_filters
        except Exception as e:
            return {}, f"Error: {e}", saved_filters

    @dash_app.callback(
        Output("screener-summary-cards", "children"),
        Input("screener-results-store", "data"),
    )
    def update_screener_summary(scan_data):
        results = scan_data.get("results", [])
        if not results:
            return html.Small("Click Scan to find CSP opportunities.", style={"color": TEXT_SECONDARY})

        watchlist_count = scan_data.get("watchlist_count", 0)
        total_capital = sum(r.get("capital_required", 0) for r in results)
        avg_iv = sum(r.get("iv", 0) for r in results) / len(results) if results else 0

        return dbc.Row(
            [
                dbc.Col(kpi_card("Watchlist", str(watchlist_count), ACCENT_INFO), lg=2, sm=6),
                dbc.Col(kpi_card("Opportunities", str(len(results)), ACCENT_PROFIT), lg=2, sm=6),
                dbc.Col(kpi_card("Avg IV", f"{avg_iv * 100:.1f}%", ACCENT_WARN), lg=2, sm=6),
                dbc.Col(kpi_card("Total Capital", fmt_money(total_capital), ACCENT_PROFIT), lg=2, sm=6),
                dbc.Col(
                    kpi_card("Scanned", scan_data.get("scanned_at", "")[:19].replace("T", " "), TEXT_SECONDARY),
                    lg=4,
                    sm=6,
                ),
            ]
        )

    @dash_app.callback(
        Output("filter-ticker", "options"),
        Input("screener-results-store", "data"),
    )
    def update_ticker_options(scan_data):
        results = scan_data.get("results", [])
        symbols = sorted({r.get("symbol") for r in results if r.get("symbol")})
        return [{"label": s, "value": s} for s in symbols]

    @dash_app.callback(
        Output("screener-table", "data"),
        Output("screener-table", "columns"),
        Input("screener-results-store", "data"),
        Input("main-tabs", "active_tab"),
        Input("filter-ticker", "value"),
        Input("filter-rating", "value"),
    )
    def update_screener_table(scan_data, active_tab, ticker, min_rating):
        results = scan_data.get("results", [])
        if not results or active_tab != "suggestions":
            return [], []

        if ticker:
            results = [r for r in results if r.get("symbol") == ticker]
        if min_rating:
            results = [r for r in results if r.get("rating", 0) >= min_rating]

        cols = [
            {"name": "Ticker", "id": "symbol"},
            {"name": "Price", "id": "price", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Strike", "id": "strike", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Expiry", "id": "expiry"},
            {"name": "DTE", "id": "dte", "type": "numeric"},
            {"name": "Bid", "id": "bid", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Ann.ROC%", "id": "ann_roc_pct", "type": "numeric", "format": {"specifier": ".1f"}},
            {"name": "IV", "id": "iv_display"},
            {"name": "Delta", "id": "delta", "type": "numeric", "format": {"specifier": ".2f"}},
            {"name": "Rating", "id": "rating_display"},
        ]

        rows = []
        for r in results:
            stars = "\u2605" * r.get("rating", 0)
            rows.append(
                {
                    "symbol": r.get("symbol"),
                    "price": r.get("price"),
                    "strike": r.get("strike"),
                    "expiry": r.get("expiry"),
                    "dte": r.get("dte"),
                    "bid": r.get("bid"),
                    "ann_roc_pct": r.get("ann_roc_pct"),
                    "iv_display": f"{r.get('iv', 0) * 100:.1f}%",
                    "delta": r.get("delta"),
                    "rating": r.get("rating"),
                    "rating_display": f"{stars} {r.get('rating_label', '')}",
                    "_full": r,
                }
            )

        return rows, cols

    @dash_app.callback(
        Output("screener-detail-panel", "children"),
        Output("screener-detail-panel", "style"),
        Input("screener-table", "active_cell"),
        State("screener-table", "data"),
    )
    def show_detail(active_cell, table_data):
        if not active_cell or not table_data:
            return html.Div(), {"display": "none"}

        row_idx = active_cell.get("row")
        if row_idx is None or row_idx >= len(table_data):
            return html.Div(), {"display": "none"}

        r = table_data[row_idx].get("_full", {})

        detail_style = {
            "backgroundColor": BG_CARD,
            "border": f"1px solid {BORDER}",
            "borderRadius": "8px",
            "padding": "1rem",
            "marginTop": "0.5rem",
        }

        def _metric(label, value):
            return html.Div(
                [
                    html.Div(
                        label, style={"color": TEXT_SECONDARY, "fontSize": "0.7rem", "textTransform": "uppercase"}
                    ),
                    html.Div(str(value), style={"color": TEXT_PRIMARY, "fontSize": "0.9rem", "fontWeight": 600}),
                ],
                style={"marginRight": "1.5rem"},
            )

        fund_badge = ""
        if r.get("strong_fundamentals"):
            fund_badge = html.Span(
                " \u2605 Strong Fundamentals",
                style={"color": ACCENT_PROFIT, "fontSize": "0.8rem", "marginLeft": "0.5rem"},
            )

        return html.Div(
            [
                html.Div(
                    [
                        html.Strong(
                            f"{r.get('symbol')} ${r.get('strike')}P", style={"color": TEXT_PRIMARY, "fontSize": "1rem"}
                        ),
                        html.Span(f" exp {r.get('expiry')}", style={"color": TEXT_SECONDARY}),
                        fund_badge,
                    ],
                    style={"marginBottom": "0.75rem"},
                ),
                html.Div(
                    [
                        _metric("Mid", f"${r.get('mid', 0):.2f}"),
                        _metric("OTM%", f"{r.get('otm_pct', 0):.1f}%"),
                        _metric("Capital", fmt_money(r.get("capital_required", 0))),
                        _metric("P/E", f"{r.get('pe_ratio', 'N/A')}" if r.get("pe_ratio") else "N/A"),
                        _metric("Beta", f"{r.get('beta', 'N/A')}" if r.get("beta") else "N/A"),
                        _metric("Margin", f"{r.get('profit_margin', 0):.1f}%" if r.get("profit_margin") else "N/A"),
                        _metric(
                            "Rev Growth", f"{r.get('revenue_growth', 0):.1f}%" if r.get("revenue_growth") else "N/A"
                        ),
                    ],
                    className="d-flex flex-wrap",
                ),
            ]
        ), detail_style
