"""气体告警联动处置接口。

分四组：
* 处置编排：查看点位×气体×阈值的编排、调整阈值；
* 读数上报：设备读数入口，内部完成同一事件识别与抑制；
* 告警事件：告警中心列表、交接、现场处置、恢复；
* 处置记录 / 点位详情：与告警中心读同一份事件数据，等级、负责人、恢复状态同步。
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.gas_alarm import gas_alarm_service

router = APIRouter(prefix="/api/gas_alarm", tags=["气体告警联动"])


@router.get("/center")
def center() -> dict:
    """告警中心顶部汇总与抑制口径说明。"""
    return gas_alarm_service.center_overview()


@router.get("/rules", response_model=PageResult[dict])
def list_rules() -> PageResult[dict]:
    """处置编排清单：每个点位的监测气体、双阈值、负责人、处置方式。"""
    items = gas_alarm_service.list_rules()
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


@router.post("/rules/{point_id}/threshold", response_model=ActionResult)
def adjust_threshold(point_id: int, payload: EntryPayload) -> ActionResult:
    """调整某点位的预警/报警阈值；调整后宽限期内的抖动并入同一事件。"""
    values = payload.values
    rule, message = gas_alarm_service.adjust_threshold(
        point_id,
        values.get("warn"),
        values.get("alarm"),
        str(values.get("operator") or ""),
        str(values.get("reason") or payload.remark or ""),
    )
    return ActionResult(ok=rule is not None, message=message, entry=rule)


@router.post("/points/{point_id}/readings", response_model=ActionResult)
def report_reading(point_id: int, payload: EntryPayload) -> ActionResult:
    """设备/巡检上报浓度读数；系统判定新告警、升级、恢复或抑制合并。"""
    values = payload.values
    event, message, suppressed = gas_alarm_service.ingest_reading(
        point_id,
        values.get("concentration"),
        str(values.get("source") or ""),
        str(values.get("reporter") or ""),
    )
    # 抑制属于正常业务结果：ok=True 且 suppressed=True，前端给出抑制说明
    return ActionResult(ok=event is not None or "读数正常" in message, message=message, entry=event, suppressed=suppressed)


@router.get("/events", response_model=PageResult[dict])
def list_events(
    status: str | None = Query(default=None, description="未恢复、已恢复"),
    level: str | None = Query(default=None, description="预警值、报警值"),
    keyword: str | None = None,
    include_suppressed: bool = True,
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """告警中心事件列表，可按恢复状态、等级、点位编号过滤。"""
    items, total = gas_alarm_service.list_events(
        status=status,
        level=level,
        keyword=keyword,
        include_suppressed=include_suppressed,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/events/{event_id}", response_model=dict)
def get_event(event_id: int) -> dict:
    event = gas_alarm_service.get_event(event_id)
    if event is None:
        return {"ok": False, "message": f"告警事件 {event_id} 不存在"}
    return event


@router.post("/events/{event_id}/handover", response_model=ActionResult)
def handover_event(event_id: int, payload: EntryPayload) -> ActionResult:
    """处置人交接：负责人立即同步到告警中心与点位，交接宽限期内抖动并入同一事件。"""
    values = payload.values
    event, message = gas_alarm_service.handover(
        event_id,
        str(values.get("owner") or ""),
        str(values.get("note") or payload.remark or ""),
    )
    return ActionResult(ok=event is not None, message=message, entry=event)


@router.post("/events/{event_id}/dispose", response_model=ActionResult)
def dispose_event(event_id: int, payload: EntryPayload) -> ActionResult:
    """登记现场处置措施，处置记录对告警中心和点位详情同步可见。"""
    values = payload.values
    event, message = gas_alarm_service.dispose_event(
        event_id,
        str(values.get("operator") or ""),
        str(values.get("action") or ""),
        str(values.get("note") or payload.remark or ""),
    )
    return ActionResult(ok=event is not None, message=message, entry=event)


@router.post("/events/{event_id}/recover", response_model=ActionResult)
def recover_event(event_id: int, payload: EntryPayload) -> ActionResult:
    """确认恢复：事件恢复状态、点位状态同步置为正常；浓度仍越限时会被拦下。"""
    values = payload.values
    event, message = gas_alarm_service.recover_event(
        event_id,
        str(values.get("operator") or ""),
        str(values.get("note") or payload.remark or ""),
    )
    return ActionResult(ok=event is not None, message=message, entry=event)


@router.get("/records", response_model=PageResult[dict])
def list_records(
    event_no: str | None = None,
    point_id: int | None = None,
    suppressed_only: bool = False,
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """处置记录时间线，可只看被抑制的重复告警。"""
    items, total = gas_alarm_service.list_records(
        event_no=event_no,
        point_id=point_id,
        suppressed_only=suppressed_only,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/points/{point_id}/detail", response_model=dict)
def point_detail(point_id: int) -> dict:
    """点位详情：编排、当前事件、等级/负责人/恢复状态与处置记录，一处维护多处一致。"""
    detail = gas_alarm_service.point_detail(point_id)
    if detail is None:
        return {"ok": False, "message": f"监测点位 {point_id} 不存在或已归档"}
    return detail
