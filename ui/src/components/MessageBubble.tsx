import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Sparkles, User } from 'lucide-react'
import type { Message } from '../types'
import ToolCallCard from './ToolCallCard'
import WorkerProgress from './WorkerProgress'

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
}

export default function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isAssistant = message.role === 'assistant'
  const showCursor = isAssistant && isStreaming && message.content.length > 0

  // 流式期间用纯文本渲染（性能优），结束后用 Markdown 渲染
  const renderedContent = useMemo(() => {
    if (isStreaming && isAssistant) {
      // 流式中：逐行渲染，不做 Markdown 解析（避免频繁重渲染卡顿）
      return message.content.split('\n').map((line, i) => (
        <span key={i}>
          {line}
          {i < message.content.split('\n').length - 1 && <br />}
        </span>
      ))
    }
    // 流式结束：完整 Markdown 渲染
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {message.content}
      </ReactMarkdown>
    )
  }, [message.content, isStreaming, isAssistant])

  return (
    <div className={`flex gap-4 animate-slide-up ${isUser ? 'flex-row-reverse ml-auto' : ''}`}>
      {/* Avatar */}
      {isAssistant ? (
        <div className="relative w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1">
          <div className="absolute inset-0 rounded-full bg-gradient-to-br from-blue-500 to-blue-600 opacity-20 blur-md" />
          <div className="relative w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center">
            <Sparkles size={14} className="text-white" />
          </div>
        </div>
      ) : (
        <div className="w-8 h-8 rounded-full bg-[#2a2a2a] flex items-center justify-center shrink-0 mt-1">
          <User size={15} className="text-[#888]" />
        </div>
      )}

      {/* Content */}
      <div className={`min-w-0 ${isUser ? 'max-w-[75%]' : 'max-w-[768px]'}`}>
        {isUser ? (
          <div className="inline-block px-4 py-2.5 rounded-2xl rounded-tl-sm bg-[#2a2a2a] text-[14px] leading-relaxed text-[#e0e0e0] text-left">
            {message.content}
          </div>
        ) : (
          <div className="space-y-3">
            {/* Worker progress */}
            {message.workerProgress && message.workerProgress.length > 0 && (
              <WorkerProgress workers={message.workerProgress} />
            )}

            {/* Tool calls */}
            {message.toolCalls && message.toolCalls.length > 0 && (
              <div className="space-y-1.5">
                {message.toolCalls.map((tc) => (
                  <ToolCallCard key={tc.id} toolCall={tc} />
                ))}
              </div>
            )}

            {/* Streaming thinking indicator */}
            {isStreaming && !message.content && (
              <div className="flex items-center gap-2 py-1">
                <div className="thinking-dots flex items-center gap-1">
                  <span /><span /><span />
                </div>
                <span className="text-[12px] text-[#555]">思考中</span>
              </div>
            )}

            {/* Message content */}
            {message.content && (
              <div className={`text-[14px] leading-[1.75] text-[#d4d4d4] ${
                !isStreaming ? 'prose prose-invert max-w-none prose-p:my-2 prose-p:leading-[1.75] prose-headings:my-4 prose-headings:text-[#e0e0e0] prose-headings:font-semibold prose-h1:text-[20px] prose-h2:text-[17px] prose-h3:text-[15px] prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-li:leading-[1.75] prose-table:text-[12px] prose-table:border-collapse prose-th:py-1.5 prose-th:px-3 prose-th:bg-[#1a1a1a] prose-th:border prose-th:border-[#2a2a2a] prose-td:py-1.5 prose-td:px-3 prose-td:border prose-td:border-[#2a2a2a] prose-code:text-[12px] prose-code:bg-[#1a1a1a] prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:text-[#ccc] prose-code:before:content-[\'\'] prose-code:after:content-[\'\'] prose-pre:bg-[#141414] prose-pre:border prose-pre:border-[#1e1e1e] prose-pre:rounded-xl prose-pre:my-3 prose-strong:text-[#e0e0e0] prose-strong:font-semibold prose-a:text-blue-400 prose-a:no-underline hover:prose-a:underline prose-blockquote:border-l-2 prose-blockquote:border-blue-500/30 prose-blockquote:pl-4 prose-blockquote:text-[#999]' : ''
              } ${showCursor ? 'streaming-cursor' : ''}`}>
                {renderedContent}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}