// Written for KAMANU gate E8: await_has_timeout, positive. Every wait has a limit.

const PATIENCE_MS = 25;

function deadline(ms: number): Promise<never> {
  return new Promise((_, reject) => setTimeout(() => reject(new Error("timed out")), ms));
}

export async function fetchQuote(tool: any, approver: any, key: string): Promise<unknown> {
  return await tool.call(key, { signal: AbortSignal.timeout(PATIENCE_MS) });
}

export async function approve(tool: any, approver: any, key: string): Promise<unknown> {
  return await Promise.race([approver.decide(key), deadline(PATIENCE_MS)]);
}
