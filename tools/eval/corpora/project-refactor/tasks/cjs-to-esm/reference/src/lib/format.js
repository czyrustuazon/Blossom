export const PRIORITY_MARK = { high: "!!", normal: "", low: "~" };

export function formatTask(task) {
  const box = task.done ? "[x]" : "[ ]";
  const mark = PRIORITY_MARK[task.priority] || "";
  return `${box} ${mark}${task.title}`.replace(/\s+$/, "");
}
