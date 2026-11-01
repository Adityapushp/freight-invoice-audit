"""Pure pricing rules. Shared by the generator (to build invoices) and the auditor (to recompute expected charges).
All money uses Decimal with ROUND_HALF_UP to the cent, so expected charges are exactly reproducible."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from . import config as C

CENT = Decimal("0.01")

def D(x): return x if isinstance(x, Decimal) else Decimal(str(x))
def money(x): return D(x).quantize(CENT, ROUND_HALF_UP)

def tier_for(weight_lb):
    """Tier by billable weight; lower bound inclusive, upper exclusive (50 lb -> T2)."""
    for code, lo, hi in C.TIERS:
        if weight_lb >= lo and (hi is None or weight_lb < hi):
            return code
    raise ValueError(weight_lb)

def tier_index(code): return [t[0] for t in C.TIERS].index(code)

def dim_weight(length, width, height, pieces, divisor):
    """Dimensional weight (lb) = ceil(L*W*H*pieces / divisor)."""
    return int((D(length * width * height * pieces) / D(divisor)).to_integral_value(ROUND_CEILING))

def chargeable_weight(actual_lb, dim_wt):
    """Billable weight = max(ceil(actual), dim weight)."""
    return max(int(D(actual_lb).to_integral_value(ROUND_CEILING)), dim_wt)

def base_charge(weight_lb, rate_per_lb, min_charge):
    return money(max(D(min_charge), D(weight_lb) * D(rate_per_lb)))

def fuel_charge(base, fuel_rate):
    return money(D(base) * D(fuel_rate))
