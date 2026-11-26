# Sync GET then SET on a shared store (redis-like). Any other process may run between them.
def admit(budget, key, amount, cap):
    spent = budget.get(key) or 0
    if spent + amount > cap:
        return False
    budget.set(key, spent + amount)
    return True
