export interface Conversation {
  session_id: string
  user_query: string
  analysis_type: string
  status: string
  created_at: string
  duration_ms: number
  total_steps: number
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

export interface ConversationMessage {
  role: string
  content: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  toolCalls?: ToolCall[]
  workerProgress?: WorkerProgress[]
}

export interface ToolCall {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
  status: 'running' | 'success' | 'error'
}

export interface WorkerProgress {
  workerName: string
  status: 'pending' | 'running' | 'done' | 'error'
  summary?: string
}

export interface ChatRequest {
  message: string
  thread_id?: string
  mode?: 'react' | 'multi_agent'
}

export interface AgentStep {
  id: string
  type: 'plan' | 'worker_start' | 'worker_thought' | 'worker_tool_call' | 'worker_tool_result' | 'worker_done' | 'synthesizing' | 'final' | 'error'
  workerName?: string
  displayName?: string
  icon?: string
  color?: string
  step?: number
  content?: string
  tools?: string[]
  status: 'pending' | 'running' | 'done' | 'error'
  timestamp: number
}

export interface AgentOutputLine {
  type: 'thought' | 'tool_call' | 'tool_result' | 'content'
  content: string
  tools?: string[]
  timestamp: number
}

export interface AgentInfo {
  name: string
  displayName: string
  icon?: string
  color?: string
  status: 'pending' | 'running' | 'done' | 'error'
  currentStep: number
  totalSteps: number
  currentAction: string
  startedAt: number
  finishedAt?: number
  outputLines: AgentOutputLine[]
}