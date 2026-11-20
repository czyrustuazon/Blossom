let counter = 0;

function nextId(prefix = "t") {
  counter += 1;
  return `${prefix}${counter}`;
}

function resetIds() {
  counter = 0;
}

module.exports = { nextId, resetIds };
