import { useState, useCallback, useEffect, useRef } from 'react'
import { ThemeProvider } from '@/contexts/ThemeContext'
import { Sidebar } from '@/components/layout/Sidebar'
import { Header } from '@/components/layout/Header'
import { MessageList } from '@/components/chat/MessageList'
import { ChatInput } from '@/components/chat/ChatInput'
import { cn } from '@/lib/utils'
import type { Conversation, Message, ToolCall } from '@/types/chat'
import {
  fetchConversations,
  fetchConversation,
  deleteConversation as apiDeleteConversation,
  streamChat,
  generateId,
  interruptSession,
  type ConversationItem,
} from '@/lib/api'

function convertApiConversation(item: ConversationItem): Conversation {
  return {
    id: item.session_id,
    title: item.user_query || '新对话',
    createdAt: new Date(item.created_at || Date.now()),
    updatedAt: new Date(item.created_at || Date.now()),
    messages: [],
  }
}

function ChatApp() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const cancelStreamRef = useRef<(() => void) | null>(null)

  const currentConversation = conversations.find((c) => c.id === currentConversationId)

  useEffect(() => {
    const checkConnection = async () => {
      try {
        const res = await fetch('/health', { method: 'GET' })
        setIsConnected(res.ok)
      } catch {
        setIsConnected(false)
      }
    }
    checkConnection()
    const interval = setInterval(checkConnection, 5000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    const loadConversations = async () => {
      const items = await fetchConversations()
      if (items.length > 0) {
        const convs = items.map(convertApiConversation)
        setConversations(convs)
        setCurrentConversationId(convs[0].id)
        loadConversationMessages(convs[0].id)
      } else {
        const newConv: Conversation = {
          id: generateId(),
          title: '新对话',
          createdAt: new Date(),
          updatedAt: new Date(),
          messages: [],
        }
        setConversations([newConv])
        setCurrentConversationId(newConv.id)
      }
    }
    loadConversations()
  }, [])

  const loadConversationMessages = async (convId: string) => {
    const detail = await fetchConversation(convId)
    if (detail) {
      const messages: Message[] = detail.messages
        .filter((m) => m.content.trim())
        .map((m, i) => ({
          id: `${convId}-${i}`,
          role: m.role,
          content: m.content,
          timestamp: new Date(detail.created_at || Date.now()),
        }))

      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== convId) return c
          return {
            ...c,
            title: detail.user_query?.slice(0, 30) || c.title,
            messages,
          }
        })
      )
    }
  }

  const handleNewConversation = useCallback(() => {
    const newConv: Conversation = {
      id: generateId(),
      title: '新对话',
      createdAt: new Date(),
      updatedAt: new Date(),
      messages: [],
    }
    setConversations((prev) => [newConv, ...prev])
    setCurrentConversationId(newConv.id)
    setMobileSidebarOpen(false)
  }, [])

  const handleSelectConversation = useCallback(async (id: string) => {
    setCurrentConversationId(id)
    setMobileSidebarOpen(false)
    const conv = conversations.find((c) => c.id === id)
    if (conv && conv.messages.length === 0) {
      await loadConversationMessages(id)
    }
  }, [conversations])

  const handleDeleteConversation = useCallback(async (id: string) => {
    await apiDeleteConversation(id)
    setConversations((prev) => {
      const filtered = prev.filter((c) => c.id !== id)
      if (filtered.length === 0) {
        const newConv: Conversation = {
          id: generateId(),
          title: '新对话',
          createdAt: new Date(),
          updatedAt: new Date(),
          messages: [],
        }
        setCurrentConversationId(newConv.id)
        return [newConv]
      }
      if (currentConversationId === id) {
        setCurrentConversationId(filtered[0].id)
      }
      return filtered
    })
  }, [currentConversationId])

  const handleSend = useCallback(async (content: string) => {
    if (!currentConversationId || isLoading) return

    const userMessage: Message = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: new Date(),
    }

    const assistantMessageId = generateId()
    const assistantMessage: Message = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
      toolCalls: [],
    }

    setConversations((prev) =>
      prev.map((c) => {
        if (c.id !== currentConversationId) return c
        const newTitle = c.messages.length === 0
          ? content.slice(0, 30) + (content.length > 30 ? '...' : '')
          : c.title
        return {
          ...c,
          title: newTitle,
          messages: [...c.messages, userMessage, assistantMessage],
          updatedAt: new Date(),
        }
      })
    )

    setIsLoading(true)
    let pendingContent = ''
    let toolCallCount = 0
    let toolResultCount = 0

    const cancel = streamChat(currentConversationId, content, {
      onToken: (token) => {
        pendingContent += token
      },
      onToolCall: (toolCall) => {
        toolCallCount += 1
        const newToolCall: ToolCall = {
          id: toolCall.id,
          name: toolCall.name,
          status: 'running',
          input: JSON.stringify(toolCall.args || {}),
        }
        setConversations((prev) =>
          prev.map((c) => {
            if (c.id !== currentConversationId) return c
            return {
              ...c,
              messages: c.messages.map((m) =>
                m.id === assistantMessageId
                  ? {
                      ...m,
                      toolCalls: [...(m.toolCalls || []), newToolCall],
                    }
                  : m
              ),
            }
          })
        )
      },
      onToolResult: () => {
        toolResultCount += 1
        setConversations((prev) =>
          prev.map((c) => {
            if (c.id !== currentConversationId) return c
            return {
              ...c,
              messages: c.messages.map((m) => {
                if (m.id !== assistantMessageId || !m.toolCalls) return m
                const updatedToolCalls = [...m.toolCalls]
                const idx = toolResultCount - 1
                if (idx >= 0 && idx < updatedToolCalls.length) {
                  updatedToolCalls[idx] = { ...updatedToolCalls[idx], status: 'completed' }
                }
                return { ...m, toolCalls: updatedToolCalls }
              }),
            }
          })
        )
      },
      onDone: (data) => {
        const finalResponse = data.response || pendingContent
        setConversations((prev) =>
          prev.map((c) => {
            if (c.id !== currentConversationId) return c
            return {
              ...c,
              messages: c.messages.map((m) => {
                if (m.id !== assistantMessageId) return m
                const allCompleted = (m.toolCalls || []).map((tc) => ({
                  ...tc,
                  status: 'completed' as const,
                }))
                return {
                  ...m,
                  content: finalResponse,
                  isStreaming: false,
                  toolCalls: allCompleted,
                }
              }),
            }
          })
        )
        setIsLoading(false)
        cancelStreamRef.current = null
        refreshConversations()
      },
      onError: (message) => {
        const errorContent = `抱歉，发生了错误：${message}`
        setConversations((prev) =>
          prev.map((c) => {
            if (c.id !== currentConversationId) return c
            return {
              ...c,
              messages: c.messages.map((m) => {
                if (m.id !== assistantMessageId) return m
                const allCompleted = (m.toolCalls || []).map((tc) => ({
                  ...tc,
                  status: 'error' as const,
                }))
                return {
                  ...m,
                  content: errorContent,
                  isStreaming: false,
                  toolCalls: allCompleted,
                }
              }),
            }
          })
        )
        setIsLoading(false)
        cancelStreamRef.current = null
      },
    })

    cancelStreamRef.current = cancel
  }, [currentConversationId, isLoading])

  const refreshConversations = async () => {
    const items = await fetchConversations()
    setConversations((prev) => {
      const existingIds = new Set(prev.map((c) => c.id))
      const newConvs = items
        .filter((item) => !existingIds.has(item.session_id))
        .map(convertApiConversation)
      return [...newConvs, ...prev]
    })
  }

  const handleStop = useCallback(() => {
    if (cancelStreamRef.current) {
      cancelStreamRef.current()
      cancelStreamRef.current = null
    }
    if (currentConversationId) {
      interruptSession(currentConversationId)
    }
    setIsLoading(false)
    setConversations((prev) =>
      prev.map((c) => {
        if (c.id !== currentConversationId) return c
        return {
          ...c,
          messages: c.messages.map((m) =>
            m.isStreaming ? { ...m, isStreaming: false } : m
          ),
        }
      })
    )
  }, [currentConversationId])

  const toggleSidebar = useCallback(() => {
    if (window.innerWidth < 768) {
      setMobileSidebarOpen((prev) => !prev)
    } else {
      setSidebarCollapsed((prev) => !prev)
    }
  }, [])

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <div
        className={cn(
          'hidden md:flex',
          mobileSidebarOpen && 'flex fixed inset-0 z-50 bg-black/50 md:relative md:bg-transparent'
        )}
        onClick={() => setMobileSidebarOpen(false)}
      >
        <div onClick={(e) => e.stopPropagation()}>
          <Sidebar
            conversations={conversations}
            currentConversationId={currentConversationId}
            onSelectConversation={handleSelectConversation}
            onNewConversation={handleNewConversation}
            onDeleteConversation={handleDeleteConversation}
            collapsed={sidebarCollapsed}
            onToggleCollapse={() => setSidebarCollapsed((prev) => !prev)}
          />
        </div>
      </div>

      {mobileSidebarOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          <div className="bg-black/50 flex-1" onClick={() => setMobileSidebarOpen(false)} />
          <Sidebar
            conversations={conversations}
            currentConversationId={currentConversationId}
            onSelectConversation={handleSelectConversation}
            onNewConversation={handleNewConversation}
            onDeleteConversation={handleDeleteConversation}
            collapsed={false}
            onToggleCollapse={() => setMobileSidebarOpen(false)}
          />
        </div>
      )}

      <div className="flex-1 flex flex-col min-w-0">
        <Header onToggleSidebar={toggleSidebar} />
        <MessageList
          messages={currentConversation?.messages || []}
          isLoading={isLoading}
        />
        <ChatInput
          onSend={handleSend}
          isLoading={isLoading}
          onStop={handleStop}
          isConnected={isConnected}
        />
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <ChatApp />
    </ThemeProvider>
  )
}
