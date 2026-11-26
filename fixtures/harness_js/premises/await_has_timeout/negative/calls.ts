// Written for KAMANU gate E8: await_has_timeout, negative. approve waits on the approver for good.

const PATIENCE_MS = 25;

export async function fetchQuote(tool: any, approver: any, key: string): Promise<unknown> {
  return await tool.call(key, { signal: AbortSignal.timeout(PATIENCE_MS) });
}

export async function approve(tool: any, approver: any, key: string): Promise<unknown> {
  return await approver.decide(key);
}
