// Written for KAMANU gate E8: release_post_dominates, negative. reserveFast leaks on a failure.

interface Mutex {
  acquire(): Promise<() => void>;
}

export async function reserve(lock: Mutex, other: Mutex, tool: any, flag: boolean): Promise<unknown> {
  const release = await lock.acquire();
  try {
    return await tool.call(flag);
  } finally {
    release();
  }
}

export async function reserveFast(lock: Mutex, other: Mutex, tool: any, flag: boolean): Promise<unknown> {
  const release = await lock.acquire();
  const answer = await tool.call(flag);
  release();
  return answer;
}
