// Written for KAMANU gate E8: retry_bounded, negative. pushWithRetry never gives up.

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
  while (true) {
    try {
      return await tool.send(key);
    } catch (err) {
      continue;
    }
  }
}
