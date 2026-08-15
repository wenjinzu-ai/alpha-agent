export interface ConversationItem {
  session_id: string
  user_query: string
  analysis_type: string
  status: string
  created_at: string
  duration_ms: number
  total_steps: number
}

export interface ConversationMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

export interface ConversationDetail {
  session_id: string
  user_query: string
  analysis_type: string
  status: string
  created_at: string
  final_result: string
  duration_ms: number
  total_steps: number
  messages: ConversationMessage[]
}

export interface ToolCallEvent {
  id: string
  name: string
  args: Record<string, unknown>
}

export interface StreamCallbacks {
  onStart?: (threadId: string) => void
  onToken?: (content: string) => void
  onToolCall?: (toolCall: ToolCallEvent) => void
  onToolResult?: () => void
  onDone?: (data: {
    thread_id: string
    response: string
    tool_calls: string[]
    duration_ms: number
    steps: number
  }) => void
  onError?: (message: string) => void
}

const API_BASE = '/api'

export async function fetchConversations(): Promise<ConversationItem[]> {
  try {
    const res = await fetch(`${API_BASE}/conversations`)
    if (!res.ok) return []
    const data = await res.json()
    return data.items || []
  } catch {
    return []
  }
}

export async function fetchConversation(sessionId: string): Promise<ConversationDetail | null> {
  try {
    const res = await fetch(`${API_BASE}/conversations/${sessionId}`)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function deleteConversation(sessionId: string): Promise<boolean> {
  try {
    await fetch(`${API_BASE}/conversations/${sessionId}`, { method: 'DELETE' })
    return true
  } catch {
    return false
  }
}

export function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).substring(2, 9)
}

interface SSEEvent {
  event: string
  data: Record<string, unknown>
}

function parseSSEChunk(chunk: string): SSEEvent[] {
  const events: SSEEvent[] = []
  const lines = chunk.split('\n')
  let currentEvent = 'message'
  let currentData = ''

  for (const line of lines) {
    if (line.startsWith('event: ')) {
      currentEvent = line.slice(7).trim()
    } else if (line.startsWith('data: ')) {
      currentData += line.slice(6)
    } else if (line === '') {
      if (currentData) {
        try {
          events.push({
            event: currentEvent,
            data: JSON.parse(currentData),
          })
        } catch {
        }
        currentEvent = 'message'
        currentData = ''
      }
    }
  }

  return events
}

export function streamChat(
  threadId: string,
  message: string,
  callbacks: StreamCallbacks
): () => void {
  const controller = new AbortController()
  let cancelled = false

  const startStream = async () => {
    try {
      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          thread_id: threadId,
          message,
        }),
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No response body')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (!cancelled) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const events = parseSSEChunk(buffer)
        const lastNewline = buffer.lastIndexOf('\n\n')
        if (lastNewline !== -1) {
          buffer = buffer.slice(lastNewline + 2)
        }

        for (const { event, data } of events) {
          if (cancelled) break
          handleSSEEvent(event, data, callbacks)
        }
      }

      if (buffer.trim() && !cancelled) {
        const events = parseSSEChunk(buffer + '\n\n')
        for (const { event, data } of events) {
          handleSSEEvent(event, data, callbacks)
        }
      }
    } catch (error: unknown) {
      if (!cancelled && error instanceof Error && error.name !== 'AbortError') {
        callbacks.onError?.(error.message)
      }
    }
  }

  function handleSSEEvent(
    event: string,
    data: Record<string, unknown>,
    cb: StreamCallbacks
  ) {
    switch (event) {
      case 'start':
        cb.onStart?.(data.thread_id as string)
        break
      case 'token':
        if (typeof data.content === 'string') {
          cb.onToken?.(data.content)
        }
        break
      case 'tool_call':
        cb.onToolCall?.({
          id: data.id as string,
          name: data.name as string,
          args: data.args as Record<string, unknown>,
        })
        break
      case 'tool_result':
        cb.onToolResult?.()
        break
      case 'done':
        cb.onDone?.({
          thread_id: data.thread_id as string,
          response: (data.response as string) || '',
          tool_calls: (data.tool_calls as string[]) || [],
          duration_ms: data.duration_ms as number,
          steps: data.steps as number,
        })
        break
      case 'error':
        cb.onError?.((data.message as string) || '未知错误')
        break
    }
  }

  startStream()

  return () => {
    cancelled = true
    controller.abort()
  }
}

export async function interruptSession(sessionId: string): Promise<void> {
  try {
    await fetch(`${API_BASE}/interrupt/${sessionId}`, { method: 'POST' })
  } catch {
  }
}
