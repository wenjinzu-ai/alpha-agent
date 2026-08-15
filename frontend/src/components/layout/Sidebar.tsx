import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/Button'
import {
  Plus,
  MessageSquare,
  Settings,
  ChevronLeft,
  ChevronRight,
  Trash2,
  Sparkles,
  Search,
  FolderKanban,
} from 'lucide-react'
import type { Conversation } from '@/types/chat'

interface SidebarProps {
  conversations: Conversation[]
  currentConversationId: string | null
  onSelectConversation: (id: string) => void
  onNewConversation: () => void
  onDeleteConversation: (id: string) => void
  collapsed: boolean
  onToggleCollapse: () => void
}

export function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  collapsed,
  onToggleCollapse,
}: SidebarProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  const filteredConversations = conversations.filter((c) =>
    c.title.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div
      className={cn(
        'flex flex-col h-full border-r border-sidebar-border bg-sidebar transition-all duration-300',
        collapsed ? 'w-[60px]' : 'w-[280px]'
      )}
    >
      <div className="p-3 flex items-center justify-between">
        {!collapsed && (
          <div className="flex items-center gap-2 px-2">
            <Sparkles className="h-5 w-5 text-blue-500" />
            <span className="font-semibold text-sidebar-foreground">Alpha Agent</span>
          </div>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={onToggleCollapse}
          className={cn('h-8 w-8', collapsed && 'mx-auto')}
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronLeft className="h-4 w-4" />
          )}
        </Button>
      </div>

      <div className="px-3 pb-2">
        <Button
          onClick={onNewConversation}
          className={cn(
            'w-full gap-2 justify-start bg-sidebar-accent text-sidebar-accent-foreground hover:bg-sidebar-accent/80',
            collapsed && 'justify-center px-0'
          )}
          variant="secondary"
        >
          <Plus className="h-4 w-4" />
          {!collapsed && <span>新建对话</span>}
        </Button>
      </div>

      {!collapsed && (
        <div className="px-3 pb-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="搜索对话..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm bg-transparent border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-ring placeholder:text-muted-foreground"
            />
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-2">
        {!collapsed && (
          <div className="px-2 py-2">
            <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground px-2 py-1">
              <FolderKanban className="h-3 w-3" />
              <span>对话历史</span>
            </div>
          </div>
        )}
        <nav className="space-y-0.5">
          {filteredConversations.map((conv) => (
            <div
              key={conv.id}
              className="relative group"
              onMouseEnter={() => setHoveredId(conv.id)}
              onMouseLeave={() => setHoveredId(null)}
            >
              <Button
                variant="ghost"
                onClick={() => onSelectConversation(conv.id)}
                className={cn(
                  'w-full justify-start gap-2 px-2 h-10 font-normal',
                  collapsed && 'justify-center px-0',
                  currentConversationId === conv.id &&
                    'bg-sidebar-accent text-sidebar-accent-foreground'
                )}
              >
                <MessageSquare className="h-4 w-4 shrink-0" />
                {!collapsed && (
                  <span className="truncate text-sm">{conv.title}</span>
                )}
              </Button>
              {!collapsed && hoveredId === conv.id && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-destructive hover:text-destructive-foreground"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDeleteConversation(conv.id)
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          ))}
        </nav>
      </div>

      <div className="p-3 border-t border-sidebar-border">
        <Button
          variant="ghost"
          className={cn(
            'w-full justify-start gap-2',
            collapsed && 'justify-center px-0'
          )}
        >
          <Settings className="h-4 w-4" />
          {!collapsed && <span>设置</span>}
        </Button>
      </div>
    </div>
  )
}
