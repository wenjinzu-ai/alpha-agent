import { useEffect, useRef, useState } from 'react'
import { MessageBubble } from './MessageBubble'
import { Sparkles, ArrowDown } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import type { Message } from '@/types/chat'

interface MessageListProps {
  messages: Message[]
  isLoading?: boolean
}

export function MessageList({ messages, isLoading }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [showScrollButton, setShowScrollButton] = useState(false)

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container
      setShowScrollButton(scrollHeight - scrollTop - clientHeight > 100)
    }

    container.addEventListener('scroll', handleScroll)
    return () => container.removeEventListener('scroll', handleScroll)
  }, [])

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
        <div className="h-16 w-16 rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center mb-6 shadow-lg">
          <Sparkles className="h-8 w-8 text-white" />
        </div>
        <h2 className="text-2xl font-semibold mb-2">Alpha Agent</h2>
        <p className="text-muted-foreground max-w-md mb-8">
          你的智能量化投资助手，可以帮助你进行股票筛选、因子分析、策略回测、行业轮动等。
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-xl w-full">
          {[
            '帮我筛选今日放量上涨的股票',
            '计算过去30天上证指数的技术指标',
            '回测一个均线交叉策略',
            '分析当前市场行业轮动情况',
          ].map((suggestion, i) => (
            <button
              key={i}
              className="text-left p-4 rounded-xl border border-border hover:bg-accent hover:border-accent-foreground/20 transition-colors group"
            >
              <span className="text-sm group-hover:text-accent-foreground">
                {suggestion}
              </span>
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto relative px-4">
      <div className="max-w-5xl mx-auto py-4">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {isLoading && messages[messages.length - 1]?.role !== 'assistant' && (
          <MessageBubble
            message={{
              id: 'loading',
              role: 'assistant',
              content: '',
              timestamp: new Date(),
              isStreaming: true,
            }}
          />
        )}
        <div ref={bottomRef} />
      </div>
      {showScrollButton && (
        <Button
          variant="secondary"
          size="icon"
          className="absolute bottom-4 right-4 h-10 w-10 rounded-full shadow-lg"
          onClick={scrollToBottom}
        >
          <ArrowDown className="h-4 w-4" />
        </Button>
      )}
    </div>
  )
}
