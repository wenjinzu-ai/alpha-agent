import { Button } from './Button'
import { Sun, Moon, Monitor } from 'lucide-react'
import { useTheme } from '@/contexts/ThemeContext'
import { cn } from '@/lib/utils'

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  const themes = [
    { value: 'light', icon: Sun, label: '浅色' },
    { value: 'dark', icon: Moon, label: '深色' },
    { value: 'system', icon: Monitor, label: '跟随系统' },
  ] as const

  return (
    <div className="flex items-center gap-1 p-1 rounded-lg bg-muted">
      {themes.map(({ value, icon: Icon, label }) => (
        <Button
          key={value}
          variant="ghost"
          size="icon"
          className={cn(
            'h-8 w-8 rounded-md',
            theme === value && 'bg-background shadow-sm'
          )}
          onClick={() => setTheme(value)}
          title={label}
        >
          <Icon className="h-4 w-4" />
        </Button>
      ))}
    </div>
  )
}
