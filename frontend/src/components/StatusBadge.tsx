interface StatusBadgeProps {
  value: string
}

export function StatusBadge({ value }: StatusBadgeProps) {
  return <span className={`status-pill status-${value.replace(/_/g, '-')}`}>{value.replace(/_/g, ' ')}</span>
}