const TaskList = require("./taskList");
const { formatTask } = require("./lib/format");
const ids = require("./lib/ids");

module.exports = {
  TaskList,
  formatTask,
  resetIds: ids.resetIds,
};
