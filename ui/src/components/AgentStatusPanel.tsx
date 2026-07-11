import { Activity, CheckCircle2, Loader2, AlertCircle, Brain, Wrench, ChevronDown, ChevronRight, Zap, Clock, PanelRightClose, PanelRight, MessageSquare, Square } from 'lucide-react'
import { useState, useRef, useEffect } from 'react'
import type { AgentStep, AgentInfo, AgentOutputLine } from '../types'

interface AgentStatusPanelProps {
  agents: AgentInfo[]
  steps: AgentStep[]
  isStreaming: boolean
  totalStepCount: number
  collapsed: boolean
  onToggle: () => void
  onStop?: () => void
}

const AGENT_COLORS: Record<string, string> = {
  fundamental: '#3b82f6',
  technical: '#a855f7',
  risk_control: '#ef4444',
  bull: '#22c55e',
  bear: '#f97316',
  judge: '#eab308',
  data_collector: '#06b6d4',
  backtest_engineer: '#6366f1',
  research_analyst: '#14b8a6',
}

const STEP_ICONS: Record<string, typeof Brain> = {
  plan: Zap,
  worker_start: Activity,
  worker_thought: Brain,
  worker_tool_call: Wrench,
  worker_tool_result: Wrench,
  worker_done: CheckCircle2,
  synthesizing: Brain,
  final: CheckCircle2,
  error: AlertCircle,
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

const OUTPUT_LINE_ICONS: Record<AgentOutputLine['type'], typeof Brain> = {
  thought: Brain,
  tool_call: Wrench,
  tool_result: Wrench,
  content: MessageSquare,
}

function AgentOutputView({ lines, isRunning }: { lines: AgentOutputLine[]; isRunning: boolean }) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [lines.length])

  if (lines.length === 0 && !isRunning) return null

  return (
    <div
      ref={scrollRef}
      className="mt-2 max-h-[140px] overflow-y-auto rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-[11px]"
    >
      {lines.length === 0 && isRunning && (
        <div className="px-2.5 py-2 text-[#555] flex items-center gap-1.5">
          <Loader2 size={10} className="animate-spin" />
          等待输出...
        </div>
      )}
      {lines.map((line, i) => {
        const Icon = OUTPUT_LINE_ICONS[line.type] || Activity
        const isLast = i === lines.length - 1
        return (
          <div
            key={i}
            className={`flex items-start gap-1.5 px-2.5 py-1.5 ${
              line.type === 'tool_result' ? 'text-[#666]' :
              line.type === 'tool_call' ? 'text-[#888]' :
              line.type === 'thought' ? 'text-[#999]' :
              'text-[#aaa]'
            } ${isLast && isRunning ? 'animate-fade-in-fast' : ''}`}
          >
            <Icon size={10} className="mt-0.5 shrink-0 opacity-50" />
            <span className="break-all leading-relaxed font-mono">{line.content}</span>
          </div>
        )
      })}
      {isRunning && (
        <div className="flex items-center gap-1 px-2.5 py-1.5 text-[#555]">
          <span className="inline-block w-1 h-2.5 bg-current animate-pulse rounded-sm" />
        </div>
      )}
    </div>
  )
}

