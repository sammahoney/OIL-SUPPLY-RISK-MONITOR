def risk_score(shipping_stress, price):
    """
    shipping_stress: 0-100 score from shipping_stress.shipping_stress()
                      (GDELT news signal + optional freight/Suez inputs)
    price: latest oil price from oil.get_oil_price()

    Same weighting and graceful-degradation logic as before — just fed by
    the new shipping_stress source instead of raw AIS vessel counts.
    """

    # ---------------------------
    # 1. HANDLE MISSING DATA SAFELY
    # ---------------------------

    # shipping_stress arrives already as a 0-100 stress score, no
    # conversion needed (the old code inverted a vessel count here).
    shipping_score = shipping_stress if shipping_stress is not None else None

    if price is None:
        price_score = None
    else:
        price_score = min(100, price / 1.2)

    # ---------------------------
    # 2. DATA QUALITY CHECK
    # ---------------------------

    valid_signals = 0
    score_sum = 0

    if shipping_score is not None:
        score_sum += 0.6 * shipping_score
        valid_signals += 1

    if price_score is not None:
        score_sum += 0.4 * price_score
        valid_signals += 1

    # ---------------------------
    # 3. IF NO DATA -> SAFE OUTPUT
    # ---------------------------

    if valid_signals == 0:
        return None

    # ---------------------------
    # 4. NORMALIZE IF PARTIAL DATA
    # ---------------------------

    if valid_signals == 2:
        weight_used = 0.6 + 0.4
    elif shipping_score is not None:
        weight_used = 0.6
    else:
        weight_used = 0.4

    return score_sum / weight_used
