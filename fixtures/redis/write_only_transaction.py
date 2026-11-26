# Atomic FALSE. MULTI covers the write and not the read, and a read inside MULTI gives no value to branch on.
# source: https://redis.io/docs/latest/develop/using-commands/transactions/#usage (commands are queued until EXEC)
# source: https://redis.io/tutorials/howtos/ratelimiting/ (you cannot read a value inside the batch and branch on it)


def admit(client, key, amount, cap):
    spent = int(client.get(key) or 0)
    if spent + amount > cap:
        return False
    with client.pipeline() as pipe:
        pipe.set(key, spent + amount)
        pipe.expire(key, 60)
        pipe.execute()
    return True
