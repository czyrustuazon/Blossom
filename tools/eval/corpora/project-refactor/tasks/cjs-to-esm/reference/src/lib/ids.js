let counter = 0;

export function nextId(prefix = "t") {
  counter += 1;
  return `${prefix}${counter}`;
}

export function resetIds() {
  counter = 0;
}
