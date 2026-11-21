let nextId = 1;

export function resetIds() {
  nextId = 1;
}

export class UserService {
  constructor(store) {
    this.store = store;
  }

  async create(name) {
    if (!name) {
      throw new Error("name is required");
    }
    const user = { id: `u${nextId++}`, name, renames: 0 };
    await this.store.set(user.id, user);
    return user;
  }

  async rename(id, name) {
    const user = await this.store.get(id);
    const updated = { ...user, name, renames: user.renames + 1 };
    await this.store.set(id, updated);
    return updated;
  }

  async find(id) {
    return this.store.get(id);
  }
}
