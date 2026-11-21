// In-memory key-value store with an error-first callback API.
export function createStore() {
  const data = new Map();
  return {
    get(key, cb) {
      setImmediate(() => {
        if (!data.has(key)) {
          cb(new Error(`not found: ${key}`));
          return;
        }
        cb(null, data.get(key));
      });
    },
    set(key, value, cb) {
      setImmediate(() => {
        data.set(key, value);
        cb(null, value);
      });
    },
    keys(cb) {
      setImmediate(() => cb(null, [...data.keys()]));
    },
  };
}
