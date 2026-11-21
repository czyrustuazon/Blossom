// Builds "id: name" lines for the given ids, in order. Unknown ids are reported as missing.
export function userReport(service, ids, cb) {
  const lines = [];
  let i = 0;
  function next() {
    if (i >= ids.length) {
      cb(null, lines.join("\n"));
      return;
    }
    const id = ids[i++];
    service.find(id, (err, user) => {
      lines.push(err ? `${id}: (missing)` : `${id}: ${user.name}`);
      next();
    });
  }
  next();
}

export function countUsers(store, cb) {
  store.keys((err, keys) => {
    if (err) {
      cb(err);
      return;
    }
    cb(null, keys.length);
  });
}
