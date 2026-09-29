"""气体告警联动处置接口。

在监测点位、监测气体与阈值之间提供处置编排，并围绕「读数上报 → 事件定级 → 抑制合并 →
现场处置 → 恢复」给出一组接口。告警中心、处置记录、点位详情共用同一份事件数据。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.schemas import ActionResult, PageResult
from app.services.gas_alarm import gas_alarm_service

router = APIRouter(prefix="/api/gas_alarm", tags=["气体告警联动"])


class RulePayload(BaseModel):
    values: dict[str, Any]


class ReadingPayload(BaseModel):
    浓度: float | None = None
    concentration: float | None = None
    操作人: str | None = None
    operator: str | None = None


class HandlePayload(BaseModel):
    action: str = "处置"
    operator: str | None = None
    操作人: str | None = None
    note: str | None = None
    说明: str | None = None


class HandoverPayload(BaseModel):
    owner: str
    operator: str | None = None


def _started() -> None:
    gas_alarm_service.ensure_seed()


@router.get("/summary")
def summary() -> dict[str, Any]:
    """告警中心顶部统计：活动/报警/预警/恢复/抑制读数数量。"""
    _started()
    return gas_alarm_service.summary()


@router.get("/rules")
def list_rules(keyword: str | None = None) -> dict[str, Any]:
    """处置编排清单：点位 × 气体 × 阈值与负责人。"""
    _started()
    return {"items": gas_alarm_service.list_rules(keyword=keyword)}


@router.post("/rules", response_model=ActionResult)
def save_rule(payload: RulePayload) -> ActionResult:
    """建立或调整处置编排；阈值被调整时记录调整时间，供事件引擎做调阈抑制。"""
    _started()
    rule, message = gas_alarm_service.save_rule(payload.values)
    if rule is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=rule)


@router.get("/events", response_model=PageResult[dict])
def list_events(
    status: str | None = Query(default=None, description="处置中、已恢复或未恢复"),
    level: str | None = Query(default=None, description="预警、报警"),
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """告警中心事件列表，可按恢复状态、等级与点位/事件编号过滤。"""
    _started()
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = gas_alarm_service.list_events(status=status, level=level, keyword=keyword, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/events/{event_id}")
def get_event(event_id: int) -> dict[str, Any]:
    """事件详情附带处置记录时间线。"""
    _started()
    items, _ = gas_alarm_service.list_records(event_id=event_id, page=1, size=100)
    from app.store import store

    event = store.find("gas_alarm_event", event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"告警事件 {event_id} 不存在或已归档")
    return {"event": gas_alarm_service._event_view(event), "records": items}


@router.post("/points/{code}/readings", response_model=ActionResult)
def report_reading(code: str, payload: ReadingPayload) -> ActionResult:
    """上报一次浓度读数，驱动事件引擎定级、抑制或恢复。"""
    _started()
    concentration = payload.浓度 if payload.浓度 is not None else payload.concentration
    operator = payload.操作人 or payload.operator
    if concentration is None:
        return ActionResult(ok=False, message="缺少浓度读数，无法判定告警")
    view, message = gas_alarm_service.ingest_reading(code, float(concentration), operator=operator)
    if view is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=view)


@router.post("/events/{event_id}/actions", response_model=ActionResult)
def handle_event(event_id: int, payload: HandlePayload) -> ActionResult:
    """现场处置或确认恢复；恢复后点位等级、负责人、恢复状态同步更新。"""
    _started()
    note = payload.note or payload.说明 or ""
    operator = payload.operator or payload.操作人
    view, message = gas_alarm_service.handle_event(event_id, payload.action, operator=operator, note=note)
    if view is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=view)


@router.post("/events/{event_id}/handover", response_model=ActionResult)
def handover_event(event_id: int, payload: HandoverPayload) -> ActionResult:
    """处置人交接：识别为同一事件，负责人同步更新并给出抑制说明。"""
    _started()
    view, message = gas_alarm_service.handover_event(event_id, payload.owner, operator=payload.operator)
    if view is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=view)


@router.get("/records", response_model=PageResult[dict])
def list_records(
    event_id: int | None = None,
    point: str | None = Query(default=None, description="按点位编号过滤"),
    suppressed: bool | None = Query(default=None, description="只看抑制/非抑制记录"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """处置记录：等级、负责人、恢复状态与事件实时同步。"""
    _started()
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = gas_alarm_service.list_records(event_id=event_id, code=point, suppressed=suppressed, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/points/{code}/detail")
def point_detail(code: str) -> dict[str, Any]:
    """点位详情：点位、处置编排、活动事件、最近记录一次取齐。"""
    _started()
    detail = gas_alarm_service.point_detail(code)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"监测点位 {code} 不存在或已归档")
    return detail
