// Written for KAMANU gate E8: release_post_dominates, positive. Every acquire is released.

interface Mutex {
  acquire(): Promise<() => void>;
  runExclusive<T>(work: () => Promise<T>): Promise<T>;
}

export async function reserve(lock: Mutex, other: Mutex, tool: any, flag: boolean): Promise<unknown> {
  const release = await lock.acquire();
  try {
    return await tool.call(flag);
  } finally {
    release();
  }
}

export async function reserveLater(lock: Mutex, other: Mutex, tool: any, flag: boolean): Promise<unknown> {
  return lock.runExclusive(async () => {
    return await tool.call(flag);
  });
}
