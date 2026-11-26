// Written for KAMANU gate E8: status_before_retry, negative. payAgain refunds without asking.

export async function pay(gateway: any, order: string, amount: number): Promise<unknown> {
  try {
    return await gateway.charge(order, amount);
  } catch (err) {
    const state = await gateway.status(order);
    if (state === "settled") return state;
    return await gateway.charge(order, amount);
  }
}

export async function payAgain(gateway: any, order: string, amount: number): Promise<unknown> {
  try {
    return await gateway.charge(order, amount);
  } catch (err) {
    await gateway.refund(order, amount);
    return null;
  }
}
