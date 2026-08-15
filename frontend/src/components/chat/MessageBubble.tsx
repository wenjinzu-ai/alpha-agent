import { useState } from 'react'
import { Avatar } from '@/components/ui/Avatar'
import { cn } from '@/lib/utils'
import { Bot, User, Loader2, CheckCircle2, XCircle, ChevronDown, ChevronUp, Terminal, Wrench } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { Message, ToolCall } from '@/types/chat'

interface ToolCallDisplayProps {
  toolCall: ToolCall
  defaultOpen?: boolean
}

function ToolCallDisplay({ toolCall, defaultOpen = false }: ToolCallDisplayProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  const statusConfig = {
    pending: {
      icon: <Loader2 className="h-4 w-4 animate-spin text-yellow-500" />,
      label: '等待中',
      color: 'text-yellow-500',
      bg: 'bg-yellow-500/10',
    },
    running: {
      icon: <Loader2 className="h-4 w-4 animate-spin text-blue-500" />,
      label: '执行中',
      color: 'text-blue-500',
      bg: 'bg-blue-500/10',
    },
    completed: {
      icon: <CheckCircle2 className="h-4 w-4 text-green-500" />,
      label: '已完成',
      color: 'text-green-500',
      bg: 'bg-green-500/10',
    },
    error: {
      icon: <XCircle className="h-4 w-4 text-red-500" />,
      label: '失败',
      color: 'text-red-500',
      bg: 'bg-red-500/10',
    },
  }

  const config = statusConfig[toolCall.status]
  const hasContent = !!(toolCall.input || toolCall.output)

  const formatArgs = (argsStr?: string) => {
    if (!argsStr) return ''
    try {
      return JSON.stringify(JSON.parse(argsStr), null, 2)
    } catch {
      return argsStr
    }
  }

  return (
    <div className="rounded-lg border border-border bg-muted/40 overflow-hidden transition-all">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted/60 transition-colors text-left"
      >
        <Wrench className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        <span className="text-xs font-mono font-medium truncate flex-1">
          {toolCall.name}
        </span>
        <span className={cn('text-[10px] font-medium px-1.5 py-0.5 rounded', config.bg, config.color)}>
          {config.label}
        </span>
        {hasContent && (
          isOpen
            ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        )}
      </button>
      {isOpen && hasContent && (
        <div className="border-t border-border bg-background/50">
          {toolCall.input && (
            <div className="px-3 py-2 border-b border-border/50">
              <div className="text-[10px] text-muted-foreground mb-1 font-medium uppercase tracking-wide">参数</div>
              <pre className="text-xs font-mono text-muted-foreground bg-muted/50 rounded p-2 max-h-40 overflow-auto whitespace-pre-wrap break-all">
                {formatArgs(toolCall.input)}
              </pre>
            </div>
          )}
          {toolCall.output && (
            <div className="px-3 py-2">
              <div className="text-[10px] text-muted-foreground mb-1 font-medium uppercase tracking-wide">结果</div>
              <pre className="text-xs font-mono bg-muted/30 rounded p-2 max-h-60 overflow-auto whitespace-pre-wrap break-all">
                {toolCall.output}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface ToolCallListProps {
  toolCalls: ToolCall[]
}

function ToolCallList({ toolCalls }: ToolCallListProps) {
  const [isExpanded, setIsExpanded] = useState(false)

  if (toolCalls.length === 0) return null

  const completedCount = toolCalls.filter(tc => tc.status === 'completed' || tc.status === 'error').length
  const totalCount = toolCalls.length
  const isRunning = completedCount < totalCount

  return (
    <div className="mt-2 rounded-lg border border-border bg-muted/20 overflow-hidden">
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted/40 transition-colors text-left"
      >
        <Terminal className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        <span className="text-xs font-medium text-muted-foreground flex-1">
          思考过程 ({completedCount}/{totalCount})
        </span>
        {isRunning && (
          <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
        )}
        {!isRunning && completedCount === totalCount && totalCount > 0 && (
          <CheckCircle2 className="h-3 w-3 text-green-500" />
        )}
        {isExpanded ? (
          <ChevronUp className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        )}
      </button>
      {isExpanded && (
        <div className="border-t border-border p-2 space-y-1.5 bg-background/30">
          {toolCalls.map((tc) => (
            <ToolCallDisplay key={tc.id} toolCall={tc} defaultOpen={false} />
          ))}
        </div>
      )}
    </div>
  )
}

interface MessageBubbleProps {
  message: Message
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  const hasToolCalls = !isUser && message.toolCalls && message.toolCalls.length > 0
  const hasContent = message.content && message.content.trim().length > 0

  if (isUser) {
    return (
      <div className="flex gap-3 py-4 flex-row-reverse">
        <Avatar
          className="h-8 w-8 shrink-0 bg-bubble-user"
          fallback={<User className="h-4 w-4 text-white" />}
        />
        <div className="flex flex-col gap-1 max-w-[85%] items-end">
          <div className="rounded-2xl px-4 py-3 bg-bubble-user text-bubble-user-foreground rounded-tr-md">
            {message.content}
          </div>
          <span className="text-xs text-muted-foreground px-1">
            {message.timestamp.toLocaleTimeString('zh-CN', {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-3 py-4 flex-row">
      <Avatar
        className="h-8 w-8 shrink-0 bg-muted"
        fallback={<Bot className="h-4 w-4" />}
      />
      <div className="flex flex-col gap-1 max-w-[85%] items-start">
        {hasToolCalls && <ToolCallList toolCalls={message.toolCalls!} />}
        {hasContent && (
          <div className="rounded-2xl px-4 py-3 bg-bubble-assistant text-bubble-assistant-foreground rounded-tl-md">
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
              >
                {message.content}
              </ReactMarkdown>
            </div>
            {message.isStreaming && (
              <span className="inline-block w-1.5 h-5 bg-current ml-1 animate-pulse align-middle" />
            )}
          </div>
        )}
        {!hasContent && hasToolCalls && message.isStreaming && (
          <div className="text-sm text-muted-foreground flex items-center gap-2 py-1">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>正在分析中...</span>
          </div>
        )}
        {!hasContent && !hasToolCalls && message.isStreaming && (
          <div className="text-sm text-muted-foreground flex items-center gap-2 py-1">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>正在思考中...</span>
          </div>
        )}
        <span className="text-xs text-muted-foreground px-1">
          {message.timestamp.toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </span>
      </div>
    </div>
  )
}
