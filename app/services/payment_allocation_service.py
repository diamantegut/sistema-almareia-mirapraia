def _parse_amount(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _is_cash_method(method_name):
    normalized = str(method_name or "").strip().lower()
    return "dinheiro" in normalized


def allocate_payments_with_change(payments, amount_due):
    due = max(0.0, _parse_amount(amount_due))
    normalized = []
    non_cash_total = 0.0
    cash_count = 0

    for payment in payments or []:
        method_name = str(payment.get("method") or payment.get("name") or "").strip()
        amount_input = _parse_amount(payment.get("amount"))
        if not method_name or amount_input <= 0:
            continue
        is_cash = _is_cash_method(method_name)
        if is_cash:
            cash_count += 1
        else:
            non_cash_total += amount_input
        normalized.append({
            "id": payment.get("id"),
            "method": method_name,
            "amount_input": amount_input,
            "is_cash": is_cash,
        })

    if not normalized:
        raise ValueError("Nenhum pagamento válido informado.")

    if non_cash_total > due + 0.05:
        raise ValueError(
            f"Valor em meios não-dinheiro (R$ {non_cash_total:.2f}) excede o valor devido (R$ {due:.2f})."
        )

    total_input = sum(p["amount_input"] for p in normalized)
    if cash_count == 0 and total_input > due + 0.05:
        raise ValueError(
            f"Sobrepagamento sem dinheiro não permitido. Total informado: R$ {total_input:.2f} | Devido: R$ {due:.2f}."
        )

    due_left = due
    total_applied = 0.0
    total_received = 0.0
    total_change = 0.0
    allocated = []

    for payment in normalized:
        amount_input = payment["amount_input"]
        amount_applied = min(amount_input, max(0.0, due_left))
        change_amount = 0.0

        if payment["is_cash"] and amount_input > amount_applied:
            change_amount = amount_input - amount_applied

        due_left = max(0.0, due_left - amount_applied)
        total_applied += amount_applied
        total_received += amount_input
        total_change += change_amount

        allocated.append({
            "id": payment.get("id"),
            "method": payment["method"],
            "amount_input": round(amount_input, 2),
            "amount_applied": round(amount_applied, 2),
            "change_amount": round(change_amount, 2),
            "is_cash": payment["is_cash"],
        })

    if total_applied + 0.05 < due:
        missing = due - total_applied
        raise ValueError(f"Pagamento insuficiente. Falta R$ {missing:.2f}.")

    return {
        "amount_due": round(due, 2),
        "total_received": round(total_received, 2),
        "total_applied": round(total_applied, 2),
        "total_change": round(total_change, 2),
        "payments": allocated,
    }
