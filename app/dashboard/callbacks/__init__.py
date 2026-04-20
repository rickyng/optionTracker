import contextlib
import logging
import os
import time
from collections import defaultdict
from datetime import date, timedelta

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
    TEXT_ACCENT,
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


def _api_get(path, params=None, timeout=5, max_retries=2):
    """GET from internal API with retry on transient errors. Returns parsed JSON or None."""
    headers = _get_user_headers()
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(f"{API_BASE}{path}", params=params, headers=headers, timeout=timeout)
            if not resp.ok:
                return None
            return resp.json()
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(2 * (attempt + 1))
                continue
        except Exception as e:
            _logger.warning("API GET %s failed: %s", path, e)
            return None
    _logger.warning("API GET %s failed after %d retries: %s", path, max_retries, last_exc)
    return None


def _api_post(path, json=None, timeout=15, max_retries=2):
    """POST to internal API with retry on transient errors. Returns parsed JSON or None."""
    headers = _get_user_headers()
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(f"{API_BASE}{path}", json=json, headers=headers, timeout=timeout)
            if not resp.ok:
                return None
            return resp.json()
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(2 * (attempt + 1))
                continue
        except Exception as e:
            _logger.warning("API POST %s failed: %s", path, e)
            return None
    _logger.warning("API POST %s failed after %d retries: %s", path, max_retries, last_exc)
    return None


