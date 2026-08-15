import { useState, type FormEvent, type KeyboardEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { Textarea } from '@/components/ui/Textarea'
import { Send, Square, Paperclip, Wifi, WifiOff } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ChatInputProps {
  onSend: (message: string) => void
  isLoading?: boolean
  onStop?: () => void
  isConnected?: boolean
}

export function ChatInput({ onSend, isLoading, onStop, isConnected = true }: ChatInputProps) {
  const [input, setInput] = useState('')

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return
    onSend(input.trim())
    setInput('')
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="px-4 py-4 border-t border-border bg-background shrink-0">
      <div className="max-w-5xl mx-auto">
        <div className="relative flex items-end gap-2 bg-muted rounded-2xl p-2 border border-transparent focus-within:border-border focus-within:bg-background transition-colors">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-9 w-9 shrink-0 rounded-xl"
          >
            <Paperclip className="h-5 w-5" />
          </Button>
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息... (Shift+Enter 换行)"
            disabled={!isConnected}
            className={cn(
              'min-h-0 border-0 bg-transparent focus-visible:ring-0 focus-visible:ring-offset-0 resize-none py-2 max-h-48',
              'text-base',
              !isConnected && 'opacity-50 cursor-not-allowed'
            )}
            rows={1}
          />
          {isLoading ? (
            <Button
              type="button"
              onClick={onStop}
              size="icon"
              variant="destructive"
              className="h-9 w-9 shrink-0 rounded-xl"
            >
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon"
              disabled={!input.trim() || !isConnected}
              className="h-9 w-9 shrink-0 rounded-xl bg-bubble-user hover:bg-bubble-user/90"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </div>
        <div className="flex items-center justify-center gap-2 mt-2">
          {isConnected ? (
            <>
              <Wifi className="h-3 w-3 text-green-500" />
              <span className="text-xs text-muted-foreground">
                已连接 · Alpha Agent 可能会犯错，请核实重要信息
              </span>
            </>
          ) : (
            <>
              <WifiOff className="h-3 w-3 text-yellow-500" />
              <span className="text-xs text-muted-foreground">
                等待后端服务连接...
              </span>
            </>
          )}
        </div>
      </div>
    </form>
  )
}
