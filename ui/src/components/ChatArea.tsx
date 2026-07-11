import { useState, useRef, useEffect } from 'react'
import { Square, Sparkles, ArrowUp } from 'lucide-react'
import type { Message } from '../types'
import MessageBubble from './MessageBubble'
import QuickActions from './QuickActions'

interface ChatAreaProps {
  messages: Message[]
  isStreaming: boolean
  currentThought: string
  onSend: (message: string, mode: 'react' | 'multi_agent') => void
  onStop: () => void
}

export default function ChatArea({ messages, isStreaming, currentThought, onSend, onStop }: ChatAreaProps) {
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<'react' | 'multi_agent'>('multi_agent')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, currentThought])

  useEffect(() => {
    if (!isStreaming) inputRef.current?.focus()
  }, [isStreaming])

  const handleSend = () => {
    if (!input.trim() || isStreaming) return
    onSend(input.trim(), mode)
    setInput('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleQuickAction = (prompt: string) => {
    if (isStreaming) return
    setInput(prompt)
    inputRef.current?.focus()
  }

  const lastAssistantId = [...messages].reverse().find(m => m.role === 'assistant')?.id

  const InputBox = (
    <div className="relative group">
      <div className="flex gap-3">
        {/* Input container */}
        <div className="flex-1 relative bg-[#141414] rounded-2xl border border-[#1e1e1e] group-focus-within:border-[#333] group-focus-within:shadow-[0_0_0_1px_#1e1e1e,0_8px_30px_-10px_rgba(0,0,0,0.5)] transition-all duration-300">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={mode === 'multi_agent' ? '输入股票代码或分析需求，Enter 发送' : '快速提问，如：分析茅台 600519 走势'}
            rows={1}
            disabled={isStreaming}
            className="w-full bg-transparent resize-none px-4 pt-3.5 pb-3 text-[15px] leading-relaxed text-[#e0e0e0] placeholder-[#444] outline-none disabled:opacity-50"
            style={{ maxHeight: '200px' }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement
              target.style.height = 'auto'
              target.style.height = Math.min(target.scrollHeight, 200) + 'px'
            }}
          />

          {/* Bottom bar */}
          <div className="flex items-center justify-center gap-3 px-3 pb-3">
            {/* Mode Toggle */}
            <div className="flex bg-[#0a0a0a] rounded-lg p-0.5 border border-[#1a1a1a] gap-1">
              <button
                onClick={() => setMode('multi_agent')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium transition-all duration-200 ${
                  mode === 'multi_agent'
                    ? 'bg-[#1e1e1e] text-white shadow-sm'
                    : 'text-[#555] hover:text-[#888]'
                }`}
              >
                <span className="relative flex h-1.5 w-1.5">
                  <span className={`absolute inline-flex h-full w-full rounded-full opacity-75 ${mode === 'multi_agent' ? 'bg-blue-400 animate-ping' : 'bg-[#444]'}`} />
                  <span className={`relative inline-flex rounded-full h-1.5 w-1.5 ${mode === 'multi_agent' ? 'bg-blue-500' : 'bg-[#555]'}`} />
                </span>
                多Agent协作
              </button>
              <button
                onClick={() => setMode('react')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-medium transition-all duration-200 ${
                  mode === 'react'
                    ? 'bg-[#1e1e1e] text-white shadow-sm'
                    : 'text-[#555] hover:text-[#888]'
                }`}
              >
                <span className={`relative inline-flex rounded-full h-1.5 w-1.5 ${mode === 'react' ? 'bg-emerald-500' : 'bg-[#555]'}`} />
                ReAct 快速
              </button>
            </div>
          </div>
        </div>

        {/* Send/Stop Button */}
        <div className="flex items-center">
          {isStreaming ? (
            <button
              onClick={onStop}
              className="flex items-center justify-center w-10 h-10 rounded-xl bg-[#ef4444]/10 hover:bg-[#ef4444]/20 text-[#ef4444] border border-[#ef4444]/20 transition-all duration-200"
              title="停止生成"
            >
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className={`flex items-center justify-center w-10 h-10 rounded-xl transition-all duration-300 ${
                input.trim()
                  ? 'bg-white text-black hover:bg-[#e5e5e5] hover:shadow-md hover:shadow-white/10 active:scale-95'
                  : 'bg-[#1e1e1e] text-[#444] cursor-not-allowed'
              }`}
            >
              <ArrowUp size={18} strokeWidth={2.5} className="relative top-[1px]" />
            </button>
          )}
        </div>
      </div>

      {/* Disclaimer */}
      <p className="text-[11px] text-[#333] text-center mt-3">
        AI 生成内容仅供参考，不构成投资建议
      </p>
    </div>
  )

  return (
    <div ref={containerRef} className="flex-1 flex flex-col h-full bg-[#0d0d0d]">
      {messages.length === 0 ? (
        <div className="flex-1 flex flex-col items-center px-6 py-12 overflow-y-auto">
          <div className="flex-1 flex flex-col items-center justify-center w-full">
            <div className="relative mb-6">
              <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-600 opacity-20 blur-xl scale-150" />
              <div className="relative w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center">
                <Sparkles size={30} className="text-white" />
              </div>
            </div>
            <h1 className="text-[22px] font-semibold text-white mb-2 tracking-tight">Investment Agent</h1>
            <p className="text-[14px] text-[#666] mb-8 max-w-[420px] text-center leading-relaxed">
              智能投资分析助手，支持多Agent协作分析、<br />个股深研、选股扫描、策略回测
            </p>
            <QuickActions onAction={handleQuickAction} />
          </div>

          <div className="w-full max-w-[768px] mt-8">
            {InputBox}
          </div>
        </div>
      ) : (
        <>
          {/* Messages */}
          <div className="flex-1 overflow-y-auto">
            <div className="w-full px-6 py-8 space-y-8">
              {messages.map((msg) => (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isStreaming={isStreaming && msg.id === lastAssistantId}
                />
              ))}

              {/* Thinking indicator */}
              {currentThought && (
                <div className="flex gap-4 animate-fade-in">
                  <div className="relative w-8 h-8 rounded-full flex items-center justify-center shrink-0">
                    <div className="absolute inset-0 rounded-full bg-gradient-to-br from-blue-500 to-blue-600 opacity-20 blur-md" />
                    <div className="relative w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center">
                      <Sparkles size={14} className="text-white" />
                    </div>
                  </div>
                  <div className="flex-1 py-1">
                    <div className="flex items-center gap-2 mb-1.5">
                      <div className="thinking-dots flex items-center gap-1">
                        <span /><span /><span />
                      </div>
                      <span className="text-[12px] text-[#555]">推理中</span>
                    </div>
                    <p className="text-[13px] text-[#555] italic leading-relaxed">
                      {currentThought}
                    </p>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Input Area */}
          <div className="shrink-0 w-full flex justify-center px-6 pb-6">
            <div className="w-full max-w-[768px]">
              {InputBox}
            </div>
          </div>
        </>
      )}
    </div>
  )
}