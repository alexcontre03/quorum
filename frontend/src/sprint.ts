/**
 * Formato humano del sprint_id. Soporta dos convenciones del dataset:
 *   "sprint-24" -> "Sprint 24"
 *   "s1", "s2"  -> "Sprint 1", "Sprint 2"
 * Cualquier otro id se devuelve capitalizado tal cual, sin transformarlo.
 */
export function formatSprintId(sprintId: string): string {
  const longMatch = sprintId.match(/^sprint-(\d+)$/i);
  if (longMatch) return `Sprint ${longMatch[1]}`;
  const shortMatch = sprintId.match(/^s(\d+)$/i);
  if (shortMatch) return `Sprint ${shortMatch[1]}`;
  return sprintId.charAt(0).toUpperCase() + sprintId.slice(1);
}
