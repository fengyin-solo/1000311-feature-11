"""气体监测业务规则：状态流转、字段校验与筛选口径都收在这里。

点位的等级、负责人、恢复状态由气体告警联动服务（gas_alarm）作为单一数据源回写，
本服务读取时原样透出，保证告警中心、处置记录、点位详情三处口径一致。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "gas_detect"
REQUIRED_FIELDS = ["点位编号", "监测气体", "所在管沟"]
STATUS_ORDER = ["正常", "预警值", "报警值", "离线"]
ACTION_RULES = {"确认预警": "预警值", "处置报警": "报警值", "恢复在线": "正常"}
NEGATIVE_ACTIONS = []

# 联动回写到点位上的同步字段，列表与详情统一透出
SYNC_FIELDS = ["告警等级", "告警负责人", "恢复状态", "抑制说明", "告警事件id"]


class GasDetectService:
    def _ensure_alarm(self) -> None:
        # 延迟导入，避免与 gas_alarm 服务在模块加载期互相依赖
        from app.services.gas_alarm import gas_alarm_service

        gas_alarm_service.ensure_seed()

    def _with_sync(self, row: dict[str, Any]) -> dict[str, Any]:
        view = dict(row)
        for field in SYNC_FIELDS:
            view.setdefault(field, "")
        return view

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        self._ensure_alarm()
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("点位编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [self._with_sync(row) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        self._ensure_alarm()
        row = store.find(MODULE, entry_id)
        return self._with_sync(row) if row else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"监测点位 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于气体监测可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"监测点位已{action}"
