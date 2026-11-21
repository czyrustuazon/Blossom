// Builds "id: name" lines for the given ids, in order. Unknown ids are reported as missing.
export async function userReport(service, ids) {
  const lines = [];
  for (const id of ids) {
    try {
      const user = await service.find(id);
      lines.push(`${id}: ${user.name}`);
    } catch {
      lines.push(`${id}: (missing)`);
    }
  }
  return lines.join("\n");
}

export async function countUsers(store) {
  const keys = await store.keys();
  return keys.length;
}
