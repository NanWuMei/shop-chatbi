/**
 * ③ 数据表：label 列名、format 格式化（千分位/百分比）、前端分页 20/50/100、
 * truncated 横幅、tooltip 显值；rate_delta=null 显"不可比"（AC-8/AC-13）。
 */
import { Alert, Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { ComparisonResult, TableData } from '../../../api/types';
import { formatValue } from '../../../utils/format';

export default function DataTable({
  table,
  comparison,
  xField,
}: {
  table: TableData;
  comparison?: ComparisonResult | null;
  /** comparison.changes 按维度值匹配行用（chart.x_field） */
  xField?: string;
}) {
  const hasDeltaColumn = table.columns.some((c) => c.field === 'value_delta' || c.field === 'rate_delta');
  const changesByKey = new Map((comparison?.changes ?? []).map((c) => [c.key, c]));

  const columns: ColumnsType<Record<string, unknown>> = table.columns.map((col) => ({
    title: col.label,
    dataIndex: col.field,
    key: col.field,
    ellipsis: { showTitle: true },
    render: (value: unknown) => {
      if (value === null || value === undefined) {
        // 不可比：rate_delta=null 原样显示文本，不渲染成 0/∞（F19）
        return col.format === 'percent' ? '不可比' : '';
      }
      return formatValue(value, col.format);
    },
  }));

  // changes 未落在表列里时按普通字段补列（FR-14：作普通字段渲染，不做任何计算）
  if (comparison && !hasDeltaColumn) {
    if (!columns.some((c) => c.key === 'value_delta')) {
      columns.push({
        title: '变化值',
        dataIndex: 'value_delta',
        key: 'value_delta',
        render: (_: unknown, row: Record<string, unknown>) => {
          const change = changesByKey.get(String(row[xField ?? table.columns[0]?.field] ?? ''));
          return change ? formatValue(change.value_delta, 'money') : '';
        },
      });
    }
    columns.push({
      title: '变化率',
      dataIndex: 'rate_delta',
      key: 'rate_delta',
      render: (_: unknown, row: Record<string, unknown>) => {
        const change = changesByKey.get(String(row[xField ?? table.columns[0]?.field] ?? ''));
        if (!change || change.rate_delta === null) return '不可比';
        return `${change.rate_delta}%`;
      },
    });
  }

  return (
    <div className="result-card__table" data-testid="data-table">
      {table.truncated && (
        <Alert type="warning" showIcon message={`仅展示前 ${table.display_limit} 行`} data-testid="truncated-banner" />
      )}
      <Table
        size="small"
        columns={columns}
        dataSource={table.rows}
        rowKey={(_, idx) => String(idx)}
        pagination={{ defaultPageSize: 20, pageSizeOptions: ['20', '50', '100'], showSizeChanger: true, showTotal: (n) => `共 ${n} 行` }}
      />
    </div>
  );
}
