/** A full-thread screenshot temporarily hydrates and mounts every row. */
type Prepare = () => Promise<() => void>;
const preparers = new Set<Prepare>();

export function registerVirtualThreadCapture(prepare: Prepare) {
  preparers.add(prepare);
  return () => {
    preparers.delete(prepare);
  };
}

export async function prepareVirtualThreadCapture(): Promise<() => void> {
  const releases: (() => void)[] = [];
  try {
    for (const prepare of preparers) releases.push(await prepare());
    return () => {
      for (const release of releases) release();
    };
  } catch (error) {
    for (const release of releases) release();
    throw error;
  }
}
