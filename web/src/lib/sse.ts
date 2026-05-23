/**
 * SSE event stream connection for live alerts.
 */

export type AlertPayload = {
  id?: number
  timestamp?: string
  attack_type?: string
  severity?: string
  confidence?: number
  source?: string
  [key: string]: unknown
}

export function connectAlertStream(
  onAlert: (payload: AlertPayload) => void,
  onHeartbeat?: () => void,
  onError?: (err: Event) => void,
): () => void {
  const es = new EventSource('/api/alerts/sse')

  es.addEventListener('alert', (e: MessageEvent) => {
    try {
      const payload = JSON.parse(e.data) as AlertPayload
      onAlert(payload)
    } catch {
      // malformed JSON — skip
    }
  })

  if (onHeartbeat) {
    es.addEventListener('heartbeat', () => onHeartbeat())
  }

  if (onError) {
    es.onerror = onError
  }

  return () => es.close()
}
