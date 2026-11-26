def refund_unknown(tools, payments, k):
    try:
        tools.charge(k)
    except Exception:
        st = tools.status(k)
        if st == "absent":
            tools.refund(k)

def pay(gw, k):
    try:
        gw.charge(k)
    except Exception:
        gw.refund(k)                      # refund without asking: receiver not named tool/gateway
