"""
notifications.py — Email (SMTP) + iOS push via ntfy.sh
"""

import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from config import settings


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(subject: str, body_html: str, body_text: str = "") -> bool:
    if not settings.smtp_user or not settings.alert_email_to:
        print("[notify] Email not configured, skipping.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Finance Autopilot] {subject}"
    msg["From"]    = settings.smtp_user
    msg["To"]      = settings.alert_email_to

    if body_text:
        msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, settings.alert_email_to, msg.as_string())
        print(f"[notify] Email sent: {subject}")
        return True
    except Exception as e:
        print(f"[notify] Email error: {e}")
        return False


def _alert_email_html(title: str, items: list[dict]) -> str:
    rows = ""
    for item in items:
        color = {"warning": "#f59e0b", "danger": "#ef4444", "info": "#4fc3f7"}.get(item.get("level","info"), "#4fc3f7")
        rows += f"""
        <tr>
          <td style="padding:10px 16px;border-bottom:1px solid #1e2d4a;">
            <span style="color:{color};font-size:18px;">{"⚠️" if item.get("level")=="warning" else "🔔"}</span>
          </td>
          <td style="padding:10px 16px;border-bottom:1px solid #1e2d4a;color:#e2e8f0;">
            <strong>{item.get("title","")}</strong><br>
            <span style="color:#8899aa;font-size:13px;">{item.get("body","")}</span>
          </td>
        </tr>"""

    return f"""
    <html><body style="background:#0a0f1e;font-family:-apple-system,sans-serif;margin:0;padding:20px;">
      <div style="max-width:560px;margin:auto;background:#0d1526;border-radius:12px;
                  border:1px solid #1e2d4a;overflow:hidden;">
        <div style="background:#0a0f1e;padding:20px 24px;border-bottom:1px solid #1e2d4a;">
          <h2 style="margin:0;color:#4fc3f7;font-size:18px;">💹 Finance Autopilot</h2>
          <p style="margin:4px 0 0;color:#8899aa;font-size:13px;">{title}</p>
        </div>
        <table style="width:100%;border-collapse:collapse;">{rows}</table>
        <div style="padding:16px 24px;background:#060c1a;">
          <p style="margin:0;color:#4a5568;font-size:12px;">
            {datetime.now().strftime("%B %d, %Y at %I:%M %p")} · Finance Autopilot
          </p>
        </div>
      </div>
    </body></html>"""


# ── iOS Push via ntfy.sh ──────────────────────────────────────────────────────
# User installs the free ntfy app on iPhone, subscribes to their private topic

def send_push(title: str, message: str, priority: str = "default", tags: list = None) -> bool:
    """
    Send push notification via ntfy.sh.

    Setup:
      1. Install the ntfy app on iPhone (free, App Store)
      2. Subscribe to a private topic like "finance-autopilot-abc123"
      3. Set NTFY_TOPIC=finance-autopilot-abc123 in .env
      4. Optionally self-host ntfy for full privacy

    priority: min | low | default | high | urgent
    tags: emoji/icon tags, e.g. ["warning"] or ["moneybag"]
    """
    if not settings.ntfy_topic:
        print("[notify] ntfy topic not configured, skipping push.")
        return False

    try:
        resp = requests.post(
            f"https://ntfy.sh/{settings.ntfy_topic}",
            data=message.encode("utf-8"),
            headers={
                "Title":    title,
                "Priority": priority,
                "Tags":     ",".join(tags or []),
            },
            timeout=10,
        )
        print(f"[notify] Push sent ({resp.status_code}): {title}")
        return resp.ok
    except Exception as e:
        print(f"[notify] Push error: {e}")
        return False


# ── Composed alert senders ───────────────────────────────────────────────────

def notify_low_balance(account_name: str, institution: str, balance: float):
    title   = f"Low Balance: {institution} · {account_name}"
    message = f"Available balance is ${balance:,.2f} — below your ${settings.low_balance_alert:,.0f} threshold."
    send_push(title, message, priority="high", tags=["warning", "bank"])
    send_email(title, _alert_email_html(title, [{
        "title":   title,
        "body":    message,
        "level":   "danger",
    }]))


def notify_large_debit(description: str, amount: float, account_name: str):
    title   = f"Large Debit: ${amount:,.2f}"
    message = f"{description} on {account_name}"
    send_push(title, message, priority="high", tags=["warning", "credit_card"])
    send_email(title, _alert_email_html(title, [{
        "title":   title,
        "body":    message,
        "level":   "warning",
    }]))


def notify_sweep_recommendation(symbol: str, shares: int, cost: float, reason: str):
    title   = f"Sweep Recommendation: Buy {shares}× {symbol}"
    message = f"${cost:,.2f} available to invest. {reason}\n\nOpen Finance Autopilot to approve."
    send_push(title, message, priority="default", tags=["chart_increasing", "moneybag"])
    send_email(title, _alert_email_html(title, [{
        "title":   f"Buy {shares} shares of {symbol} (~${cost:,.2f})",
        "body":    reason + " — Open the app to confirm.",
        "level":   "info",
    }]))


def notify_order_filled(symbol: str, shares: int, side: str):
    title   = f"Order Placed: {side} {shares}× {symbol}"
    message = f"Your {side.lower()} order for {shares} shares of {symbol} was submitted."
    send_push(title, message, priority="default", tags=["white_check_mark"])


def notify_daily_summary(accounts_count: int, new_txns: int, brokerage_value: float):
    title   = "Daily Finance Summary"
    message = (
        f"Morning update: {accounts_count} accounts synced, "
        f"{new_txns} new transactions. "
        f"Brokerage value: ${brokerage_value:,.2f}"
    )
    send_push(title, message, priority="low", tags=["sunny", "chart_with_upwards_trend"])
