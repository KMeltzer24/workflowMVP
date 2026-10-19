"""Financial-data tools (yfinance-backed)."""

from __future__ import annotations

from typing import Any, Dict

from workflowmvp._finance_symbols import resolve_finance_symbol_hint

from ._base import P, Tool, _BaseToolRegistry


class FinanceToolsMixin(_BaseToolRegistry):
    """Financial-market lookup tools exposed through the registry."""

    def _register_finance_tools(self) -> None:
        self.register_tool(Tool(
            name="fetch_stock_price",
            description=(
                "Fetch the current or recent price of a stock or index using its ticker symbol "
                "(e.g. ^GSPC for S&P 500 index level in points, SPY for the ETF, AAPL for Apple). "
                "Returns price, currency, and metadata."
            ),
            function=self._fetch_stock_price,
            category="finance",
            side_effects=("network",),
            parameters={
                "ticker": P("Ticker symbol (e.g. '^GSPC', 'AAPL', 'BTC-USD')", required=True),
                "period": P("Data period: '1d', '5d', '1mo', etc. (default: '1d')"),
            },
        ))

    def _fetch_stock_price(
        self, ticker: str, period: str = "1d"
    ) -> Dict[str, Any]:
        """Fetch stock/index price via yfinance (no scraping, no rate-limits)."""
        ticker = resolve_finance_symbol_hint(ticker) or ticker
        try:
            import yfinance as yf
        except ImportError:
            return {
                "success": False,
                "error": "yfinance is not installed. Run: pip3 install yfinance",
            }
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period)
            if hist.empty:
                return {
                    "success": False,
                    "error": f"No data returned for ticker '{ticker}'",
                }
            latest = hist["Close"].iloc[-1]
            info = t.fast_info
            currency = getattr(info, "currency", "USD") or "USD"
            name = getattr(info, "long_name", ticker) or ticker
            price = round(float(latest), 2)
            return {
                "success": True,
                "result": price,
                "ticker": ticker,
                "name": name,
                "price": price,
                "currency": currency,
                "period": period,
                "meta": {
                    "ticker": ticker,
                    "name": name,
                    "currency": currency,
                    "period": period,
                },
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
