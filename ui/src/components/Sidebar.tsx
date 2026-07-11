import { useEffect, useRef } from 'react'
import { Plus, Trash2, MessageSquare, Loader2, PanelLeftClose, PanelLeft, Sparkles, Search, Clock } from 'lucide-react'
import type { Conversation } from '../types'

interface SidebarProps {
  conversations: Conversation[]
  loading: boolean
  activeId: string | null
  collapsed: boolean
  onToggle: () => void
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
}

function relativeTime(dateStr: string): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  if (hours < 24) return `${hours}小时前`
  if (days < 7) return `${days}天前`
  return date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

export default function Sidebar({
  conversations,
  loading,
  activeId,
  collapsed,
  onToggle,
  onSelect,
  onNew,
  onDelete,
}: SidebarProps) {
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (activeId && listRef.current) {
      const el = listRef.current.querySelector(`[data-id="${activeId}"]`)
      el?.scrollIntoView({ block: 'nearest' })
    }
  }, [activeId])

  return (
    <aside
      className={`flex flex-col bg-[#111111] border-r border-[#1e1e1e] transition-all duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] ${
        collapsed ? 'w-0 overflow-hidden border-r-0' : 'w-[272px]'
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 h-14 shrink-0 border-b border-[#1a1a1a]">
        <div className="flex items-center gap-2.5">
          <div className="relative w-7 h-7">
            <div className="absolute inset-0 rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 opacity-80 blur-[2px]" />
            <div className="relative w-full h-full rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center">
              <Sparkles size={14} className="text-white" />
            </div>
          </div>
          <div className="flex flex-col leading-none">
            <span className="font-semibold text-[13px] text-white tracking-tight">Investment</span>
            <span className="text-[10px] text-[#555] font-medium">Agent v0.3</span>
          </div>
        </div>
        <button
          onClick={onToggle}
          className="p-1.5 rounded-lg hover:bg-[#1e1e1e] text-[#666] hover:text-[#aaa] transition-all duration-200"
        >
          <PanelLeftClose size={15} />
        </button>
      </div>

      {/* New Chat Button */}
      <div className="px-3 pt-3 pb-2">
        <button
          onClick={onNew}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-[#222] hover:border-[#333] bg-[#141414] hover:bg-[#1a1a1a] text-[#aaa] hover:text-white text-[13px] font-medium transition-all duration-200 group"
        >
          <div className="w-5 h-5 rounded-md bg-[#1e1e1e] group-hover:bg-[#2a2a2a] flex items-center justify-center transition-colors duration-200">
            <Plus size={12} className="text-[#888] group-hover:text-white transition-colors duration-200" />
          </div>
          <span>新对话</span>
          <kbd className="ml-auto text-[10px] text-[#444] font-mono bg-[#1a1a1a] border border-[#222] rounded-md px-1.5 py-0.5 group-hover:border-[#333] transition-colors duration-200">
            ⌘K
          </kbd>
        </button>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#444]" />
          <input
            type="text"
            placeholder="搜索对话..."
            className="w-full bg-[#141414] border border-[#1e1e1e] rounded-lg pl-7 pr-3 py-1.5 text-[11px] text-[#aaa] placeholder-[#444] outline-none focus:border-[#333] focus:bg-[#181818] transition-all duration-200"
          />
        </div>
      </div>

      {/* Conversation List */}
      <div ref={listRef} className="flex-1 overflow-y-auto px-2 py-0.5 space-y-0.5">
        <div className="px-2 py-1.5">
          <span className="text-[10px] font-medium text-[#444] uppercase tracking-wider">最近对话</span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={16} className="text-[#444] animate-spin" />
          </div>
        ) : conversations.length === 0 ? (
          <div className="text-center py-12 px-4">
            <div className="w-10 h-10 rounded-xl bg-[#1a1a1a] border border-[#222] flex items-center justify-center mx-auto mb-3">
              <MessageSquare size={18} className="text-[#444]" />
            </div>
            <p className="text-[11px] text-[#444]">暂无对话记录</p>
            <p className="text-[10px] text-[#333] mt-0.5">开始你的第一次分析</p>
          </div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.session_id}
              data-id={conv.session_id}
              onClick={() => onSelect(conv.session_id)}
              className={`group relative flex items-start gap-2.5 px-2.5 py-2 rounded-lg cursor-pointer transition-all duration-200 ${
                activeId === conv.session_id
                  ? 'bg-[#1a1a1a]'
                  : 'hover:bg-[#151515]'
              }`}
            >
              {/* Active indicator */}
              {activeId === conv.session_id && (
                <div className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full bg-blue-500" />
              )}

              <div className={`w-6 h-6 rounded-md flex items-center justify-center shrink-0 mt-px transition-colors duration-200 ${
                activeId === conv.session_id
                  ? 'bg-blue-500/10 text-blue-400'
                  : 'bg-[#1a1a1a] text-[#555] group-hover:bg-[#1e1e1e] group-hover:text-[#888]'
              }`}>
                <MessageSquare size={12} />
              </div>

              <div className="flex-1 min-w-0">
                <p className={`text-[12px] leading-snug line-clamp-2 transition-colors duration-200 ${
                  activeId === conv.session_id ? 'text-[#ddd]' : 'text-[#999] group-hover:text-[#bbb]'
                }`}>
                  {conv.user_query || '新对话'}
                </p>
                <div className="flex items-center gap-2 mt-1.5">
                  <Clock size={10} className="text-[#444] shrink-0" />
                  <span className="text-[10px] text-[#444]">
                    {relativeTime(conv.created_at)}
                  </span>
                  {conv.status === 'running' && (
                    <span className="text-[10px] px-1.5 py-px rounded-full bg-yellow-500/10 text-yellow-600/80 font-medium">
                      进行中
                    </span>
                  )}
                  {conv.status === 'completed' && (
                    <span className="text-[10px] text-[#444]">
                      {conv.total_steps}步
                    </span>
                  )}
                </div>
              </div>

              <button
                onClick={(e) => { e.stopPropagation(); onDelete(conv.session_id) }}
                className="opacity-0 group-hover:opacity-100 p-1 rounded-md hover:bg-[#222] text-[#555] hover:text-red-400 transition-all duration-200 shrink-0 mt-px"
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2.5 border-t border-[#1a1a1a]">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-green-500/60" />
          <span className="text-[10px] text-[#444]">系统运行中</span>
        </div>
      </div>
    </aside>
  )
}

export function SidebarToggle({ collapsed, onClick }: { collapsed: boolean; onClick: () => void }) {
  if (!collapsed) return null
  return (
    <button
      onClick={onClick}
      className="fixed left-3 top-3 z-50 p-2.5 rounded-xl bg-[#151515] border border-[#1e1e1e] text-[#666] hover:text-white hover:bg-[#1e1e1e] hover:border-[#333] transition-all duration-200 shadow-lg shadow-black/20"
    >
      <PanelLeft size={17} />
    </button>
  )
}