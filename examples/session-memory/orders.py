"""A small idempotency example for the memory walkthrough."""


def create_order(order_id: str, seen: set[str]) -> bool:
    """Return True only for the first occurrence of an order ID."""
    if order_id in seen:
        return False
    seen.add(order_id)
    return True
