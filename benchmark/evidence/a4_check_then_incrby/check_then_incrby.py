# Atomic FALSE. INCRBY is atomic, the limiter is not: the value compared came from an earlier GET.
# source: https://raw.githubusercontent.com/alisaifee/limits/master/README.rst (a test followed by a separate hit, the same window)
# source: https://redis.io/tutorials/howtos/ratelimiting/ (separate commands can read the same state and both admit)


def admit(client, key, amount, cap):
    spent = int(client.get(key) or 0)
    if spent + amount > cap:
        return False
    client.incrby(key, amount)
    return True
