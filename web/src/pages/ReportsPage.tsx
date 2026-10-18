/**
 * 报表列表页（FR-17~19）：本地搜索防抖 300ms、口径摘要列、点击行进查看页、重命名/删除。
 */
import { App as AntApp, Button, Input, Modal, Table } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { ReportListItem } from '../api/types';
import { useReportStore } from '../store/reportStore';
import { formatDateTime, formatTimeRange } from '../utils/format';

export default function ReportsPage() {
  const navigate = useNavigate();
  const { message, modal } = AntApp.useApp();
  const items = useReportStore((s) => s.items);
  const loadList = useReportStore((s) => s.loadList);
  const [keyword, setKeyword] = useState('');
  const [renaming, setRenaming] = useState<ReportListItem | null>(null);
  const [renameTitle, setRenameTitle] = useState('');
  const [renameSubmitting, setRenameSubmitting] = useState(false);

  useEffect(() => {
    loadList('', { onError: (msg) => message.error(msg) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 本地搜索防抖 300ms（FR-18）
  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadList(keyword, { onError: (msg) => message.error(msg) });
    }, 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyword]);

  const doRename = async () => {
    if (renaming === null) return;
    const title = renameTitle.trim();
    if (title === '') return;
    setRenameSubmitting(true);
    const ok = await useReportStore.getState().rename(renaming.id, title, { onError: (msg) => message.error(msg) });
    setRenameSubmitting(false);
    if (ok) {
      setRenaming(null);
      loadList(keyword, { onError: (msg) => message.error(msg) });
    }
  };

  const confirmDelete = (item: ReportListItem) => {
    modal.confirm({
      title: `删除报表《${item.title}》？`,
      content: '删除后不可恢复',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        const ok = await useReportStore.getState().remove(item.id, { onError: (msg) => message.error(msg) });
        if (ok) loadList(keyword, { onError: (msg) => message.error(msg) });
      },
    });
  };

  const columns = [
    {
      title: '名称',
      key: 'title',
      render: (_: unknown, item: ReportListItem) => <Link to={`/reports/${item.id}`}>{item.title}</Link>,
    },
    { title: '口径摘要', key: 'caliber', render: (_: unknown, item: ReportListItem) => item.caliber_summary },
    {
      title: '数据时间范围',
      key: 'range',
      render: (_: unknown, item: ReportListItem) => formatTimeRange(item.data_time_range) || '—',
    },
    {
      title: '查询时间',
      key: 'queried_at',
      render: (_: unknown, item: ReportListItem) => formatDateTime(item.queried_at),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, item: ReportListItem) => (
        <span onClick={(e) => e.stopPropagation()}>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setRenaming(item);
              setRenameTitle(item.title);
            }}
          >
            重命名
          </Button>
          <Button type="link" size="small" danger onClick={() => confirmDelete(item)}>
            删除
          </Button>
        </span>
      ),
    },
  ];

  return (
    <div className="reports-page" data-testid="reports-page">
      <div className="reports-page__toolbar">
        <Input.Search
          placeholder="搜索报表名称"
          allowClear
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          data-testid="report-search"
        />
      </div>
      <Table
        rowKey="id"
        columns={columns}
        dataSource={items}
        pagination={false}
        locale={{ emptyText: '暂无保存的报表' }}
        onRow={(record) => ({
          onClick: () => navigate(`/reports/${record.id}`),
          style: { cursor: 'pointer' },
        })}
        data-testid="report-list"
      />

      <Modal
        open={renaming !== null}
        title="重命名报表"
        okText="保存"
        cancelText="取消"
        confirmLoading={renameSubmitting}
        okButtonProps={{ disabled: renameTitle.trim() === '' }}
        onOk={doRename}
        onCancel={() => setRenaming(null)}
        destroyOnHidden
      >
        <Input value={renameTitle} onChange={(e) => setRenameTitle(e.target.value)} onPressEnter={doRename} autoFocus />
      </Modal>
    </div>
  );
}
