// Deep teal-charcoal dark mode rather than the generic navy/electric-blue
// "dev-tool dark mode" look — teal reads calmer and more clinical, and
// gives status colors (amber/coral/green below) room to actually mean
// something instead of competing with a loud blue everywhere.
export const colors = {
  background: '#0d1614',
  surface: '#15221f',
  surfaceRaised: '#1c332c',
  border: '#28403a',
  text: '#edf5f1',
  textMuted: '#8fa89e',
  primary: '#2fbf9f',
  primaryPressed: '#24a085',
  danger: '#f2634b',
  success: '#4fd68c',
  warning: '#f2b84b',
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
};

// Best-effort semantic color for a status string coming from the backend
// (Appointment/RefillRequest/Invoice/LabOrder/Visit all define their own
// status choices — this matches by keyword rather than enumerating every
// model's exact values, so it degrades gracefully for one we haven't seen).
export function statusColor(status: string): string {
  const s = status.toUpperCase();
  if (/(CANCEL|DENIED|REJECTED|FAILED)/.test(s)) return colors.danger;
  if (/(COMPLETE|PAID|RESOLVED|DISPENSED|APPROVED|ACTIVE)/.test(s)) return colors.success;
  if (/(WAITING|PENDING|SCHEDULED|REQUESTED|PARTIAL|ACKNOWLEDGED)/.test(s)) return colors.warning;
  return colors.primary;
}
