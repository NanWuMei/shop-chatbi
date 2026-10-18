"""ChainState 黑板 + ChainResult 契约（SDD-算法应用 §6 唯一定义）。

后端 DTO 与前端 TS 类型镜像本文件；字段冲突时改 SDD 本文，前后端跟随。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------
class Action(str, Enum):
    ANSWER = "answer"
    CLARIFY = "clarify"
    NOT_ANSWERABLE = "not_answerable"
    QUERY_GEN_FAILED = "query_gen_failed"
    QUERY_FAILED = "query_failed"
    ERROR = "error"


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    TREND_LINE = "trend_line"
    GROUPED_BAR = "grouped_bar"
    PIE = "pie"


class ClarifyReasonCode(str, Enum):
    METRIC_DIM_AMBIGUOUS = "METRIC_DIM_AMBIGUOUS"
    MISSING_TIME = "MISSING_TIME"
    VAGUE = "VAGUE"
    ANAPHORA_UNRESOLVED = "ANAPHORA_UNRESOLVED"


class RejectionReasonCode(str, Enum):
    # not_answerable
    NOT_DATA_QUESTION = "NOT_DATA_QUESTION"
    NO_MATCHING_DATA = "NO_MATCHING_DATA"
    CALIBER_CONFLICT = "CALIBER_CONFLICT"
    # query_gen_failed
    GEN_LINT_EXHAUSTED = "GEN_LINT_EXHAUSTED"
    # query_failed
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    QUERY_ERROR = "QUERY_ERROR"


class InputType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    TIME_QUICK = "time_quick"
    QUESTION_SUGGESTIONS = "question_suggestions"


class RetrievalMode(str, Enum):
    VECTOR = "vector"
    LEXICAL = "lexical"


class ComparisonMode(str, Enum):
    YOY = "yoy"
    MOM = "mom"
    CUSTOM = "custom"


E_LLM_UNAVAILABLE = "E_LLM_UNAVAILABLE"


# ---------------------------------------------------------------------------
# 中间强类型（节点交接只传这些，不传自然语言中间态）
# ---------------------------------------------------------------------------
class IntentSpec(BaseModel):
    """S1 输出：听懂用户想看什么，不含表/列/日期。"""

    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    time_expr: Optional[str] = None
    comparison_intent: Optional[str] = None  # yoy | mom | custom | None
    filters: list[str] = Field(default_factory=list)
    sort: Optional[str] = None  # 如 "gmv desc"
    top_n: Optional[int] = None
    slot_form: str = "unknown"  # ranking | trend | comparison | share | scalar | judgement
    is_data_question: bool = True
    non_data_kind: Optional[str] = None  # chitchat | attribution | prediction
    unresolved_references: list[str] = Field(default_factory=list)


class SchemaColumn(BaseModel):
    name: str
    type: str = "text"
    comment: str = ""
    is_pk: bool = False
    fk: Optional[str] = None


class SchemaBlock(BaseModel):
    """L0 库结构片段：一张表。"""

    table: str
    comment: str = ""
    columns: list[SchemaColumn] = Field(default_factory=list)
    enum_samples: dict[str, list[str]] = Field(default_factory=dict)

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


class Exemplar(BaseModel):
    id: str
    question: str
    sql: str
    chart_type: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    score: float = 0.0


class RetrievalContext(BaseModel):
    """S3 输出：只作 S4/S5 输入上下文，不作授权、不做事后比对。"""

    schema_blocks: list[SchemaBlock] = Field(default_factory=list)
    caliber_defs: list[dict[str, Any]] = Field(default_factory=list)
    entity_defs: list[dict[str, Any]] = Field(default_factory=list)
    exemplars: list[Exemplar] = Field(default_factory=list)
    mode: RetrievalMode = RetrievalMode.LEXICAL


class MetricSpec(BaseModel):
    name: str  # gmv | conversion_rate | return_rate | aov | 其他业务名
    label: str = ""
    table: str = ""
    expression: str = ""  # 如 SUM(pay_amount - refund_amount)
    agg: str = ""
    fmt: str = "money"  # money | percent | number
    filters: list[str] = Field(default_factory=list)
    caliber_note: str = ""


class DimSpec(BaseModel):
    name: str
    label: str = ""
    table: str = ""
    column: str = ""


class TimeRange(BaseModel):
    start: str = ""
    end: str = ""
    label: str = ""
    inferred: bool = False


class Period(BaseModel):
    key: str
    label: str
    start: str
    end: str


class ComparisonSpec(BaseModel):
    mode: ComparisonMode
    periods: list[Period] = Field(default_factory=list)
    value_fields: list[str] = Field(default_factory=list)


class QuerySpec(BaseModel):
    """S4 输出：Coder 直接可用的无歧义查询规格。"""

    metrics: list[MetricSpec] = Field(default_factory=list)
    dimensions: list[DimSpec] = Field(default_factory=list)
    time_range: Optional[TimeRange] = None
    grain: str = "total"  # total | day
    entity_expansions: list[str] = Field(default_factory=list)
    sort: Optional[str] = None
    limit: Optional[int] = None
    comparison: Optional[ComparisonSpec] = None
    caliber_summary: str = ""
    caliber_filters: list[str] = Field(default_factory=list)


class Lineage(BaseModel):
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    calibers: list[str] = Field(default_factory=list)
    exemplar_ids: list[str] = Field(default_factory=list)


class TemplateMatch(BaseModel):
    hit: bool = False
    template_id: Optional[str] = None
    sql: Optional[str] = None
    chart_type: Optional[ChartType] = None
    bindings: dict[str, Any] = Field(default_factory=dict)


class QueryResult(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False


# ---------------------------------------------------------------------------
# ChainResult 载荷（SDD §6）
# ---------------------------------------------------------------------------
class TableColumn(BaseModel):
    field: str
    label: str
    format: str = "text"  # money | percent | number | text


class TableData(BaseModel):
    columns: list[TableColumn] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    display_limit: int = 500


class ChartSeries(BaseModel):
    field: str
    label: str


class ChartSpec(BaseModel):
    type: ChartType
    x_field: str
    series: list[ChartSeries] = Field(default_factory=list)
    switchable: list[str] = Field(default_factory=list)


class CaliberDetail(BaseModel):
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    time_range: str = ""
    filters: list[str] = Field(default_factory=list)
    comparison: Optional[str] = None


class Caliber(BaseModel):
    summary: str
    detail: CaliberDetail = Field(default_factory=CaliberDetail)


class ComparisonChange(BaseModel):
    key: str
    value_delta: str  # Decimal 序列化为字符串，金额 2 位
    rate_delta: Optional[str] = None  # 率 1 位；分母为 0 → null（不可比）


class ComparisonResult(BaseModel):
    mode: ComparisonMode
    periods: list[str] = Field(default_factory=list)
    changes: list[ComparisonChange] = Field(default_factory=list)


class Answer(BaseModel):
    table: TableData
    chart: Optional[ChartSpec] = None
    insight: str
    caliber: Caliber
    comparison: Optional[ComparisonResult] = None


class ClarifyOption(BaseModel):
    value: str
    label: str


class ClarifySuggestion(BaseModel):
    question: str


class ClarifyPayload(BaseModel):
    clarify_id: str
    round: int  # 1 | 2
    title: str
    reason_code: ClarifyReasonCode
    input_type: InputType
    options: list[ClarifyOption] = Field(default_factory=list)
    suggestions: list[ClarifySuggestion] = Field(default_factory=list)
    allow_custom_text: bool = True


class RejectionSuggestion(BaseModel):
    label: str
    question: str


class Rejection(BaseModel):
    reason_code: RejectionReasonCode
    reason_text: str  # 大白话，不含 SQL/堆栈/技术码
    suggestions: list[RejectionSuggestion] = Field(default_factory=list)


class ErrorPayload(BaseModel):
    code: str
    message: str
    retryable: bool = False


class Trace(BaseModel):
    path: list[str] = Field(default_factory=list)
    template_hit: bool = False
    retrieval_mode: Optional[str] = None
    lint_rounds: int = 0
    llm_calls: int = 0
    elapsed_ms: int = 0
    notes: list[str] = Field(default_factory=list)


class Meta(BaseModel):
    turn_id: str
    question: str


class ChainResult(BaseModel):
    """一次问数返回体的唯一权威定义（SDD §6）。"""

    model_config = ConfigDict(use_enum_values=True)

    action: Action
    answer: Optional[Answer] = None
    clarify: Optional[ClarifyPayload] = None
    rejection: Optional[Rejection] = None
    error: Optional[ErrorPayload] = None
    trace: Trace
    meta: Meta
    # service-only（SDD §6 约定 6 / algorithm-chain OQ-4）：仅落 messages.internal 与报表存储，
    # 禁止出现在任何前端报文；前端 TS 镜像不含这两个字段。
    query_spec: Optional[QuerySpec] = None
    sql: Optional[str] = None

    @model_validator(mode="after")
    def exactly_one_payload(self) -> "ChainResult":
        payloads = {
            "answer": self.answer,
            "clarify": self.clarify,
            "rejection": self.rejection,
            "error": self.error,
        }
        non_null = [k for k, v in payloads.items() if v is not None]
        if len(non_null) != 1:
            raise ValueError(f"ChainResult 必须恰好一个载荷非空，实际: {non_null}")
        expected = {
            Action.ANSWER: "answer",
            Action.CLARIFY: "clarify",
            Action.NOT_ANSWERABLE: "rejection",
            Action.QUERY_GEN_FAILED: "rejection",
            Action.QUERY_FAILED: "rejection",
            Action.ERROR: "error",
        }[Action(self.action)]
        if non_null[0] != expected:
            raise ValueError(f"action={self.action} 应对应载荷 {expected}，实际 {non_null[0]}")
        return self


# ---------------------------------------------------------------------------
# ChainState 黑板（LangGraph 图状态；值均为强类型）
# ---------------------------------------------------------------------------
class ChainState(BaseModel):
    """节点间只传本模型字段，不传自然语言中间态。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    question: str = ""
    clarified_question: Optional[str] = None
    clarify_id: Optional[str] = None
    round: int = 1  # 澄清轮次 1|2
    conversation_summary: str = ""
    # 中段入口（FR-21/22）：start_at=None 主入口 | "S4" recalibrate | "S5" 刷新
    start_at: Optional[str] = None
    recalibrate: bool = False

    intent: Optional[IntentSpec] = None
    template_match: Optional[TemplateMatch] = None
    retrieval: Optional[RetrievalContext] = None
    query_spec: Optional[QuerySpec] = None
    sql: Optional[str] = None
    lineage: Optional[Lineage] = None
    lint_passed: bool = False
    lint_rounds: int = 0
    lint_errors: list[str] = Field(default_factory=list)
    query_result: Optional[QueryResult] = None
    table: Optional[TableData] = None
    chart: Optional[ChartSpec] = None
    comparison_result: Optional[ComparisonResult] = None
    insight: Optional[str] = None
    writer_fallback: bool = False

    final_action: Optional[Action] = None
    clarify_payload: Optional[ClarifyPayload] = None
    rejection: Optional[Rejection] = None
    error: Optional[ErrorPayload] = None

    trace_path: list[str] = Field(default_factory=list)
    trace_notes: list[str] = Field(default_factory=list)
    retrieval_mode: Optional[str] = None
    llm_calls: int = 0
