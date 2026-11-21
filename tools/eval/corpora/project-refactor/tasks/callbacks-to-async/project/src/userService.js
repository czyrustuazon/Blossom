let nextId = 1;

export function resetIds() {
  nextId = 1;
}

export class UserService {
  constructor(store) {
    this.store = store;
  }

  create(name, cb) {
    if (!name) {
      cb(new Error("name is required"));
      return;
    }
    const user = { id: `u${nextId++}`, name, renames: 0 };
    this.store.set(user.id, user, (err) => {
      if (err) {
        cb(err);
        return;
      }
      cb(null, user);
    });
  }

  rename(id, name, cb) {
    this.store.get(id, (err, user) => {
      if (err) {
        cb(err);
        return;
      }
      const updated = { ...user, name, renames: user.renames + 1 };
      this.store.set(id, updated, (err2) => {
        if (err2) {
          cb(err2);
          return;
        }
        cb(null, updated);
      });
    });
  }

  find(id, cb) {
    this.store.get(id, cb);
  }
}
