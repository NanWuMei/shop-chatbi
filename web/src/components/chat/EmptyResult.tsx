/** 空结果（answer 且 rows=[]）：insight 无数据句 + 口径折叠；无图、无空表、无保存入口（F15）。 */
import CaliberPanel from './ResultCard/Caliber';

export default function EmptyResult({ insight, caliber }: { insight: string; caliber: CaliberLike }) {
  return (
    <div className="empty-result" data-testid="empty-result">
      <p className="result-card__insight" data-testid="insight">
        {insight}
      </p>
      <CaliberPanel caliber={caliber} />
    </div>
  );
}

type CaliberLike = Parameters<typeof CaliberPanel>[0]['caliber'];
