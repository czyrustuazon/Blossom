const { nextId } = require("./lib/ids");
const fmt = require("./lib/format");

class TaskList {
  constructor() {
    this.tasks = [];
  }

  add(title, priority = "normal") {
    const task = { id: nextId(), title, priority, done: false };
    this.tasks.push(task);
    return task;
  }

  complete(id) {
    const task = this.tasks.find((t) => t.id === id);
    if (!task) throw new Error(`no task ${id}`);
    task.done = true;
    return task;
  }

  pending() {
    return this.tasks.filter((t) => !t.done);
  }

  render() {
    return this.tasks.map(fmt.formatTask).join("\n");
  }
}

module.exports = TaskList;
