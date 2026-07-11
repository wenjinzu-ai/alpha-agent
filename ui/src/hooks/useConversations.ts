import { useState, useCallback, useEffect } from 'react'
import type { Conversation, ConversationDetail } from '../types'

const API_BASE = '/api'

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [loading, setLoading] = useState(true)

  const fetchConversations = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/conversations`)
      if (res.ok) {
        const data = await res.json()
        setConversations(data.items || [])
      }
    } catch {
      // silent fail
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchConversations()
  }, [fetchConversations])

  const getConversation = useCallback(async (sessionId: string): Promise<ConversationDetail | null> => {
    try {
      const res = await fetch(`${API_BASE}/conversations/${sessionId}`)
      if (res.ok) {
        return await res.json()
      }
      return null
    } catch {
      return null
    }
  }, [])

  const deleteConversation = useCallback(async (sessionId: string) => {
    try {
      const res = await fetch(`${API_BASE}/conversations/${sessionId}`, { method: 'DELETE' })
      if (res.ok) {
        setConversations(prev => prev.filter(c => c.session_id !== sessionId))
      }
    } catch {
      // silent fail
    }
  }, [])

  return {
    conversations,
    loading,
    fetchConversations,
    getConversation,
    deleteConversation,
  }
}