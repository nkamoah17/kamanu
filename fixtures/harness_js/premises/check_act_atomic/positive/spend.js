// Written for KAMANU gate E8: check_act_atomic, positive. One atomic INCRBY answers each check.

export async function spend(ledger, lock, order, amount, cap) {
  const total = await ledger.incrBy(order, amount);
  if (total > cap) {
    await ledger.decrBy(order, amount);
    return false;
  }
  return true;
}

export async function countVisit(counter, lock, key, amount, cap) {
  return (await counter.incrBy(key, amount)) <= cap;
}
