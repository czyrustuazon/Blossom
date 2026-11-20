const PRIORITY_MARK = { high: "!!", normal: "", low: "~" };

exports.formatTask = function formatTask(task) {
  const box = task.done ? "[x]" : "[ ]";
  const mark = PRIORITY_MARK[task.priority] || "";
  return `${box} ${mark}${task.title}`.replace(/\s+$/, "");
};

exports.PRIORITY_MARK = PRIORITY_MARK;
