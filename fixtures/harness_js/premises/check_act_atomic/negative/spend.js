// Written for KAMANU gate E8: check_act_atomic, negative. spendChecked reads, then writes.

export async function spend(ledger, lock, order, amount, cap) {
  const total = await ledger.incrBy(order, amount);
  if (total > cap) {
    await ledger.decrBy(order, amount);
    return false;
  }
  return true;
}

export async function spendChecked(ledger, lock, order, amount, cap) {
  const used = await ledger.get(order);
  if (used + amount > cap) {
    return false;
  }
  await ledger.set(order, used + amount);
  return true;
}
