import { useState, useCallback, useEffect, useRef } from 'react'
import { useChat } from './hooks/useChat'
import { useConversations } from './hooks/useConversations'
import Sidebar, { SidebarToggle } from './components/Sidebar'
import ChatArea from './components/ChatArea'
import AgentStatusPanel from './components/AgentStatusPanel'
import type { Message } from './types'

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2)
}

export default function App() {
  const {
    messages,
    isStreaming,
    currentThought,
    sendMessage,
    stopStreaming,
    clearMessages,
    loadMessages,
    setThreadId,
    agentSteps,
    agents,
    totalStepCount,
  } = useChat()
  const { conversations, loading, fetchConversations, getConversation, deleteConversation } = useConversations()
  const [activeId, setActiveId] = useState<string | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false)

  const prevStreaming = useRef(false)
  useEffect(() => {
    if (prevStreaming.current && !isStreaming) {
      fetchConversations()
    }
    prevStreaming.current = isStreaming
  }, [isStreaming, fetchConversations])

  const handleNewChat = useCallback(() => {
    clearMessages()
    setActiveId(null)
  }, [clearMessages])

  const handleDelete = useCallback(async (sessionId: string) => {
    await deleteConversation(sessionId)
    if (activeId === sessionId) {
      clearMessages()
      setActiveId(null)
    }
  }, [activeId, clearMessages, deleteConversation])

  const handleSelect = useCallback(async (sessionId: string) => {
    if (isStreaming) return
    setActiveId(sessionId)

    const detail = await getConversation(sessionId)
    if (!detail) return

    const msgs: Message[] = []
    for (const m of detail.messages) {
      msgs.push({
        id: generateId(),
        role: m.role as 'user' | 'assistant',
        content: m.content,
        timestamp: new Date(),
      })
    }
    setThreadId(sessionId)
    loadMessages(msgs)
  }, [isStreaming, getConversation, loadMessages, setThreadId])

  const handleSend = useCallback((content: string, mode: 'react' | 'multi_agent') => {
    sendMessage(content, mode, activeId || undefined)
    setActiveId(null)
  }, [sendMessage, activeId])

  return (
    <div className="flex h-screen bg-[#0d0d0d] text-[#e0e0e0]">
      <SidebarToggle collapsed={sidebarCollapsed} onClick={() => setSidebarCollapsed(false)} />
      <Sidebar
        conversations={conversations}
        loading={loading}
        activeId={activeId}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        onSelect={handleSelect}
        onNew={handleNewChat}
        onDelete={handleDelete}
      />
      <ChatArea
        messages={messages}
        isStreaming={isStreaming}
        currentThought={currentThought}
        onSend={handleSend}
        onStop={stopStreaming}
      />
      <AgentStatusPanel
        agents={agents}
        steps={agentSteps}
        isStreaming={isStreaming}
        totalStepCount={totalStepCount}
        collapsed={rightPanelCollapsed}
        onToggle={() => setRightPanelCollapsed(!rightPanelCollapsed)}
        onStop={stopStreaming}
      />
    </div>
  )
}