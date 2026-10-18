/** ④ 口径摘要：默认折叠 summary 一行，展开 detail（指标/维度/时间/筛选/对比）（SDD §3 区4）。 */
import { Collapse, Descriptions } from 'antd';
import type { Caliber } from '../../../api/types';

export default function CaliberPanel({ caliber }: { caliber: Caliber }) {
  const d = caliber.detail;
  return (
    <Collapse
      ghost
      size="small"
      className="result-card__caliber"
      items={[
        {
          key: 'caliber',
          label: <span data-testid="caliber-summary">{caliber.summary}</span>,
          children: (
            <Descriptions size="small" column={1} data-testid="caliber-detail">
              <Descriptions.Item label="指标">{d.metrics.join('、') || '—'}</Descriptions.Item>
              <Descriptions.Item label="维度">{d.dimensions.join('、') || '—'}</Descriptions.Item>
              <Descriptions.Item label="时间范围">{d.time_range || '—'}</Descriptions.Item>
              <Descriptions.Item label="筛选">{d.filters.length > 0 ? d.filters.join('；') : '无'}</Descriptions.Item>
              <Descriptions.Item label="对比">{d.comparison ?? '无'}</Descriptions.Item>
            </Descriptions>
          ),
        },
      ]}
    />
  );
}
