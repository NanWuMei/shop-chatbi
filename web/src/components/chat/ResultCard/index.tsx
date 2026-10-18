/**
 * 结果卡片五区（固定顺序）：① 解读 → ② 图表（chart=null 不渲染）→ ③ 数据表 → ④ 口径 → ⑤ 操作区。
 * 问数流（AnswerEvent）与报表查看（snapshot 复合）共用本组件（SDD §3/§3.6）。
 */
import { useState } from 'react';
import type { AnswerEvent, Caliber, ChartSpec, ComparisonResult, TableData } from '../../../api/types';
import Actions from './Actions';
import CaliberPanel from './Caliber';
import ChartView from './ChartView';
import DataTable from './DataTable';
import Insight from './Insight';

/** 问数流与报表查看共用的最小数据形状 */
export interface ResultCardData {
  question: string;
  table: TableData;
  chart: ChartSpec | null;
  insight: string;
  caliber: Caliber;
  comparison: ComparisonResult | null;
  saveable: boolean;
}

export function answerToCardData(answer: AnswerEvent): ResultCardData {
  return {
    question: answer.question,
    table: answer.table,
    chart: answer.chart,
    insight: answer.insight,
    caliber: answer.caliber,
    comparison: answer.comparison,
    saveable: answer.saveable,
  };
}

export default function ResultCard({
  data,
  terminal = null,
  clarifyStatus,
  turnId,
  onSave,
  onRecalibrate,
  showActions = false,
}: {
  data: ResultCardData;
  /** 问数流上下文终态（保存置灰判定用）；报表查看页不传 */
  terminal?: Parameters<typeof Actions>[0]['terminal'];
  clarifyStatus?: 'pending' | 'confirmed' | 'cancelled';
  turnId?: string;
  onSave?: () => void;
  onRecalibrate?: (sourceTurnId: string) => void;
  showActions?: boolean;
}) {
  const [chartFailed, setChartFailed] = useState(false);

  return (
    <div className="result-card" data-testid="result-card">
      <Insight text={data.insight} />
      {data.chart !== null && <ChartView chart={data.chart} rows={data.table.rows} onChartFailed={() => setChartFailed(true)} />}
      <DataTable table={data.table} comparison={data.comparison} xField={data.chart?.x_field} />
      <CaliberPanel caliber={data.caliber} />
      {showActions && onSave !== undefined && (
        <Actions
          terminal={terminal}
          saveable={data.saveable}
          chartFailed={chartFailed}
          clarifyStatus={clarifyStatus}
          turnId={turnId}
          onSave={onSave}
          onRecalibrate={onRecalibrate}
        />
      )}
    </div>
  );
}