def _api_delete(path, timeout=5, max_retries=2):
    """DELETE from internal API with retry on transient errors. Returns Response or None."""
    headers = _get_user_headers()
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return requests.delete(f"{API_BASE}{path}", headers=headers, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(2 * (attempt + 1))
                continue
        except Exception as e:
            _logger.warning("API DELETE %s failed: %s", path, e)
            return None
    _logger.warning("API DELETE %s failed after %d retries: %s", path, max_retries, last_exc)
    return None


def _api_put(path, params=None, timeout=5, max_retries=2):
    """PUT to internal API with retry on transient errors. Returns Response or None."""
    headers = _get_user_headers()
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return requests.put(f"{API_BASE}{path}", params=params, headers=headers, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            if attempt < max_retries:
                time.sleep(2 * (attempt + 1))
                continue
        except Exception as e:
            _logger.warning("API PUT %s failed: %s", path, e)
            return None
    _logger.warning("API PUT %s failed after %d retries: %s", path, max_retries, last_exc)
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

            data = _api_get("/api/dashboard/summary", params=params, timeout=15)
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
                                "Earnings",
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

                # Earnings date is at underlying level — compute display once
                earnings_raw = e.get("earnings_date")

                for pos in positions:
                    pos_rmp = pos.get("risk_margin_price")
                    pos_rmp_str = f"${pos_rmp:,.2f}" if pos_rmp is not None else "N/A"

                    # Only show earnings if before this position's expiry
                    earnings_str = ""
                    earnings_color = TEXT_SECONDARY
                    if earnings_raw:
                        try:
                            earnings_dt = date.fromisoformat(earnings_raw)
                            expiry_dt = date.fromisoformat(pos.get("expiry", ""))
                            if earnings_dt <= expiry_dt:
                                days_to_earnings = (earnings_dt - date.today()).days
                                earnings_str = f"{earnings_raw} ({days_to_earnings}d)"
                                if days_to_earnings <= 7:
                                    earnings_color = ACCENT_WARN
                        except (ValueError, TypeError):
                            pass

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
                                    earnings_str,
                                    style={"color": earnings_color, "padding": "0.35rem 0.6rem", "fontSize": "0.8rem"},
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
            pct_data = _api_get("/api/dashboard/summary-multi", params=params, timeout=15)
            if pct_data is None:
                return html.Div("Failed to load risk data"), dash.no_update

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
        Output("expiry-this-week", "children"),
        Output("expiry-next-week", "children"),
        Output("expiry-next-next-week", "children"),
        Output("expiry-beyond", "children"),
        Input("positions-store", "data"),
        Input("main-tabs", "active_tab"),
    )
    def update_expiration(positions, active_tab):
        if active_tab != "expiration":
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update

        if not positions:
            empty = [html.Small("No positions")]
            return empty, empty, empty, empty

        # Fetch market prices for all underlyings
        market_prices = {}
        try:
            price_data = _api_get("/api/sync/price-status", timeout=10)
            if price_data and price_data.get("symbols"):
                for sym in price_data["symbols"]:
                    market_prices[sym["symbol"]] = sym.get("price")
        except Exception:
            pass

        def calc_moneyness(p):
            """Calculate moneyness category: ITM, ATM, 5% OTM, 10% OTM."""
            underlying = p.get("underlying")
            strike = p.get("strike")
            right = p.get("right")  # "C" or "P"
            price = market_prices.get(underlying)

            if price is None or strike is None:
                return "N/A", TEXT_SECONDARY

            # For short puts: ITM when price < strike (obligated to buy at higher strike)
            # For short calls: ITM when price > strike (obligated to sell at lower strike)
            if right == "P":
                if price < strike:
                    otm_pct = ((strike - price) / price) * 100
                    if otm_pct <= 5:
                        return "ITM", ACCENT_PROFIT
                    elif otm_pct <= 10:
                        return "5% ITM", ACCENT_WARN
                    else:
                        return "10% ITM", ACCENT_LOSS
                else:
                    otm_pct = ((price - strike) / price) * 100
                    if otm_pct <= 5:
                        return "ATM", TEXT_SECONDARY
                    elif otm_pct <= 10:
                        return "5% OTM", ACCENT_WARN
                    else:
                        return "10% OTM", ACCENT_LOSS
            else:
                if price > strike:
                    otm_pct = ((price - strike) / price) * 100
                    if otm_pct <= 5:
                        return "ITM", ACCENT_PROFIT
                    elif otm_pct <= 10:
                        return "5% ITM", ACCENT_WARN
                    else:
                        return "10% ITM", ACCENT_LOSS
                else:
                    otm_pct = ((strike - price) / price) * 100
                    if otm_pct <= 5:
                        return "ATM", TEXT_SECONDARY
                    elif otm_pct <= 10:
                        return "5% OTM", ACCENT_WARN
                    else:
                        return "10% OTM", ACCENT_LOSS

        # Calendar week boundaries (week starts Monday)
        today = date.today()
        days_until_sunday = 6 - today.weekday()
        end_this_week = today + timedelta(days=days_until_sunday)
        end_next_week = end_this_week + timedelta(days=7)
        end_next_next_week = end_next_week + timedelta(days=7)

        # Group positions by calendar-week bucket and moneyness
        buckets = {
            "this_week": {"ITM": [], "5% OTM": [], "10% OTM": [], "N/A": []},
            "next_week": {"ITM": [], "5% OTM": [], "10% OTM": [], "N/A": []},
            "next_next_week": {"ITM": [], "5% OTM": [], "10% OTM": [], "N/A": []},
            "beyond": {"ITM": [], "5% OTM": [], "10% OTM": [], "N/A": []},
        }

        for p in positions:
            try:
                expiry_str = p.get("expiry", "")
                if not expiry_str:
                    continue
                expiry = date.fromisoformat(expiry_str)
                if expiry < today:
                    continue
                dte = (expiry - today).days
                moneyness, moneyness_color = calc_moneyness(p)

                # Normalize moneyness to bucket key
                if moneyness == "N/A":
                    bucket_key = "N/A"
                elif moneyness in ("ITM", "5% ITM"):
                    bucket_key = "ITM"
                elif moneyness in ("5% OTM", "ATM"):
                    bucket_key = "5% OTM"
                else:
                    bucket_key = "10% OTM"

                # Create badge for moneyness
                moneyness_badge = dbc.Badge(
                    moneyness,
                    color=None,
                    pill=True,
                    style={
                        "backgroundColor": moneyness_color,
                        "color": "#0f0f1a" if moneyness_color in (ACCENT_PROFIT, ACCENT_WARN) else "#fff",
                        "fontSize": "0.65rem",
                        "fontWeight": 600,
                        "marginLeft": "0.5rem",
                    },
                )

                item = dbc.Card(
                    [
                        dbc.CardBody(
                            [
                                html.Strong(p["underlying"], style={"color": TEXT_PRIMARY}),
                                html.Span(f" {p['right']} {p['strike']}", style={"color": TEXT_SECONDARY}),
                                moneyness_badge,
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

                # Assign to calendar-week bucket
                if expiry <= end_this_week:
                    buckets["this_week"][bucket_key].append(item)
                elif expiry <= end_next_week:
                    buckets["next_week"][bucket_key].append(item)
                elif expiry <= end_next_next_week:
                    buckets["next_next_week"][bucket_key].append(item)
                else:
                    buckets["beyond"][bucket_key].append(item)
            except (ValueError, KeyError):
                pass

        def build_bucket_content(bucket_data: dict) -> list:
            """Build grouped content for a week bucket with moneyness sub-headers."""
            total_count = sum(len(items) for items in bucket_data.values())
            content = [_count_badge([None] * total_count)]

            order = [
                ("ITM", ACCENT_PROFIT),
                ("5% OTM", ACCENT_WARN),
                ("10% OTM", ACCENT_LOSS),
                ("N/A", TEXT_SECONDARY),
            ]

            for label, color in order:
                items = bucket_data.get(label, [])
                if not items:
                    continue

                sub_header = html.Div(
                    [
                        html.Span(
                            label,
                            style={
                                "color": color,
                                "fontSize": "0.75rem",
                                "fontWeight": 600,
                            },
                        ),
                        html.Span(
                            f" ({len(items)})",
                            style={"color": TEXT_SECONDARY, "fontSize": "0.7rem"},
                        ),
                    ],
                    style={
                        "marginTop": "0.5rem",
                        "marginBottom": "0.25rem",
                        "paddingLeft": "0.25rem",
                        "borderBottom": f"1px solid {BORDER}",
                    },
                )
                content.append(sub_header)
                content.extend(items)

            if total_count == 0:
                content.append(html.Small("None", style={"color": TEXT_SECONDARY}))

            return content

        return (
            build_bucket_content(buckets["this_week"]),
            build_bucket_content(buckets["next_week"]),
            build_bucket_content(buckets["next_next_week"]),
            build_bucket_content(buckets["beyond"]),
        )

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
                _api_delete(f"/api/accounts/{account_id}")
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
                a = _api_get(f"/api/accounts/{account_id}")
                if a is None:
                    return {"display": "none"}, "d-none", dash.no_update, "", "", "", "true"
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
            resp = _api_put(f"/api/accounts/{account_id}", params=params)
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
            resp = _api_post(
                "/api/accounts",
                json={"name": name, "token": token, "query_id": query_id},
                timeout=10,
            )
            if not resp:
                return html.Small("Network error", style={"color": ACCENT_LOSS})
            result = resp
            return html.Small(
                f"Created: {result.get('name', '')} (ID: {result.get('id', '')})", style={"color": ACCENT_PROFIT}
            )
        except Exception as e:
            return html.Small(f"Error: {e}", style={"color": ACCENT_LOSS})

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

    # ---- Global Sync Banner ----
    @dash_app.callback(
        Output("sync-status-banner", "children"),
        Input("sync-status-store", "data"),
    )
    def render_sync_banner(status_data):
        """Render global sync status banner across all tabs."""
        if not status_data:
            # No sync job — show last sync time from API
            try:
                last_sync = _api_get("/api/sync/last-sync")
                if last_sync and last_sync.get("last_sync"):
                    ts = last_sync["last_sync"]
                    age = _format_age(ts)
                    return html.Div(
                        [
                            html.Span(f"Data synced {age}", style={"color": TEXT_SECONDARY, "fontSize": "0.8rem"}),
                            html.A(
                                "Refresh",
                                href="/dashboard",
                                style={"color": TEXT_ACCENT, "fontSize": "0.8rem", "marginLeft": "0.5rem"},
                            ),
                        ],
                        style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
                    )
            except Exception:
                pass
            return html.Div()

        status = status_data.get("status", "")
        current_step = status_data.get("current_step", 0)
        step_name = status_data.get("step_name", "")
        error = status_data.get("error")

        if status == "pending":
            # Job queued but not yet running
            return html.Div(
                [
                    dbc.Spinner(size="sm", color="primary"),
                    html.Span(" Queuing sync...", style={"color": TEXT_PRIMARY, "fontSize": "0.85rem"}),
                ],
                style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
            )

        if status == "syncing" or status == "running":
            # Show progress
            return html.Div(
                [
                    dbc.Spinner(size="sm", color="primary"),
                    html.Span(
                        f" Syncing {step_name} ({current_step}/3)...",
                        style={"color": TEXT_PRIMARY, "fontSize": "0.85rem"},
                    ),
                ],
                style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
            )

        if status == "retrying":
            retry_count = status_data.get("retry_count", 0)
            return html.Div(
                [
                    dbc.Spinner(size="sm", color="warning"),
                    html.Span(
                        f" Retrying {step_name} ({retry_count}/3)...",
                        style={"color": ACCENT_WARN, "fontSize": "0.85rem"},
                    ),
                ],
                style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
            )

        if status == "completed":
            last_sync = status_data.get("last_sync")
            if last_sync:
                age = _format_age(last_sync)
                return html.Div(
                    [
                        html.Span(f"Data synced {age}", style={"color": ACCENT_PROFIT, "fontSize": "0.85rem"}),
                        html.Span(" ✓", style={"color": ACCENT_PROFIT}),
                    ],
                    style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
                )

        if status == "error":
            return html.Div(
                [
                    html.Span(f"Sync failed: {error}", style={"color": ACCENT_LOSS, "fontSize": "0.85rem"}),
                    html.A("Retry", href="/dashboard", style={"color": TEXT_ACCENT, "marginLeft": "0.5rem"}),
                ],
                style={"padding": "0.25rem 0.5rem", "backgroundColor": BG_CARD, "borderRadius": "4px"},
            )

        return html.Div()

    # ---- Sync All Data Pipeline ----
    _max_sync_poll_attempts = 100

    @dash_app.callback(
        Output("sync-status-store", "data"),
        Output("sync-progress-list", "children"),
        Output("sync-last-time", "children"),
        Output("sync-banner-poll-interval", "disabled"),
        Output("settings-stale-check", "disabled"),
        Input("sync-force-btn", "n_clicks"),
        Input("sync-smart-btn", "n_clicks"),
        Input("sync-banner-poll-interval", "n_intervals"),
        Input("settings-stale-check", "n_intervals"),
        State("sync-status-store", "data"),
        prevent_initial_call=True,
    )
    def handle_sync_pipeline(force_clicks, smart_clicks, poll_intervals, stale_check, store_data):
        """Handle Sync buttons + polling."""
        ctx = dash.callback_context
        triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""

        # Case 1: Stale check on settings tab load — auto-trigger if data is old
        if triggered == "settings-stale-check.n_intervals":
            try:
                last_sync = _api_get("/api/sync/last-sync")
                if last_sync and last_sync.get("last_sync"):
                    ts = last_sync["last_sync"]
                    age_hours = _get_age_hours(ts)
                    if age_hours >= 24:
                        # Auto-trigger smart sync
                        resp = _api_post("/api/sync/all?force=false", timeout=10)
                        if resp:
                            data = resp
                            job_id = data.get("job_id")
                            return {"job_id": job_id, "status": "pending"}, [], f"Last: {ts[:19]} (stale)", False, True
                # Data fresh or no last_sync
                return dash.no_update, dash.no_update, dash.no_update, True, True
            except Exception:
                return dash.no_update, dash.no_update, dash.no_update, True, True

        # Case 2: Button click — trigger sync
        if triggered == "sync-force-btn.n_clicks" and force_clicks:
            force = True
        elif triggered == "sync-smart-btn.n_clicks" and smart_clicks:
            force = False
        else:
            force = None

        if force is not None:
            try:
                force_str = "true" if force else "false"
                label = "Force" if force else "Smart"
                resp = _api_post(f"/api/sync/all?force={force_str}", timeout=10)
                if resp is None:
                    return {}, [html.Small("Network error", style={"color": ACCENT_LOSS})], "", True, dash.no_update
                data = resp
                job_id = data.get("job_id")
                return (
                    {"job_id": job_id, "status": "pending", "force": force},
                    [html.Small(f"{label} sync started...", style={"color": TEXT_SECONDARY})],
                    "",
                    False,
                    dash.no_update,
                )
            except Exception as e:
                return {}, [html.Small(f"Error: {e}", style={"color": ACCENT_LOSS})], "", True, dash.no_update

        # Case 3: Poll interval — fetch job status
        job_id = (store_data or {}).get("job_id")
        if not job_id:
            return dash.no_update, dash.no_update, dash.no_update, True, dash.no_update

        try:
            status_data = _api_get(f"/api/sync/status/{job_id}", timeout=10)
            if not status_data:
                # Job not found (404) — likely cleaned up after completion. Check last-sync.
                try:
                    last_sync = _api_get("/api/sync/last-sync")
                    if last_sync and last_sync.get("last_sync"):
                        ts = last_sync["last_sync"]
                        last_time = f"Last: {ts[:19]}"
                        return {"status": "completed", "last_sync": ts}, [], last_time, True, dash.no_update
                except Exception:
                    pass
                # Retry on transient failure
                return store_data, dash.no_update, dash.no_update, dash.no_update, dash.no_update

            status = status_data.get("status")
            current_step = status_data.get("current_step", 0)
            completed = status_data.get("completed_steps", [])
            error = status_data.get("error")

            # Build progress list
            step_names = ["IBKR Flex", "Stock Prices", "Earnings Dates"]
            progress_cards = []
            for i in range(1, 4):
                if i in completed:
                    badge = dbc.Badge("✓", color="success")
                elif i == current_step and status in ("running", "syncing"):
                    badge = dbc.Spinner(size="sm", color="primary")
                elif i == current_step and status == "retrying":
                    badge = dbc.Badge("Retrying", color="warning")
                elif status == "error" and i == current_step:
                    badge = dbc.Badge("Failed", color="danger")
                else:
                    badge = dbc.Badge("Pending", color="secondary")

                progress_cards.append(
                    html.Div(
                        [html.Span(step_names[i - 1], style={"color": TEXT_PRIMARY}), badge],
                        style={"marginRight": "1rem"},
                    )
                )

            progress_list = html.Div(progress_cards, className="d-flex flex-wrap")

            last_time = ""
            if status == "completed":
                last_time = f"Last: {status_data.get('last_sync', '')[:19]}"
                return status_data, progress_list, last_time, True, dash.no_update

            if status == "error":
                return (
                    status_data,
                    [html.Small(f"Error at step {current_step}: {error}", style={"color": ACCENT_LOSS})],
                    "",
                    True,
                    dash.no_update,
                )

            # Still running
            return status_data, progress_list, "", False, dash.no_update

        except Exception as e:
            return store_data, [html.Small(f"Poll error: {e}", style={"color": ACCENT_LOSS})], "", True, dash.no_update

    # ---- Account Sync Status ----
    @dash_app.callback(
        Output("account-sync-status", "children"),
        Input("main-tabs", "active_tab"),
        Input("accounts-store", "data"),
        Input("sync-status-store", "data"),
    )
    def update_account_sync_status(active_tab, accounts, sync_data):
        """Fetch and display account sync status in Settings tab."""
        # Refresh on settings tab or when sync completes
        if active_tab != "settings":
            return dash.no_update

        # Only trigger on sync completion (skip intermediate states)
        ctx = dash.callback_context
        triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        if (
            triggered == "sync-status-store.data"
            and sync_data
            and sync_data.get("status") not in ("completed", "error")
        ):
            return dash.no_update

        try:
            data = _api_get("/api/sync/account-status", timeout=10)
            if not data or not data.get("accounts"):
                return html.Small("No accounts configured", style={"color": TEXT_SECONDARY})

            accounts_list = data["accounts"]
            rows = []
            for acct in accounts_list:
                last_flex = acct.get("last_flex_update")
                if last_flex:
                    age = _format_age(last_flex)
                    flex_display = html.Span(age, style={"color": TEXT_SECONDARY, "fontSize": "0.75rem"})
                else:
                    flex_display = html.Span("Never", style={"color": ACCENT_WARN, "fontSize": "0.75rem"})

                enabled_badge = dbc.Badge(
                    "Enabled" if acct.get("enabled") else "Disabled",
                    color="success" if acct.get("enabled") else "secondary",
                    style={"fontSize": "0.7rem"},
                )

                pos_count = acct.get("position_count", 0)
                pos_color = ACCENT_PROFIT if pos_count > 0 else TEXT_SECONDARY

                rows.append(
                    html.Div(
                        [
                            html.Span(
                                acct["name"],
                                style={
                                    "color": TEXT_PRIMARY,
                                    "fontWeight": 600,
                                    "width": "25%",
                                    "display": "inline-block",
                                },
                            ),
                            html.Span(
                                f"{pos_count} pos",
                                style={
                                    "color": pos_color,
                                    "fontSize": "0.8rem",
                                    "width": "15%",
                                    "display": "inline-block",
                                },
                            ),
                            enabled_badge,
                            html.Span(
                                "Flex: ", style={"color": TEXT_SECONDARY, "fontSize": "0.75rem", "marginLeft": "1rem"}
                            ),
                            flex_display,
                        ],
                        style={
                            "padding": "0.5rem 0",
                            "borderBottom": f"1px solid {BORDER}",
                            "display": "flex",
                            "alignItems": "center",
                        },
                    )
                )

            return html.Div(rows, style={"width": "100%"})

        except Exception as e:
            return html.Small(f"Error: {e}", style={"color": ACCENT_LOSS})

    # ---- Price Sync Status ----
    @dash_app.callback(
        Output("price-sync-status", "children"),
        Input("main-tabs", "active_tab"),
        Input("sync-status-store", "data"),
    )
    def update_price_sync_status(active_tab, sync_data):
        """Fetch and display price sync status in Settings tab."""
        if active_tab != "settings":
            return dash.no_update

        # Only trigger on sync completion (skip intermediate states)
        ctx = dash.callback_context
        triggered = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
        if (
            triggered == "sync-status-store.data"
            and sync_data
            and sync_data.get("status") not in ("completed", "error")
        ):
            return dash.no_update

        try:
            data = _api_get("/api/sync/price-status", timeout=10)
            if not data or not data.get("symbols"):
                return html.Small("No positions loaded", style={"color": TEXT_SECONDARY})

            symbols_list = data["symbols"]
            last_sync = data.get("last_price_sync")
            sync_age = _format_age(last_sync) if last_sync else "Never"

            header = html.Div(
                [
                    html.Span(
                        "Symbol",
                        style={
                            "color": TEXT_SECONDARY,
                            "fontSize": "0.7rem",
                            "textTransform": "uppercase",
                            "width": "20%",
                            "display": "inline-block",
                            "fontWeight": 600,
                        },
                    ),
                    html.Span(
                        "Price",
                        style={
                            "color": TEXT_SECONDARY,
                            "fontSize": "0.7rem",
                            "textTransform": "uppercase",
                            "width": "20%",
                            "display": "inline-block",
                            "fontWeight": 600,
                        },
                    ),
                    html.Span(
                        "Options",
                        style={
                            "color": TEXT_SECONDARY,
                            "fontSize": "0.7rem",
                            "textTransform": "uppercase",
                            "width": "15%",
                            "display": "inline-block",
                            "fontWeight": 600,
                        },
                    ),
                    html.Span(
                        "Last Update",
                        style={
                            "color": TEXT_SECONDARY,
                            "fontSize": "0.7rem",
                            "textTransform": "uppercase",
                            "width": "25%",
                            "display": "inline-block",
                            "fontWeight": 600,
                        },
                    ),
                ],
                style={
                    "paddingBottom": "0.5rem",
                    "borderBottom": f"2px solid {BORDER}",
                    "display": "flex",
                },
            )

            rows = []
            for sym in symbols_list:
                price = sym.get("price")
                opt_count = sym.get("option_count", 0)
                last_updated = sym.get("last_updated")

                price_str = f"${price:.2f}" if price is not None else "N/A"
                price_color = TEXT_PRIMARY if price is not None else ACCENT_WARN

                if last_updated:
                    age = _format_age(last_updated)
                    age_color = (
                        ACCENT_PROFIT
                        if "just now" in age or "h ago" in age and int(age.split("h")[0]) < 24
                        else ACCENT_WARN
                    )
                else:
                    age = "Never"
                    age_color = ACCENT_LOSS

                rows.append(
                    html.Div(
                        [
                            html.Span(
                                sym["symbol"],
                                style={
                                    "color": TEXT_PRIMARY,
                                    "fontWeight": 600,
                                    "width": "20%",
                                    "display": "inline-block",
                                },
                            ),
                            html.Span(
                                price_str,
                                style={
                                    "color": price_color,
                                    "fontSize": "0.85rem",
                                    "width": "20%",
                                    "display": "inline-block",
                                },
                            ),
                            html.Span(
                                str(opt_count),
                                style={
                                    "color": TEXT_SECONDARY,
                                    "fontSize": "0.85rem",
                                    "width": "15%",
                                    "display": "inline-block",
                                },
                            ),
                            html.Span(
                                age,
                                style={
                                    "color": age_color,
                                    "fontSize": "0.75rem",
                                    "width": "25%",
                                    "display": "inline-block",
                                },
                            ),
                        ],
                        style={
                            "padding": "0.5rem 0",
                            "borderBottom": f"1px solid {BORDER}",
                            "display": "flex",
                            "alignItems": "center",
                        },
                    )
                )

            footer = html.Div(
                [
                    html.Span(f"Last price sync: {sync_age}", style={"color": TEXT_SECONDARY, "fontSize": "0.75rem"}),
                ],
                style={"marginTop": "0.5rem"},
            )

            return html.Div([header] + rows + [footer], style={"width": "100%"})

        except Exception as e:
            return html.Small(f"Error: {e}", style={"color": ACCENT_LOSS})


def _format_age(ts_str: str) -> str:
    """Format timestamp as human-readable age."""
    try:
        from datetime import datetime

        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
        diff = now - ts
        hours = int(diff.total_seconds() / 3600)
        if hours < 1:
            return "just now"
        if hours == 1:
            return "1h ago"
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return "unknown"


def _get_age_hours(ts_str: str) -> int:
    """Get age in hours from timestamp."""
    try:
        from datetime import datetime

        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
        diff = now - ts
        return int(diff.total_seconds() / 3600)
    except Exception:
        return 999
