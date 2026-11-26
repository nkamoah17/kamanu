# Atomic TRUE. EXEC aborts if the key changed after WATCH, so the write commits only on what was read.
# source: https://redis.io/docs/latest/develop/using-commands/transactions/#optimistic-locking-using-check-and-set
# source: https://redis.io/docs/latest/develop/clients/redis-py/transpipe/ (watch, immediate mode, multi, WatchError)
import redis


def admit(client, key, amount, cap):
    with client.pipeline() as pipe:
        while True:
            try:
                pipe.watch(key)
                spent = int(pipe.get(key) or 0)
                if spent + amount > cap:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.set(key, spent + amount)
                pipe.execute()
                return True
            except redis.WatchError:
                continue
