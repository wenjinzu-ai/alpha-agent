import { Loader2, CheckCircle2, User } from 'lucide-react'
import type { WorkerProgress as WorkerProgressType } from '../types'

interface WorkerProgressProps {
  workers: WorkerProgressType[]
}

const WORKER_NAMES: Record<string, string> = {
  fundamental: '基本面分析',
  technical: '技术面分析',
  risk_control: '风险控制',
  bull: '多头分析',
  bear: '空头分析',
  judge: '辩论评审',
  data_collector: '数据采集',
  backtest_engineer: '回测工程',
  research_analyst: '研究分析',
}

export default function WorkerProgress({ workers }: WorkerProgressProps) {
  if (workers.length === 0) return null

  return (
    <div className="space-y-1.5 animate-fade-in">
      <div className="text-[11px] text-[#555] font-medium mb-2 px-0.5 flex items-center gap-1.5">
        <div className="w-3 h-3 rounded-full bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-[#2a2a2a] flex items-center justify-center">
          <User size={7} className="text-[#666]" />
        </div>
        Agent 协作流程
      </div>
      <div className="flex flex-wrap gap-1.5">
        {workers.map((worker) => {
          const displayName = WORKER_NAMES[worker.workerName] || worker.workerName
          return (
            <div
              key={worker.workerName}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] border transition-all duration-300 ${
                worker.status === 'running'
                  ? 'bg-blue-500/8 border-blue-500/20 text-blue-400'
                  : 'bg-[#141414] border-[#222] text-[#888]'
              }`}
            >
              {worker.status === 'running' ? (
                <Loader2 size={11} className="animate-spin shrink-0" />
              ) : (
                <CheckCircle2 size={11} className="text-green-500/80 shrink-0" />
              )}
              <span>{displayName}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}