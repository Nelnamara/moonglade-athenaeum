/* The Account screen's card-history row words (#68).

   PixAI's card log (GET /v2/kaisuuken/logs, through moonglade_backup.list_kaisuuken_logs) has
   four actions, its contract's enum: consumed | refunded | revoked | expired. Only a consumed
   or refunded card was attached to a task. An expired card ran out and a revoked one was taken
   back: PixAI sends those rows with no task id and no credit cost, so they get no task line.
   Before this every row that was not a refund read "– consumed" with an empty task, so cards
   that simply ran out looked as if a generation had used them.

   An action PixAI adds later shows as its own word, never as "consumed". */

const WORDS = {
  consumed: "– consumed",
  refunded: "↺ refunded",
  expired: "– expired",
  revoked: "– revoked",
};
const WITH_TASK = ["consumed", "refunded"];

export function cardLogRow(ev) {
  const action = String((ev && ev.action) || "");
  const taskId = String((ev && ev.task_id) || "");
  return {
    label: WORDS[action] || "– " + (action || "unknown"),
    refund: action === "refunded",
    task: WITH_TASK.indexOf(action) >= 0 ? taskId : "",
  };
}
