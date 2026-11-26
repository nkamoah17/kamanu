"""Spend limit: the check reads the answer of one INCRBY of a Redis server every worker shares.

Written for KAMANU task T5. The construct is redis_increment.
"""
import os

import redis

LIMIT = 100

counter = redis.Redis(host="127.0.0.1", port=int(os.environ["SPEND_REDIS_PORT"]))


def spend(order, amount):
    total = counter.incrby(order, amount)
    if total > LIMIT:
        return False
    return True
