/**
 * 报表查看页（FR-22 / SDD §3.6）：直渲 snapshot，无过程态、无澄清卡、无保存。
 * 刷新：同步返回 → answer 临时替换快照渲染 / 拒答态 Alert（无重试）/ error。
 * 继续问：POST continue-session → 201 → 跳 /chat/:session_id。
 */
import { App as AntApp, Alert, Button, Skeleton, Space } from 'antd';
import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { continueSession } from '../api/client';
import { useReportStore } from '../store/reportStore';
import RejectMessage from '../components/chat/RejectMessage';
import ResultCard from '../components/chat/ResultCard';
import type { RefreshResponse } from '../api/types';

function RefreshResultView({ result, onRetry }: { result: RefreshResponse; onRetry: () => void }) {
  switch (result.action) {
    case 'answer':
      return (
        <ResultCard
          data={{
            question: result.question,
            table: result.table,
            chart: result.chart,
            insight: result.insight,
            caliber: result.caliber,
            comparison: result.comparison,
            saveable: result.saveable,
          }}
        />
      );
    case 'query_failed':
    case 'query_gen_failed':
    case 'not_answerable':
      // 刷新拒答态：只显文案与建议，无重试按钮（FR-26）
      return (
        <RejectMessage
          payload={{ reason_code: result.reason_code, reason_text: result.reason_text, suggestions: result.suggestions }}
          onSuggest={() => undefined}
          onRetry={() => undefined}
        />
      );
    case 'error':
      return (
        <Alert
          type="error"
          showIcon
          role="alert"
          message={result.message}
          action={result.retryable ? <Button size="small" onClick={onRetry}>重试</Button> : undefined}
        />
      );
    default:
      return null;
  }
}

export default function ReportViewPage() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const detail = useReportStore((s) => s.detail);
  const detailLoading = useReportStore((s) => s.detailLoading);
  const detailError = useReportStore((s) => s.detailError);
  const refreshResult = useReportStore((s) => s.refreshResult);
  const refreshing = useReportStore((s) => s.refreshing);
  const loadDetail = useReportStore((s) => s.loadDetail);
  const refresh = useReportStore((s) => s.refresh);

  useEffect(() => {
    if (reportId) {
      loadDetail(reportId, { onError: (msg) => message.error(msg) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportId]);

  const onContinue = async () => {
    if (!reportId) return;
    try {
      const resp = await continueSession(reportId);
      navigate(`/chat/${resp.session_id}`);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '操作失败，请重试');
    }
  };

  if (detailLoading) {
    return (
      <div className="report-view" data-testid="report-loading">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    );
  }

  if (detailError !== null || detail === null) {
    return (
      <div className="report-view" data-testid="report-not-found">
        <Alert type="warning" showIcon message={detailError ?? '报表不存在'} />
      </div>
    );
  }

  return (
    <div className="report-view" data-testid="report-view">
      <div className="report-view__toolbar">
        <Button onClick={() => navigate('/reports')}>返回列表</Button>
        <Space>
          <Button onClick={onContinue} data-testid="continue-session-btn">
            继续问
          </Button>
          <Button
            type="primary"
            loading={refreshing}
            onClick={() => refresh(reportId as string, { onError: (msg) => message.error(msg) })}
            data-testid="refresh-btn"
          >
            刷新
          </Button>
        </Space>
      </div>
      <h2 className="report-view__title" data-testid="report-title">
        {detail.title}
      </h2>
      {refreshResult !== null ? (
        <RefreshResultView
          result={refreshResult}
          onRetry={() => refresh(reportId as string, { onError: (msg) => message.error(msg) })}
        />
      ) : (
        <ResultCard
          data={{
            question: detail.question,
            table: detail.snapshot.table,
            chart: detail.snapshot.chart,
            insight: detail.snapshot.insight,
            caliber: detail.caliber,
            comparison: detail.snapshot.comparison,
            saveable: false, // 查看页无保存入口；该字段仅满足数据形状
          }}
        />
      )}
    </div>
  );
}
