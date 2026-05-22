"""
config.py — centralised settings loaded from .env
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv
from dataclasses import dataclass, field
from typing import Optional

load_dotenv()


@dataclass
class Settings:
    # ── Schwab ──────────────────────────────────────────────────────────
    schwab_app_key:    str = field(default_factory=lambda: os.getenv("SCHWAB_APP_KEY", ""))
    schwab_app_secret: str = field(default_factory=lambda: os.getenv("SCHWAB_APP_SECRET", ""))
    schwab_callback:   str = field(default_factory=lambda: os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1"))

    # ── Teller ──────────────────────────────────────────────────────────
    teller_token:  str = field(default_factory=lambda: os.getenv("TELLER_COF_TOKEN", ""))
    teller_cert:   str = field(default_factory=lambda: os.getenv("TELLER_CERT", ""))
    teller_key:    str = field(default_factory=lambda: os.getenv("TELLER_KEY", ""))
    teller_app_id: str = field(default_factory=lambda: os.getenv("TELLER_APP_ID", ""))

    # ── Email (SMTP / Gmail) ─────────────────────────────────────────────
    smtp_host:     str = field(default_factory=lambda: os.getenv("SMTP_HOST", "smtp.gmail.com"))
    smtp_port:     int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user:     str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    alert_email_to: str = field(default_factory=lambda: os.getenv("ALERT_EMAIL_TO", ""))

    # ── iOS Push (APNs via ntfy.sh — easiest no-cert approach) ──────────
    # Use https://ntfy.sh — install the ntfy iOS app, subscribe to your topic
    ntfy_topic: str = field(default_factory=lambda: os.getenv("NTFY_TOPIC", ""))

    # ── Data storage ────────────────────────────────────────────────────
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "./data")))

    # ── Automation rules ────────────────────────────────────────────────
    # Minimum cash to keep in each bank account before sweeping to brokerage
    min_cash_buffer:      float = field(default_factory=lambda: float(os.getenv("MIN_CASH_BUFFER", "2000")))
    low_balance_alert:    float = field(default_factory=lambda: float(os.getenv("LOW_BALANCE_THRESHOLD", "500")))
    large_debit_alert:    float = field(default_factory=lambda: float(os.getenv("LARGE_DEBIT_THRESHOLD", "200")))

    # Daily sync time (24h HH:MM)
    sync_time: str = field(default_factory=lambda: os.getenv("SYNC_TIME", "07:00"))

    # Default sweep target symbol (e.g. SNSXX = Schwab money market, or SPY)
    sweep_symbol: str = field(default_factory=lambda: os.getenv("SWEEP_SYMBOL", "SNSXX"))

    risk_state_path: str = field(default_factory=lambda: os.getenv("RISK_STATE_PATH", "data/risk_state.json"))
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    deepseek_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))

    def teller_cert_tuple(self):
        c = str(Path(self.teller_cert).expanduser()) if self.teller_cert else None
        k = str(Path(self.teller_key).expanduser())  if self.teller_key  else None
        if c and k and Path(c).exists() and Path(k).exists():
            return (c, k)
        return None

    def is_configured(self) -> dict:
        """Return which integrations are ready."""
        # Teller can use .env or data/teller_tokens.json
        teller_ok = bool(self.teller_token and self.teller_cert_tuple())
        if not teller_ok:
            tokens_path = self.data_dir / "teller_tokens.json"
            if tokens_path.exists():
                try:
                    if json.loads(tokens_path.read_text()):
                        teller_ok = bool(self.teller_cert_tuple())
                except Exception:
                    pass
        return {
            "schwab": bool(self.schwab_app_key and self.schwab_app_secret),
            "teller": teller_ok,
            "email":  bool(self.smtp_user and self.smtp_password and self.alert_email_to),
            "push":   bool(self.ntfy_topic),
        }


settings = Settings()

# Ensure data dirs exist
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "balances.csv").touch(exist_ok=True)
(settings.data_dir / "transactions.csv").touch(exist_ok=True)
