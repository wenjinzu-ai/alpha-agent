import { cn } from '@/lib/utils'
import type { HTMLAttributes, ReactNode } from 'react'

interface AvatarProps extends HTMLAttributes<HTMLDivElement> {
  src?: string
  alt?: string
  fallback?: ReactNode
}

export function Avatar({ className, src, alt, fallback, ...props }: AvatarProps) {
  return (
    <div
      className={cn(
        'relative flex h-9 w-9 shrink-0 overflow-hidden rounded-full bg-muted items-center justify-center',
        className
      )}
      {...props}
    >
      {src ? (
        <img src={src} alt={alt} className="h-full w-full object-cover" />
      ) : (
        <span className="text-sm font-medium text-muted-foreground flex items-center justify-center h-full w-full">
          {fallback}
        </span>
      )}
    </div>
  )
}
