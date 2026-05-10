import os
from dotenv import load_dotenv
import schwabdev

# =========================================================
# Load environment variables from .env
# =========================================================
load_dotenv()

APP_KEY = os.getenv("app_key")
APP_SECRET = os.getenv("app_secret")
CALLBACK_URL = os.getenv("callback_url")

# =========================================================
# Create Schwab client
# =========================================================
client = schwabdev.Client(
    APP_KEY,
    APP_SECRET,
    CALLBACK_URL
)

print("Connected to Schwab API")

# =========================================================
# Get linked accounts
# =========================================================
accounts_resp = client.linked_accounts()

if not accounts_resp.ok:
    print("Failed to retrieve linked accounts")
    print(accounts_resp.text)
    exit()

accounts = accounts_resp.json()

print("\nLinked Accounts:")
print(accounts)

# Use first linked account
account_hash = accounts[0]["hashValue"]

print(f"\nUsing account hash: {account_hash}")

# =========================================================
# Get account balances and positions
# =========================================================
details_resp = client.account_details(
    account_hash,
    fields="positions"
)

if not details_resp.ok:
    print("Failed to retrieve account details")
    print(details_resp.text)
    exit()

account_data = details_resp.json()

balances = account_data["securitiesAccount"]["currentBalances"]

print("\n===== ACCOUNT BALANCES =====")
print(f"Cash Balance: ${balances.get('cashBalance', 0):,.2f}")
print(f"Buying Power: ${balances.get('buyingPower', 0):,.2f}")
print(f"Liquidation Value: ${balances.get('liquidationValue', 0):,.2f}")

# =========================================================
# Print positions
# =========================================================
positions = account_data["securitiesAccount"].get("positions", [])

print("\n===== POSITIONS =====")

if not positions:
    print("No positions found")
else:
    for pos in positions:
        instrument = pos.get("instrument", {})
        symbol = instrument.get("symbol", "UNKNOWN")

        qty = pos.get("longQuantity", 0)
        market_value = pos.get("marketValue", 0)

        print(f"{symbol} | Qty: {qty} | Value: ${market_value:,.2f}")

# =========================================================
# Get stock quotes
# =========================================================
symbols = ["AAPL", "AMD", "NVDA"]

quotes_resp = client.quotes(symbols)

if not quotes_resp.ok:
    print("Failed to retrieve quotes")
    print(quotes_resp.text)
    exit()

quotes = quotes_resp.json()

print("\n===== STOCK QUOTES =====")

for symbol, data in quotes.items():

    quote = data.get("quote", {})

    last_price = quote.get("lastPrice")
    bid = quote.get("bidPrice")
    ask = quote.get("askPrice")

    print(f"{symbol}")
    print(f"  Last: ${last_price}")
    print(f"  Bid : ${bid}")
    print(f"  Ask : ${ask}")

# =========================================================
# Example order
# =========================================================
# BUY 1 share of AMD at LIMIT $1.00
# (Likely won't fill — safer for testing)
# =========================================================

# order = {
#     "orderType": "LIMIT",
#     "session": "NORMAL",
#     "duration": "DAY",
#     "orderStrategyType": "SINGLE",
#     "price": "4.00",
#     "orderLegCollection": [
#         {
#             "instruction": "BUY",
#             "quantity": 1,
#             "instrument": {
#                 "symbol": "NOK",
#                 "assetType": "EQUITY"
#             }
#         }
#     ]
# }

# =========================================================
# Preview order (SAFE)
# =========================================================
print("\n===== PREVIEW ORDER =====")

preview_resp = client.preview_order(account_hash, order)

print(f"Preview status code: {preview_resp.status_code}")

try:
    print(preview_resp.json())
except Exception:
    print(preview_resp.text)

# =========================================================
# LIVE ORDER (DISABLED)
# =========================================================
# Uncomment to place a REAL order
# =========================================================

"""
print("\n===== PLACING LIVE ORDER =====")

place_resp = client.place_order(account_hash, order)

print(f"Order response code: {place_resp.status_code}")

# Get order ID
order_id = place_resp.headers.get(
    "location",
    "/"
).split("/")[-1]

print(f"Order ID: {order_id}")

# Get order details
if order_id:
    details = client.order_details(
        account_hash,
        order_id
    )

    print(details.json())
"""

print("\nDone.")