export default function AgentStatusPanel({ agents, steps, isStreaming, totalStepCount, collapsed, onToggle, onStop }: AgentStatusPanelProps) {
  const [expanded, setExpanded] = useState(true)
  const [stepsExpanded, setStepsExpanded] = useState(true)

  const runningAgents = agents.filter(a => a.status === 'running')
  const doneAgents = agents.filter(a => a.status === 'done')

  // 折叠状态
  if (collapsed) {
    return (
      <button
        onClick={onToggle}
        className="shrink-0 w-10 bg-[#111] border-l border-[#1e1e1e] flex flex-col items-center pt-3 hover:bg-[#161616] transition-colors duration-200"
        title="展开运行面板"
      >
        <PanelRight size={15} className="text-[#666] hover:text-white transition-colors duration-200" />
        {isStreaming && (
          <div className="mt-2 w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
        )}
        {totalStepCount > 0 && (
          <span className="mt-1 text-[9px] text-[#555] tabular-nums [writing-mode:vertical-lr]">{totalStepCount}步</span>
        )}
      </button>
    )
  }

  return (
    <aside className="w-[280px] shrink-0 bg-[#111] border-l border-[#1e1e1e] flex flex-col h-full overflow-hidden transition-all duration-300">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[#1a1a1a] shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${isStreaming ? 'bg-blue-500 animate-pulse' : agents.length > 0 ? 'bg-emerald-500/60' : 'bg-[#333]'}`} />
            <span className="text-[12px] font-medium text-[#ccc]">
              {isStreaming ? '运行中' : agents.length > 0 ? '已完成' : '运行面板'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {totalStepCount > 0 && (
              <span className="text-[11px] text-[#666] tabular-nums">{totalStepCount} 步</span>
            )}
            {isStreaming && onStop && (
              <button
                onClick={onStop}
                className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium text-[#ef4444] bg-[#ef4444]/10 hover:bg-[#ef4444]/20 border border-[#ef4444]/20 transition-all duration-200"
                title="停止执行"
              >
                <Square size={10} fill="currentColor" />
                停止
              </button>
            )}
            <button
              onClick={onToggle}
              className="p-1.5 rounded-lg hover:bg-[#1e1e1e] text-[#555] hover:text-[#aaa] transition-all duration-200"
              title="收起面板"
            >
              <PanelRightClose size={14} />
            </button>
          </div>
        </div>
        {isStreaming && runningAgents.length > 0 && (
          <div className="mt-2 text-[11px] text-[#666] truncate">
            当前: {runningAgents.map(a => a.displayName).join(' → ')}
          </div>
        )}
      </div>

      {/* Agent Cards with Streaming Output */}
      {agents.length > 0 && (
        <div className="shrink-0 border-b border-[#1a1a1a]">
          <button
            onClick={() => setExpanded(!expanded)}
            className="w-full flex items-center justify-between px-4 py-2 hover:bg-[#161616] transition-colors"
          >
            <span className="text-[11px] text-[#555] font-medium uppercase tracking-wider">智能体</span>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-[#444]">{doneAgents.length}/{agents.length}</span>
              {expanded ? <ChevronDown size={12} className="text-[#555]" /> : <ChevronRight size={12} className="text-[#555]" />}
            </div>
          </button>

          {expanded && (
            <div className="px-3 pb-3 space-y-2">
              {agents.map((agent) => {
                const color = AGENT_COLORS[agent.name] || agent.color || '#666'
                const isRunning = agent.status === 'running'
                const isDone = agent.status === 'done'
                const duration = isDone && agent.finishedAt
                  ? formatDuration(agent.finishedAt - agent.startedAt)
                  : isRunning
                    ? formatDuration(Date.now() - agent.startedAt)
                    : ''

                return (
                  <div
                    key={agent.name}
                    className={`rounded-xl border p-3 transition-all duration-300 ${
                      isRunning
                        ? 'bg-[#141414] border-[#2a2a2a]'
                        : 'bg-[#0f0f0f] border-[#1a1a1a]'
                    }`}
                  >
                    {/* Agent header */}
                    <div className="flex items-center gap-2.5">
                      <div
                        className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                        style={{ backgroundColor: `${color}12`, border: `1px solid ${color}25` }}
                      >
                        {isRunning ? (
                          <Loader2 size={14} className="animate-spin" style={{ color }} />
                        ) : isDone ? (
                          <CheckCircle2 size={14} style={{ color }} />
                        ) : (
                          <AlertCircle size={14} style={{ color }} />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className={`text-[12px] font-medium truncate ${isRunning ? 'text-white' : 'text-[#aaa]'}`}>
                            {agent.displayName}
                          </span>
                          {duration && (
                            <span className="text-[10px] text-[#555] tabular-nums shrink-0">{duration}</span>
                          )}
                        </div>
                        <p className="text-[11px] text-[#666] truncate mt-0.5">
                          {agent.currentAction || (isDone ? '分析完成' : '等待调度')}
                        </p>
                      </div>
                    </div>

                    {/* Progress bar */}
                    {isRunning && (
                      <div className="mt-2.5 h-[2px] rounded-full bg-[#1a1a1a] overflow-hidden">
                        <div
                          className="h-full rounded-full opacity-60"
                          style={{
                            background: `linear-gradient(90deg, ${color}00, ${color}, ${color}00)`,
                            backgroundSize: '200% 100%',
                            animation: 'shimmer 2s ease-in-out infinite',
                          }}
                        />
                      </div>
                    )}

                    {/* Streaming output */}
                    <AgentOutputView lines={agent.outputLines} isRunning={isRunning} />

                    {/* Done indicator */}
                    {isDone && agent.totalSteps > 0 && (
                      <div className="mt-2 flex items-center gap-1">
                        <Clock size={10} className="text-[#555]" />
                        <span className="text-[10px] text-[#555]">{agent.totalSteps} 步完成</span>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Step Timeline */}
      <div className="flex-1 overflow-y-auto">
        <button
          onClick={() => setStepsExpanded(!stepsExpanded)}
          className="w-full flex items-center justify-between px-4 py-2 hover:bg-[#161616] transition-colors sticky top-0 bg-[#111] z-10"
        >
          <span className="text-[11px] text-[#555] font-medium uppercase tracking-wider">执行步骤</span>
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-[#444]">{steps.length}</span>
            {stepsExpanded ? <ChevronDown size={12} className="text-[#555]" /> : <ChevronRight size={12} className="text-[#555]" />}
          </div>
        </button>

        {stepsExpanded && (
          <div className="px-3 pb-3">
            {steps.length === 0 ? (
              <div className="text-center py-6">
                <div className="thinking-dots flex items-center justify-center gap-1.5 mb-2">
                  <span /><span /><span />
                </div>
                <p className="text-[11px] text-[#444]">等待执行...</p>
              </div>
            ) : (
              <div className="relative">
                <div className="absolute left-[15px] top-2 bottom-2 w-px bg-[#1e1e1e]" />

                {steps.map((step) => {
                  const Icon = STEP_ICONS[step.type] || Activity
                  const isRunning = step.status === 'running'
                  const isDone = step.status === 'done'
                  const isError = step.status === 'error'
                  const agentColor = step.workerName ? (AGENT_COLORS[step.workerName] || step.color || '#666') : '#666'

                  return (
                    <div key={step.id} className="relative flex gap-2.5 py-1.5 animate-fade-in-fast">
                      <div className="relative z-10 w-[7px] h-[7px] rounded-full mt-1.5 shrink-0 mx-auto" style={{
                        left: '-4px',
                        backgroundColor: isError ? '#ef4444' : isRunning ? agentColor : isDone ? '#22c55e80' : '#333',
                        boxShadow: isRunning ? `0 0 6px ${agentColor}60` : 'none',
                      }} />

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <Icon size={10} className={isError ? 'text-red-400' : isRunning ? 'text-[#888]' : 'text-[#555]'} />
                          <span className={`text-[11px] truncate ${isRunning ? 'text-[#bbb]' : isDone ? 'text-[#777]' : 'text-red-400'}`}>
                            {step.displayName ? `${step.displayName}` : step.type}
                          </span>
                          {step.step !== undefined && step.step > 0 && (
                            <span className="text-[9px] text-[#444] tabular-nums shrink-0">#{step.step}</span>
                          )}
                        </div>
                        {step.content && (
                          <p className={`text-[10px] mt-0.5 truncate ${isRunning ? 'text-[#666]' : 'text-[#444]'}`}>
                            {step.content}
                          </p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </aside>
  )
}
