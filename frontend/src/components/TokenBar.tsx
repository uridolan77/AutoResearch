interface TokenBarProps {
  used: number
  cap: number
}

export function TokenBar({ used, cap }: TokenBarProps) {
  const ratio = cap > 0 ? Math.min(100, Math.round((used / cap) * 100)) : 0
  return (
    <div>
      <div className="token-meta">
        <span>Budget</span>
        <strong>{used.toLocaleString()} / {cap.toLocaleString()}</strong>
      </div>
      <div className="token-bar">
        <div className={`token-fill ${ratio >= 80 ? 'is-warning' : ''}`} style={{ width: `${ratio}%` }} />
      </div>
    </div>
  )
}