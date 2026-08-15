export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  toolCalls?: ToolCall[]
  isStreaming?: boolean
}

export interface ToolCall {
  id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'error'
  input?: string
  output?: string
}

export interface Conversation {
  id: string
  title: string
  createdAt: Date
  updatedAt: Date
  messages: Message[]
}
