// Written for KAMANU gate E8: retry_bounded, positive. Both retry loops are bounded.

const ATTEMPTS = 3;

export async function fetchWithRetry(tool, key) {
  for (let i = 0; i < ATTEMPTS; i++) {
    try {
      return await tool.call(key);
    } catch (err) {
      continue;
    }
  }
  return null;
}

export async function pushWithRetry(tool, key) {
  let tries = 0;
  while (tries < ATTEMPTS) {
    tries++;
    try {
      const answer = await tool.send(key);
      if (answer) return answer;
    } catch (err) {
      await new Promise((resolve) => setTimeout(resolve, 1));
    }
  }
  return null;
}
