# In-process dict counter under a thread pool: read then write, no lock.
from concurrent.futures import ThreadPoolExecutor
spend = {}

def admit(key, amount, cap):
    cur = spend[key]
    if cur + amount > cap:
        return False
    spend[key] = cur + amount
    return True

def serve(reqs):
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(lambda r: admit(*r), reqs))
