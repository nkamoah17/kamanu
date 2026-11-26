def fetch(tools, k):
    for _ in range(3):
        try:
            return tools.call(k)
        except Exception:
            pass

def charge(stripe, k):
    while True:                           # unbounded retry around a payment call not named tool
        try:
            return stripe.Charge.create(k)
        except Exception:
            continue
