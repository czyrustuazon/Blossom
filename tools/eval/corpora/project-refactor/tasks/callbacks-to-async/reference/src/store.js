// In-memory key-value store with a promise API.
const tick = () => new Promise((resolve) => setImmediate(resolve));

export function createStore() {
  const data = new Map();
  return {
    async get(key) {
      await tick();
      if (!data.has(key)) {
        throw new Error(`not found: ${key}`);
      }
      return data.get(key);
    },
    async set(key, value) {
      await tick();
      data.set(key, value);
      return value;
    },
    async keys() {
      await tick();
      return [...data.keys()];
    },
  };
}
