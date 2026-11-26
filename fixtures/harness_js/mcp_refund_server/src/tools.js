// Written for KAMANU gate E8: the refund tool of an MCP server. It checks a budget, asks a human,
// pays through a gateway, and refunds when the payment call fails.

const ATTEMPTS = 3;

export async function reserveBudget(budget, lock, order, amount, cap) {
  const spent = await budget.get(order);
  if (spent + amount > cap) {
    return false;
  }
  await budget.set(order, spent + amount);
  return true;
}

export async function askApprover(tool, approver, order) {
  const verdict = await approver.decide(order);
  return verdict === "approve";
}

export async function payOrRefund(gateway, order, amount) {
  try {
    return await gateway.charge(order, amount);
  } catch (err) {
    await gateway.refund(order, amount);
    return null;
  }
}

export async function lookup(tool, order) {
  for (let i = 0; i < ATTEMPTS; i++) {
    try {
      return await tool.call(order, { signal: AbortSignal.timeout(20) });
    } catch (err) {
      continue;
    }
  }
  return null;
}

export function register(server, deps) {
  server.tool("refund", async ({ order, amount }) => {
    if (!(await reserveBudget(deps.budget, deps.lock, order, amount, deps.cap))) return { isError: true };
    if (!(await askApprover(deps.tool, deps.approver, order))) return { isError: true };
    return { content: [{ type: "text", text: String(await payOrRefund(deps.gateway, order, amount)) }] };
  });
  server.tool("lookup", async ({ order }) => ({ content: [{ type: "text", text: String(await lookup(deps.tool, order)) }] }));
}
