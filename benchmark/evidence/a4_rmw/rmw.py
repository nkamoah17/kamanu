# kernel: P/req/atomic=F, Atomic FALSE. GET and SET are two commands, and any client may run between them.
# source: https://redis.io/docs/latest/develop/using-commands/transactions/#optimistic-locking-using-check-and-set (this read and write, without the WATCH)


def admit(client, key, amount, cap):
    spent = int(client.get(key) or 0)
    if spent + amount > cap:
        return False
    client.set(key, spent + amount)
    return True
