import { useState, useCallback, useRef } from 'react'
import type { Message, ToolCall, WorkerProgress, AgentStep, AgentInfo } from '../types'

const API_BASE = '/api'

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2)
}

interface SSEMessage {
  type: string
  content?: string
  message?: string
  worker_name?: string
  display_name?: string
  icon?: string
  color?: string
  status?: string
  steps?: number
  step?: number
  round?: number
  total_rounds?: number
  verdict?: string
  skill?: string
  response?: string
  thread_id?: string
  tool_calls?: string[]
  tools?: string[]
  duration_ms?: number
  selected_workers?: string[]
  id?: string
  name?: string
  args?: Record<string, unknown>
  preview?: string
  content_preview?: string
}

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCall[]>([])
  const [activeWorkers, setActiveWorkers] = useState<WorkerProgress[]>([])
  const [currentThought, setCurrentThought] = useState<string>('')
  const [threadId, setThreadId] = useState<string>('')
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([])
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [totalStepCount, setTotalStepCount] = useState(0)
  const abortRef = useRef<AbortController | null>(null)

  const sendMessage = useCallback(async (
    content: string,
    mode: 'react' | 'multi_agent' = 'multi_agent',
    existingThreadId?: string
  ) => {
    if (!content.trim() || isStreaming) return

    const tid = existingThreadId || generateId()
    setThreadId(tid)

    const userMsg: Message = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: new Date(),
    }

    setMessages(prev => [...prev, userMsg])
    setIsStreaming(true)
    setActiveToolCalls([])
    setActiveWorkers([])
    setCurrentThought('')
    setAgentSteps([])
    setAgents([])
    setTotalStepCount(0)

    const assistantMsg: Message = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      toolCalls: [],
      workerProgress: [],
    }

    setMessages(prev => [...prev, assistantMsg])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: content, mode, thread_id: tid }),
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('No reader')

      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            const data = line.slice(6).trim()
            if (!data) { currentEvent = ''; continue }

            try {
              const parsed: SSEMessage = JSON.parse(data)
              parsed.type = parsed.type || currentEvent
              handleSSEMessage(parsed, assistantMsg.id)
            } catch {
              if (data !== '[DONE]' && currentEvent) {
                const fallback: SSEMessage = { type: currentEvent, content: data }
                handleSSEMessage(fallback, assistantMsg.id)
              }
            }
            currentEvent = ''
          } else if (line.trim() === '') {
            currentEvent = ''
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      appendText(assistantMsg.id, '请求失败，请重试')
    } finally {
      setIsStreaming(false)
      setActiveToolCalls([])
      setActiveWorkers([])
      setCurrentThought('')
    }
  }, [isStreaming])

  function appendText(assistantId: string, text: string) {
    setMessages(prev =>
      prev.map(m =>
        m.id === assistantId
          ? { ...m, content: m.content + text }
          : m
      )
    )
  }

  function addStep(step: AgentStep) {
    setAgentSteps(prev => [...prev, step])
    setTotalStepCount(prev => prev + 1)
  }

  function handleSSEMessage(msg: SSEMessage, assistantId: string) {
    const now = Date.now()

    switch (msg.type) {
      case 'start':
        addStep({
          id: generateId(),
          type: 'plan',
          content: '分析开始',
          status: 'done',
          timestamp: now,
        })
        break

      case 'agent_plan':
        addStep({
          id: generateId(),
          type: 'plan',
          content: `制定分析方案，选中 ${msg.selected_workers?.length || 0} 位分析师`,
          status: 'done',
          timestamp: now,
        })
        break

      case 'worker_start':
        if (msg.worker_name) {
          const wp: WorkerProgress = { workerName: msg.worker_name, status: 'running', summary: msg.display_name }
          setActiveWorkers(prev => [...prev, wp])
          setMessages(prev =>
            prev.map(m =>
              m.id === assistantId
                ? { ...m, workerProgress: [...(m.workerProgress || []), wp] }
                : m
            )
          )
          setAgents(prev => [...prev, {
            name: msg.worker_name!,
            displayName: msg.display_name || msg.worker_name!,
            icon: msg.icon,
            color: msg.color,
            status: 'running',
            currentStep: 0,
            totalSteps: 0,
            currentAction: '启动中...',
            startedAt: now,
            outputLines: [],
          }])
          addStep({
            id: generateId(),
            type: 'worker_start',
            workerName: msg.worker_name,
            displayName: msg.display_name,
            icon: msg.icon,
            color: msg.color,
            content: `${msg.display_name || msg.worker_name} 开始分析`,
            status: 'running',
            timestamp: now,
          })
        }
        break

      case 'worker_thought':
        if (msg.worker_name) {
          const thoughtContent = msg.preview || '思考中...'
          setAgents(prev => prev.map(a =>
            a.name === msg.worker_name
              ? { ...a, currentStep: msg.step || a.currentStep, currentAction: thoughtContent, outputLines: [...a.outputLines, { type: 'thought' as const, content: thoughtContent, timestamp: now }] }
              : a
          ))
          addStep({
            id: generateId(),
            type: 'worker_thought',
            workerName: msg.worker_name,
            displayName: msg.display_name,
            icon: msg.icon,
            color: msg.color,
            step: msg.step,
            content: msg.preview || '思考中...',
            status: 'running',
            timestamp: now,
          })
        }
        break

      case 'worker_tool_call':
        if (msg.worker_name) {
          const toolDesc = msg.tools?.join(', ') || 'unknown'
          setAgents(prev => prev.map(a =>
            a.name === msg.worker_name
              ? { ...a, currentStep: msg.step || a.currentStep, currentAction: `调用工具: ${toolDesc}`, outputLines: [...a.outputLines, { type: 'tool_call' as const, content: `调用: ${toolDesc}`, tools: msg.tools, timestamp: now }] }
              : a
          ))
          addStep({
            id: generateId(),
            type: 'worker_tool_call',
            workerName: msg.worker_name,
            displayName: msg.display_name,
            icon: msg.icon,
            color: msg.color,
            step: msg.step,
            tools: msg.tools,
            content: `调用工具: ${toolDesc}`,
            status: 'running',
            timestamp: now,
          })
        }
        break

      case 'worker_tool_result':
        if (msg.worker_name) {
          const toolDesc = msg.tools?.join(', ') || 'unknown'
          setAgents(prev => prev.map(a =>
            a.name === msg.worker_name
              ? { ...a, currentStep: msg.step || a.currentStep, currentAction: `工具返回: ${toolDesc}`, outputLines: [...a.outputLines, { type: 'tool_result' as const, content: `返回: ${toolDesc}`, tools: msg.tools, timestamp: now }] }
              : a
          ))
          addStep({
            id: generateId(),
            type: 'worker_tool_result',
            workerName: msg.worker_name,
            displayName: msg.display_name,
            icon: msg.icon,
            color: msg.color,
            step: msg.step,
            tools: msg.tools,
            content: `工具返回: ${toolDesc}`,
            status: 'done',
            timestamp: now,
          })
        }
        break

      case 'worker_done':
        if (msg.worker_name) {
          const doneContent = msg.content_preview || '分析完成'
          setActiveWorkers(prev =>
            prev.map(w => w.workerName === msg.worker_name ? { ...w, status: 'done' as const } : w)
          )
          setAgents(prev => prev.map(a =>
            a.name === msg.worker_name
              ? { ...a, status: 'done', totalSteps: msg.steps || 0, currentAction: '分析完成', finishedAt: now, outputLines: [...a.outputLines, { type: 'content' as const, content: doneContent, timestamp: now }] }
              : a
          ))
          addStep({
            id: generateId(),
            type: 'worker_done',
            workerName: msg.worker_name,
            displayName: msg.display_name,
            icon: msg.icon,
            color: msg.color,
            content: msg.content_preview || '分析完成',
            status: 'done',
            timestamp: now,
          })
        }
        break

      case 'thought':
        if (msg.content) setCurrentThought(msg.content)
        addStep({
          id: generateId(),
          type: 'synthesizing',
          content: msg.content,
          status: 'running',
          timestamp: now,
        })
        break

      case 'text':
        if (msg.content) {
          appendText(assistantId, msg.content)
          addStep({
            id: generateId(),
            type: 'final',
            content: '生成最终报告',
            status: 'done',
            timestamp: now,
          })
        }
        break

      case 'token':
        if (msg.content) {
          appendText(assistantId, msg.content)
        }
        break

      case 'tool_call':
        const tc: ToolCall = {
          id: msg.id || generateId(),
          name: msg.name || 'unknown',
          args: msg.args || {},
          status: 'running',
        }
        setActiveToolCalls(prev => [...prev, tc])
        setMessages(prev =>
          prev.map(m =>
            m.id === assistantId
              ? { ...m, toolCalls: [...(m.toolCalls || []), tc] }
              : m
          )
        )
        break

      case 'tool_result':
        setActiveToolCalls(prev => prev.map(tc => ({ ...tc, status: 'success' as const })))
        break

      case 'error':
        if (msg.message || msg.content) {
          appendText(assistantId, `\n\n⚠️ ${msg.message || msg.content}`)
        }
        addStep({
          id: generateId(),
          type: 'error',
          content: msg.message || msg.content || '未知错误',
          status: 'error',
          timestamp: now,
        })
        break

      case 'done':
        setAgents(prev => prev.map(a => ({ ...a, status: 'done' as const })))
        break
    }
  }

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
    setIsStreaming(false)
  }, [])

  const clearMessages = useCallback(() => {
    setMessages([])
    setActiveToolCalls([])
    setActiveWorkers([])
    setCurrentThought('')
    setThreadId('')
    setAgentSteps([])
    setAgents([])
    setTotalStepCount(0)
  }, [])

  const loadMessages = useCallback((msgs: Message[]) => {
    setMessages(msgs)
    setAgentSteps([])
    setAgents([])
    setTotalStepCount(0)
  }, [])

  return {
    messages,
    isStreaming,
    activeToolCalls,
    activeWorkers,
    currentThought,
    threadId,
    setThreadId,
    sendMessage,
    stopStreaming,
    clearMessages,
    loadMessages,
    agentSteps,
    agents,
    totalStepCount,
  }
}