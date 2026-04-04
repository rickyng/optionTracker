from datetime import datetime


def generate_text_report(strategies: list, account_name: str = "All Accounts") -> str:
    lines = [
        f"IBKR Options Report — {account_name}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
    ]
    if not strategies:
        lines.append("No open strategies found.")
        return "\n".join(lines)

    for s in strategies:
        lines.append(f"[{s.type.value.upper()}] {s.underlying} exp {s.expiry} ({s.account_name})")
        lines.append(f"  Breakeven: {s.breakeven_price:.2f}")
        lines.append(f"  Max Profit: ${s.max_profit:.2f}")
        loss_str = "UNLIMITED" if s.max_loss == float("inf") else f"${s.max_loss:.2f}"
        lines.append(f"  Max Loss: {loss_str}")
        lines.append(f"  Risk Level: {s.risk_level}")
        lines.append("")

    return "\n".join(lines)
