"""Decision policy thresholds. Bump POLICY_VERSION whenever any value here changes."""
from decimal import Decimal

POLICY_VERSION = "v2"
LEDGER_CURRENCY = "INR"

MONEY_TOLERANCE = Decimal("0.01")          # rounding tolerance for arithmetic checks
PRICE_VARIANCE_PCT = Decimal("0.02")       # 2% of PO line value at PO price...
PRICE_VARIANCE_CAP = Decimal("500.00")     # ...capped at ₹500 per line
TAX_RATE_TOLERANCE_PP = Decimal("0.005")   # ±0.5 percentage points

PO_INFER_MIN_SCORE = 0.80
PO_INFER_MIN_LEAD = 0.15

DUPLICATE_DATE_WINDOW_DAYS = 14

# Invoice line -> PO line. An exact SKU match decides; otherwise description similarity must reach the
# minimum, and a runner-up within the tie margin means the line is ambiguous (HOLD, never a guess).
LINE_MATCH_MIN_SIMILARITY = 0.80
LINE_TIE_MARGIN = 0.05
