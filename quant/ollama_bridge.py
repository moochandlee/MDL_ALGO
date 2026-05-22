import asyncio
from typing import Optional
from quant.engine import run_ma_crossover
from config import settings

# OpenAI SDK for DeepSeek
try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

# OpenBB is optional — only used for FRED macro data
try:
    from openbb import obb
    _OPENBB_AVAILABLE = True
except ImportError:
    _OPENBB_AVAILABLE = False


class QuantAgent:
    def __init__(self, model: Optional[str] = None):
        if not settings.deepseek_api_key or not _OPENAI_AVAILABLE:
            raise RuntimeError(
                "DeepSeek API key not configured. Set DEEPSEEK_API_KEY in your .env "
                "and install openai: pip install openai"
            )
        self._ds_client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com",
        )
        self._ds_model = model or settings.deepseek_model

    async def check_connectivity(self) -> tuple[bool, str]:
        """Check if the DeepSeek API is reachable."""
        loop = asyncio.get_event_loop()
        try:
            resp = await loop.run_in_executor(
                None, lambda: self._ds_client.models.list()
            )
            return True, ""
        except Exception as e:
            return False, (
                f"**Cannot reach DeepSeek API.**\n\n"
                f"Check that `DEEPSEEK_API_KEY` in your `.env` is valid.\n"
                f"Error: {e}"
            )

    async def chat(self, user_input: str) -> dict:
        """
        The main interface for the Quant Agent.
        Returns {"text": str, "strategy": dict|None}.
        """
        user_input_lower = user_input.lower()

        try:
            if any(word in user_input_lower for word in ["macro", "gdp", "cpi", "fed", "fred"]):
                text = await self._get_macro_data(user_input)
                return {"text": text, "strategy": None}

            if "backtest" in user_input_lower:
                text = self._trigger_backtest(user_input_lower)
                return {"text": text, "strategy": None}

            ok, msg = await self.check_connectivity()
            if not ok:
                return {"text": msg, "strategy": None}

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self._llm_chat, user_input)
            strategy = self._extract_strategy(response)
            return {"text": response, "strategy": strategy}

        except Exception as e:
            return {"text": f"**Error in Quant Agent:** {str(e)}", "strategy": None}

    def _llm_chat(self, user_input: str) -> str:
        """Synchronous DeepSeek call, meant to be run in an executor."""
        response = self._ds_client.chat.completions.create(
            model=self._ds_model,
            messages=[
                {'role': 'system', 'content': self._system_prompt()},
                {'role': 'user', 'content': user_input},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content

    def _system_prompt(self) -> str:
        return (
            'You are a Lead Quant Systems Architect with access to OpenBB (macro data) '
            'and vectorbt (backtesting).\n\n'
            'When the user asks you to design or describe a trading strategy, include '
            'a structured machine-readable block at the end of your response using the '
            'following format:\n'
            '<<<STRATEGY>>>\n'
            '{\n'
            '  "name": "...",\n'
            '  "ticker": "SYMBOL",\n'
            '  "type": "macd",\n'
            '  "parameters": {\n'
            '    "fast_window": 12,\n'
            '    "slow_window": 26,\n'
            '    "signal_window": 9\n'
            '  },\n'
            '  "allocation_usd": 10000,\n'
            '  "stop_loss_pct": 5,\n'
            '  "reinvest_profits": true\n'
            '}\n'
            '<<<ENDSTRATEGY>>>\n\n'
            'Supported strategy types:\n'
            '  - macd:       MACD crossover (fast_window, slow_window, signal_window)\n'
            '  - ma_crossover: MA crossover (short_window, long_window)\n'
            '  - custom:     Arbitrary pandas expression (entry_condition, exit_condition)\n'
            '    For custom, the expressions use `close` as the price series, e.g.:\n'
            '      "close > close.rolling(20).mean()"\n'
            '      "close < close.shift(1) * 0.98"\n'
            '      "close.rolling(5).mean() > close.rolling(20).mean()"\n'
            '    For strategies that need synthetic data (e.g. sentiment, volatility,\n'
            '    additional indicators), include a `setup_code` field with Python code\n'
            '    that will execute before entry/exit conditions. The namespace already\n'
            '    has `close` (price Series), `pd` (pandas), and `np` (numpy). Example:\n'
            '      "setup_code": "import numpy as np; sentiment = pd.Series(np.random.uniform(-1, 1, len(close)), index=close.index)"\n'
            'Include the ticker symbol, relevant parameters for the strategy type, '
            'and sensible defaults for allocation / stop-loss / reinvest.\n'
            'Keep responses concise and actionable.'
        )

    @staticmethod
    def _extract_strategy(text: str) -> Optional[dict]:
        """Parse the <<<STRATEGY>>> block from an LLM response into a dict."""
        import json, re
        m = re.search(r'<<<STRATEGY>>>(.*?)<<<ENDSTRATEGY>>>', text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(1).strip())
        except (json.JSONDecodeError, Exception):
            return None

    async def _get_macro_data(self, query: str) -> str:
        """Fetch real-world macro data using OpenBB."""
        if not _OPENBB_AVAILABLE:
            return ("**OpenBB is not installed.**\n"
                    "Install with: `pip install openbb`\n"
                    "Then set your FRED API key: `obb.user.credentials.fred_api_key = 'YOUR_KEY'`")

        # Mapping common terms to FRED symbols
        mapping = {"gdp": "GDP", "cpi": "CPIAUCSL", "rates": "FEDFUNDS", "unemployment": "UNRATE"}

        target_symbol = "GDP"  # Default
        for key, sym in mapping.items():
            if key in query.lower():
                target_symbol = sym
                break

        try:
            # OpenBB v4 call — run in executor since it does HTTP I/O
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, lambda: obb.economy.fred_series(symbol=target_symbol))
            df = res.to_df()

            last_val = df.iloc[-1].values[0]
            last_date = df.index[-1].strftime('%Y-%m-%d')

            return (f"**OpenBB Macro Report ({target_symbol})**\n\n"
                    f"Latest Value: {last_val}\n"
                    f"Date: {last_date}\n"
                    f"Trend: The last 3 readings were {df.tail(3).values.flatten().tolist()}")
        except Exception as e:
            error_msg = str(e)
            if "missing credentials" in error_msg.lower() or "fred" in error_msg.lower():
                return ("**FRED API credentials not configured.**\n\n"
                        "To fix this:\n"
                        "1. Get a free API key at https://fred.stlouisfed.org/docs/api/api_key.html\n"
                        "2. Add to your .env: `OPENBB_FRED_API_KEY=your_key_here`\n"
                        "3. Restart the app.")
            return f"**OpenBB Error:** {error_msg}"

    def _trigger_backtest(self, query: str) -> str:
        """Extracts symbols and triggers the vectorbt engine."""
        import re
        # Find all uppercase words that look like tickers (1-5 letters)
        # Search the original (non-lowered) query for uppercase symbols,
        # but also check the lowered query for inline mentions
        candidates = re.findall(r'\b([A-Za-z]{1,5})\b', query)

        # Filter out common English words that aren't tickers
        stop_words = {
            "a", "an", "the", "is", "it", "in", "on", "to", "for", "of",
            "and", "or", "can", "you", "my", "me", "do", "run", "use",
            "using", "with", "from", "this", "that", "how", "what",
            "backtest", "test", "stock", "ma", "strategy", "moving",
            "average", "i", "please", "would", "could", "should",
        }

        symbol = "AAPL"  # Default fallback
        for word in candidates:
            if word.lower() not in stop_words:
                symbol = word.upper()
                break

        try:
            return_pct = run_ma_crossover(symbol, 20, 50)

            return (f"**Backtest Complete: {symbol}**\n"
                    f"Strategy: 20/50 MA Crossover\n"
                    f"Total Return: {return_pct:.2f}%")
        except Exception as e:
            return f"**Backtest Error ({symbol}):** {str(e)}"
