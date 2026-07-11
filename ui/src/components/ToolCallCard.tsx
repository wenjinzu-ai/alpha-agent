import { useState } from 'react'
import { Wrench, ChevronDown, ChevronRight, Loader2, CheckCircle2 } from 'lucide-react'
import type { ToolCall } from '../types'

interface ToolCallCardProps {
  toolCall: ToolCall
}

const TOOL_NAMES: Record<string, string> = {
  get_stock_info: '获取股票信息',
  get_stock_kline: '获取K线数据',
  get_stock_financials: '获取财务数据',
  analyze_stock: '全面分析股票',
  compare_stocks: '股票对比',
  screen_stocks: '选股扫描',
  get_news: '获取新闻',
  search_web: '网络搜索',
  backtest: '策略回测',
  query_data: '数据查询',
  get_portfolio: '查看组合',
  add_to_portfolio: '添加持仓',
  set_alert: '设置告警',
}

export default function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false)
  const displayName = TOOL_NAMES[toolCall.name] || toolCall.name

  return (
    <div className="rounded-xl border border-[#1e1e1e] bg-[#111] overflow-hidden animate-fade-in transition-all duration-200 hover:border-[#2a2a2a]">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-[12px] hover:bg-[#161616] transition-colors"
      >
        <div className={`w-5 h-5 rounded-md flex items-center justify-center shrink-0 ${
          toolCall.status === 'running' ? 'bg-blue-500/10' : 'bg-green-500/10'
        }`}>
          {toolCall.status === 'running' ? (
            <Loader2 size={11} className="text-blue-400 animate-spin" />
          ) : (
            <CheckCircle2 size={11} className="text-green-500/80" />
          )}
        </div>
        <Wrench size={11} className="text-[#555] shrink-0" />
        <span className="text-[#bbb]">{displayName}</span>
        <span className="text-[#444] ml-auto text-[11px]">
          {toolCall.status === 'running' ? '执行中...' : '完成'}
        </span>
        {expanded ? <ChevronDown size={12} className="text-[#555]" /> : <ChevronRight size={12} className="text-[#555]" />}
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2 border-t border-[#1e1e1e]">
          <div>
            <div className="text-[10px] text-[#555] mb-1 font-medium">参数</div>
            <pre className="text-[11px] bg-[#0d0d0d] text-[#888] rounded-lg p-2.5 overflow-x-auto border border-[#1e1e1e]">
              {JSON.stringify(toolCall.args, null, 2)}
            </pre>
          </div>
          {toolCall.result && (
            <div>
              <div className="text-[10px] text-[#555] mb-1 font-medium">结果</div>
              <pre className="text-[11px] bg-[#0d0d0d] text-[#888] rounded-lg p-2.5 overflow-x-auto max-h-36 overflow-y-auto border border-[#1e1e1e]">
                {toolCall.result.length > 500 ? toolCall.result.slice(0, 500) + '...' : toolCall.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}