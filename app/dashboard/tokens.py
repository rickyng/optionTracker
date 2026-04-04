"""Centralized design tokens for the IBKR Options Analyzer dashboard.

All colors, typography, spacing, and component styles are defined here
to ensure visual consistency across all tabs and components.
"""

# ── Colors ────────────────────────────────────────────────────────────────────
BG_PRIMARY = "#0f0f1a"
BG_CARD = "#1a1a2e"
BG_CARD_HEADER = "#16213e"
BG_INPUT = "#16213e"
BG_ROW_ALT = "#141428"

TEXT_PRIMARY = "#e0e0e0"
TEXT_SECONDARY = "#8892b0"
TEXT_ACCENT = "#64ffda"

ACCENT_PROFIT = "#00e676"
ACCENT_LOSS = "#ff5252"
ACCENT_WARN = "#ffc107"
ACCENT_INFO = "#448aff"

BORDER = "#2a2a4a"

# Chart colors
CHART_BG = BG_PRIMARY
CHART_TEXT = TEXT_PRIMARY
CHART_COLORS = ["#64ffda", "#448aff", "#ff5252", "#ffc107", "#bb86fc", "#00e676"]

# ── Typography ────────────────────────────────────────────────────────────────
FONT_FAMILY = "'Inter', system-ui, -apple-system, sans-serif"

# ── Shared styles ─────────────────────────────────────────────────────────────
CARD_STYLE = {"color": "dark", "className": "shadow-sm h-100"}

PLOT_LAYOUT = {
    "paper_bgcolor": CHART_BG,
    "font_color": CHART_TEXT,
    "margin": {"t": 10, "b": 30, "l": 40, "r": 10},
}

STAT_CARD_BODY = {
    "className": "text-center py-3",
}

# ── Helper ────────────────────────────────────────────────────────────────────


def risk_badge_color(risk_level: str) -> str:
    """Return bootstrap badge color for a risk level."""
    return {
        "DEFINED": "success",
        "LOW": "info",
        "MEDIUM": "warning",
        "HIGH": "danger",
    }.get(risk_level, "secondary")
