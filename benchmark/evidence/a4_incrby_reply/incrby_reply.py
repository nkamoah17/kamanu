# Atomic TRUE. The value compared is the reply of the write, so no client can run between them.
# source: https://redis.io/docs/latest/commands/incr/#pattern-rate-limiter (the check is on the value the increment returned)


def admit(client, key, amount, cap):
    total = client.incrby(key, amount)
    if total > cap:
        client.decrby(key, amount)
        return False
    return True
