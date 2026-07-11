import { BarChart3, TrendingUp, PieChart, Search, Newspaper, ArrowRightLeft } from 'lucide-react'

interface QuickActionsProps {
  onAction: (action: string) => void
}

const ACTIONS = [
  { id: 'analyze', label: '分析个股', desc: '深度分析单只股票', icon: TrendingUp, prompt: '请帮我分析一下' },
  { id: 'compare', label: '对比股票', desc: '多股对比分析', icon: ArrowRightLeft, prompt: '请帮我对比一下' },
  { id: 'screen', label: '选股扫描', desc: '智能筛选优质股', icon: Search, prompt: '请帮我筛选优质股票' },
  { id: 'portfolio', label: '投资组合', desc: '查看持仓组合', icon: PieChart, prompt: '查看我的投资组合' },
  { id: 'backtest', label: '策略回测', desc: '回测交易策略', icon: BarChart3, prompt: '请帮我回测一下' },
  { id: 'news', label: '市场资讯', desc: '最新市场动态', icon: Newspaper, prompt: '最近有什么重要市场新闻' },
]

export default function QuickActions({ onAction }: QuickActionsProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 max-w-[480px]">
      {ACTIONS.map((action) => {
        const Icon = action.icon
        return (
          <button
            key={action.id}
            onClick={() => onAction(action.prompt)}
            className="group flex flex-col items-start gap-1 px-3.5 py-3 rounded-xl border border-[#1e1e1e] hover:border-[#333] bg-[#141414] hover:bg-[#1a1a1a] transition-all duration-200 text-left"
          >
            <Icon size={16} className="text-[#555] group-hover:text-blue-400 transition-colors duration-200" />
            <span className="text-[13px] text-[#bbb] group-hover:text-white transition-colors duration-200 font-medium">{action.label}</span>
            <span className="text-[10px] text-[#444] group-hover:text-[#666] transition-colors duration-200">{action.desc}</span>
          </button>
        )
      })}
    </div>
  )
}