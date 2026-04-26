interface LoadingBlockProps {
  label?: string
}

export function LoadingBlock({ label = 'Loading…' }: LoadingBlockProps) {
  return <div className="card loading-block">{label}</div>
}