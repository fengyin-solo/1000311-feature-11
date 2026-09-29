"""气体告警联动处置领域。

在「监测点位 × 监测气体 × 阈值」之上挂一层处置编排（gas_alarm_rules）：
上报读数触发告警时，先按编排找到同一点位的进行中/刚恢复事件，命中以下情形
就不再重复派单，而是并入同一事件并写入抑制说明：

* 同一点位连续抖动（事件处理期间重复上报 / 刚恢复后短时间再次越限）；
* 阈值刚被调整（调整宽限期内的越限读数）；
* 处置人交接（交接宽限期内的越限读数）。

事件（gas_alarm_events）是告警中心、处置记录（gas_alarm_records）和点位详情
三处的唯一数据源：等级、负责人、恢复状态都从事件同步到 gas_detect 点位行，
避免三处各写一份造成不一致。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

# 等级只保留两级；浓度回到预警阈值以下视为恢复正常
LEVEL_NORMAL = "正常"
LEVEL_WARNING = "预警值"
LEVEL_ALARM = "报警值"
LEVEL_ORDER = [LEVEL_NORMAL, LEVEL_WARNING, LEVEL_ALARM]

# 抑制判定窗口（分钟）：读数间隔短=连续抖动；刚恢复/刚调阈值/刚交接也给宽限期
JITTER_GAP_MINUTES = 10
REOPEN_GAP_MINUTES = 30
THRESHOLD_GRACE_MINUTES = 30
HANDOVER_GRACE_MINUTES = 30

# 常见气体的默认编排：预警阈值（%LEL 或 ppm 口径随气体而定）与处置人
DEFAULT_THRESHOLDS: dict[str, tuple[float, float, str, str]] = {
    "甲烷": (10.0, 25.0, "王建国", "强制通风、切断附近气源并复测"),
    "硫化氢": (6.0, 10.0, "李晓峰", "佩戴正压呼吸器、强制通风后排查污水井"),
    "一氧化碳": (24.0, 50.0, "赵海涛", "强制通风、疏散作业人员并查找一氧化碳来源"),
}

RULE_MODULE = "gas_alarm_rules"
EVENT_MODULE = "gas_alarm_events"
RECORD_MODULE = "gas_alarm_records"


def _now() -> datetime:
    return datetime.now()


def _fmt(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _level_of(value: Any, warn: Any, alarm: Any) -> str:
    concentration, warn_at, alarm_at = _to_float(value), _to_float(warn), _to_float(alarm)
    if concentration is None or warn_at is None or alarm_at is None:
        return LEVEL_NORMAL
    if concentration >= alarm_at:
        return LEVEL_ALARM
    if concentration >= warn_at:
        return LEVEL_WARNING
    return LEVEL_NORMAL


class GasAlarmService:
    """处置编排、事件合并与跨视图同步都收口在这一个服务里。"""

    def __init__(self) -> None:
        self._initialized = False

    # ---- 初始化：用现有点位补齐处置编排、活跃事件与点位联动字段 ----
    def ensure_ready(self) -> None:
        """供气体监测模块调用：点位列表/详情读取前先把联动字段挂好。"""
        self._ensure_initialized()

    def bind_new_point(self, point: dict[str, Any]) -> dict[str, Any]:
        """气体监测登记新点位时同步创建处置编排。"""
        self._ensure_initialized()
        rule = self._find_rule(int(point["id"]))
        if rule is None:
            rule = self._create_rule(point)
            store.rows(RULE_MODULE).append(rule)
            point["负责人"] = rule["负责人"]
        return rule

    def apply_manual_status(self, point: dict[str, Any], target: str, action: str) -> None:
        """兼容气体监测页原有的确认预警/处置报警/恢复在线手动动作。

        手动恢复时把进行中的联动事件一并恢复，保证点位与告警中心状态不打架。
        """
        self._ensure_initialized()
        point["status"] = target
        point["点位状态"] = target
        point["pending"] = target not in (LEVEL_NORMAL, "离线")
        point["abnormal"] = target in (LEVEL_WARNING, LEVEL_ALARM)
        active = self._active_event(int(point["id"]))
        if target == LEVEL_NORMAL:
            point["恢复状态"] = "已恢复"
            if active is not None:
                moment = _now()
                self._recover(active, point, moment, active["负责人"], f"点位手动执行「{action}」，联动事件同步恢复")
        elif target in (LEVEL_WARNING, LEVEL_ALARM):
            point["恢复状态"] = "未恢复"
            if active is not None:
                point["关联事件"] = active["事件编号"]
                point["负责人"] = active["负责人"]
                if LEVEL_ORDER.index(target) > LEVEL_ORDER.index(active["等级"]):
                    active["等级"] = target
                    self._sync_point(point, active)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        rules = store.rows(RULE_MODULE)
        points = store.rows("gas_detect")
        for point in points:
            point_id = int(point["id"])
            rule = self._find_rule(point_id)
            if rule is None:
                rule = self._create_rule(point)
                rules.append(rule)
            # 点位行挂上联动字段，三处视图读同一份事件信息
            point["负责人"] = rule["负责人"]
            point["恢复状态"] = "未恢复"
            event = next(
                (row for row in store.rows(EVENT_MODULE) if int(row.get("点位ID", 0)) == point_id and not row["已恢复"]),
                None,
            )
            if point.get("status") in (LEVEL_WARNING, LEVEL_ALARM):
                now = _now()
                if event is None:
                    event = self._new_event(point, rule, point["status"], now, source="设备巡检上报")
                    # 最近一次读数时间沿用点位监测时间；种子数据按北京时间给值，容器可能是 UTC，
                    # 遇到“未来时间”就回退到两小时前，避免第一条演示读数被误判成连续抖动
                    observed_at = self._parse(str(point.get("监测时间") or ""))
                    if observed_at is not None and observed_at > now:
                        observed_at = now - timedelta(hours=2)
                    if observed_at is not None:
                        event["触发时间"] = event["最新上报时间"] = _fmt(observed_at)
                    store.rows(EVENT_MODULE).append(event)
                    self._add_record(event, "告警触发", rule["负责人"], "初始告警", observed_at or now)
                point["关联事件"] = event["事件编号"]
                point["恢复状态"] = "未恢复"
                point["pending"] = True
                point["abnormal"] = True
            else:
                point["关联事件"] = ""
                point["恢复状态"] = "已恢复"
                point["pending"] = False
                point["abnormal"] = False

    def _create_rule(self, point: dict[str, Any]) -> dict[str, Any]:
        gas = str(point.get("监测气体") or "")
        default = next((v for key, v in DEFAULT_THRESHOLDS.items() if key in gas), None)
        if default:
            warn_at, alarm_at, owner, playbook = default
        else:
            warn_at = _to_float(point.get("报警阈值")) or 10.0
            alarm_at = max(warn_at * 2, _to_float(point.get("报警阈值")) or 0)
            owner, playbook = "值班调度员", "现场确认、强制通风并复测"
        return {
            "id": self._next_id(RULE_MODULE),
            "点位ID": int(point["id"]),
            "点位编号": point.get("点位编号", ""),
            "监测气体": gas,
            "预警阈值": warn_at,
            "报警阈值": alarm_at,
            "负责人": owner,
            "处置方式": playbook,
            "调整时间": "",
        }

    def _next_id(self, module: str) -> int:
        return max((int(row.get("id", 0)) for row in store.rows(module)), default=0) + 1

    def _find_rule(self, point_id: int) -> dict[str, Any] | None:
        return next((row for row in store.rows(RULE_MODULE) if int(row.get("点位ID", 0)) == point_id), None)

    def _find_point(self, point_id: int) -> dict[str, Any] | None:
        return store.find("gas_detect", point_id)

    def _active_event(self, point_id: int) -> dict[str, Any] | None:
        return next(
            (
                row
                for row in store.rows(EVENT_MODULE)
                if int(row.get("点位ID", 0)) == point_id and not row["已恢复"]
            ),
            None
        )

    def _last_recovered_event(self, point_id: int) -> dict[str, Any] | None:
        recovered = [
            row
            for row in store.rows(EVENT_MODULE)
            if int(row.get("点位ID", 0)) == point_id and row["已恢复"]
        ]
        return max(recovered, key=lambda row: row.get("恢复时间", ""), default=None)

    def _new_event(
        self, point: dict[str, Any], rule: dict[str, Any], level: str, moment: datetime, *, source: str
    ) -> dict[str, Any]:
        sequence = len(store.rows(EVENT_MODULE)) + 1
        return {
            "id": self._next_id(EVENT_MODULE),
            "事件编号": f"GAS-EVT-{sequence:04d}",
            "点位ID": int(point["id"]),
            "点位编号": point.get("点位编号", ""),
            "所在管沟": point.get("所在管沟", ""),
            "监测气体": rule["监测气体"] or point.get("监测气体", ""),
            "等级": level,
            "负责人": rule["负责人"],
            "处置方式": rule["处置方式"],
            "最新浓度": point.get("当前浓度", ""),
            "触发时间": _fmt(moment),
            "最新上报时间": _fmt(moment),
            "上报来源": source,
            "已恢复": False,
            "恢复时间": "",
            "抑制中": False,
            "抑制说明": "",
            "关联阈值调整": "",
            "重复上报次数": 0,
        }

    def _add_record(
        self,
        event: dict[str, Any],
        kind: str,
        operator: str,
        note: str,
        moment: datetime,
        *,
        suppressed: bool = False,
        level: str = "",
        concentration: Any = None,
    ) -> dict[str, Any]:
        record = {
            "id": self._next_id(RECORD_MODULE),
            "事件编号": event["事件编号"],
            "点位ID": event["点位ID"],
            "点位编号": event["点位编号"],
            "监测气体": event["监测气体"],
            "等级": level or event["等级"],
            "负责人": operator,
            "记录类型": kind,
            "抑制": suppressed,
            "抑制说明": note if suppressed else "",
            "浓度": event["最新浓度"] if concentration is None else concentration,
            "记录时间": _fmt(moment),
            "说明": note,
        }
        store.rows(RECORD_MODULE).append(record)
        return record

    def _parse(self, value: str | None) -> datetime | None:
        if not value:
            return None
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, pattern)
            except ValueError:
                continue
        return None

    def _sync_point(self, point: dict[str, Any], event: dict[str, Any] | None) -> None:
        """事件是唯一数据源：点位详情里的等级、负责人、恢复状态都从这里推过去。"""
        if event is not None and not event["已恢复"]:
            point["status"] = event["等级"]
            point["点位状态"] = event["等级"]
            point["负责人"] = event["负责人"]
            point["关联事件"] = event["事件编号"]
            point["恢复状态"] = "未恢复"
            point["pending"] = True
            point["abnormal"] = True
        else:
            point["status"] = LEVEL_NORMAL
            point["点位状态"] = LEVEL_NORMAL
            point["关联事件"] = event["事件编号"] if event is not None else ""
            point["恢复状态"] = "已恢复"
            point["pending"] = False
            point["abnormal"] = False

    # ---- 处置编排 ----
    def list_rules(self) -> list[dict[str, Any]]:
        self._ensure_initialized()
        return store.rows(RULE_MODULE)

    def adjust_threshold(
        self, point_id: int, warn: Any, alarm: Any, operator: str, reason: str
    ) -> tuple[dict[str, Any] | None, str]:
        self._ensure_initialized()
        point = self._find_point(point_id)
        if point is None:
            return None, f"监测点位 {point_id} 不存在或已归档"
        warn_at, alarm_at = _to_float(warn), _to_float(alarm)
        if warn_at is None or alarm_at is None:
            return None, "预警阈值、报警阈值都必须是数字"
        if not 0 <= warn_at < alarm_at:
            return None, "阈值需要满足 0 ≤ 预警阈值 < 报警阈值"
        rule = self._find_rule(point_id)
        assert rule is not None
        moment = _now()
        rule["预警阈值"], rule["报警阈值"], rule["调整时间"] = warn_at, alarm_at, _fmt(moment)
        point["报警阈值"] = alarm_at
        operator = (operator or "值班调度员").strip() or "值班调度员"
        event = self._active_event(point_id)
        note = (
            f"阈值已由 {operator} 调整：预警 {warn_at}、报警 {alarm_at}"
            f"（{reason or '未填写调整原因'}）；{THRESHOLD_GRACE_MINUTES} 分钟内的越限读数按同一事件抑制"
        )
        if event is not None:
            self._add_record(event, "阈值调整", operator, note, moment)
            event["关联阈值调整"] = _fmt(moment)
            event["抑制中"] = True
            event["抑制说明"] = f"阈值刚于 {_fmt(moment)} 调整，宽限期内重复越限不再新建事件"
        # 调整后立刻按新阈值复核一次当前浓度，保证等级与阈值同步
        current = _level_of(point.get("当前浓度"), warn_at, alarm_at)
        if current == LEVEL_NORMAL and event is not None:
            self._recover(event, point, moment, operator, f"{operator} 调整阈值后读数回落，按新阈值自动恢复")
        return rule, f"{point.get('点位编号')} 阈值已调整，{THRESHOLD_GRACE_MINUTES} 分钟内的抖动会并入同一事件"

    # ---- 读数上报：核心的事件识别与抑制入口 ----
    def ingest_reading(
        self, point_id: int, concentration: Any, source: str, reporter: str
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """返回 (事件, 说明, 是否被抑制)。"""
        self._ensure_initialized()
        point = self._find_point(point_id)
        if point is None:
            return None, f"监测点位 {point_id} 不存在或已归档", False
        value = _to_float(concentration)
        if value is None:
            return None, "上报浓度必须是数字", False
        rule = self._find_rule(point_id)
        assert rule is not None
        moment = _now()
        point["当前浓度"] = value
        point["监测时间"] = _fmt(moment)
        level = _level_of(value, rule["预警阈值"], rule["报警阈值"])

        active = self._active_event(point_id)

        # 读数回落：进行中的事件自动恢复
        if level == LEVEL_NORMAL:
            if active is not None:
                operator = reporter or active["负责人"]
                self._recover(active, point, moment, operator, f"{operator} 上报读数 {value} 回落至阈值以下，自动恢复")
                return active, f"{active['事件编号']} 读数回落，已自动恢复", False
            self._sync_point(point, None)
            return None, "读数正常，无需处置", False

        if active is not None:
            return self._merge_into_active(active, point, rule, level, value, moment, source, reporter)

        # 没有进行中事件：刚恢复就再次越限 = 连续抖动，并入旧事件
        recent = self._last_recovered_event(point_id)
        recovered_at = self._parse(recent.get("恢复时间") if recent else None)
        if recent is not None and recovered_at is not None and moment - recovered_at <= timedelta(minutes=REOPEN_GAP_MINUTES):
            recent["已恢复"] = False
            recent["恢复时间"] = ""
            recent["等级"] = level
            recent["最新浓度"] = value
            recent["最新上报时间"] = _fmt(moment)
            recent["抑制中"] = True
            recent["抑制说明"] = (
                f"同一点位 {REOPEN_GAP_MINUTES} 分钟内再次越限，识别为连续抖动，复用原事件不重复派单"
            )
            point["当前浓度"] = value
            self._sync_point(point, recent)
            self._add_record(
                recent,
                "抑制-连续抖动",
                reporter or recent["负责人"],
                recent["抑制说明"],
                moment,
                suppressed=True,
                level=level,
                concentration=value,
            )
            return recent, f"读数并入 {recent['事件编号']}：{recent['抑制说明']}", True

        # 阈值刚被调整的宽限期内首次越限：登记为抑制中的新事件并给出说明
        adjusted_at = self._parse(rule.get("调整时间"))
        if adjusted_at is not None and moment - adjusted_at <= timedelta(minutes=THRESHOLD_GRACE_MINUTES):
            event = self._new_event(point, rule, level, moment, source=source or "设备上报")
            event["最新浓度"] = value
            event["抑制中"] = True
            event["抑制说明"] = (
                f"阈值刚于 {rule['调整时间']} 调整，{THRESHOLD_GRACE_MINUTES} 分钟宽限期内的首次越限"
                "先登记观察，暂不重复派单"
            )
            store.rows(EVENT_MODULE).append(event)
            self._sync_point(point, event)
            self._add_record(
                event, "抑制-阈值调整", reporter or rule["负责人"], event["抑制说明"], moment,
                suppressed=True, level=level, concentration=value,
            )
            return event, f"已登记 {event['事件编号']}：{event['抑制说明']}", True

        # 全新事件
        event = self._new_event(point, rule, level, moment, source=source or "设备上报")
        event["最新浓度"] = value
        store.rows(EVENT_MODULE).append(event)
        self._sync_point(point, event)
        self._add_record(event, "告警触发", rule["负责人"], f"{rule['监测气体']} 浓度 {value} 达到{level}", moment,
                         level=level, concentration=value)
        return event, f"{event['事件编号']} 已触发{level}，按处置编排派发给 {rule['负责人']}", False

    def _merge_into_active(
        self,
        event: dict[str, Any],
        point: dict[str, Any],
        rule: dict[str, Any],
        level: str,
        value: float,
        moment: datetime,
        source: str,
        reporter: str,
    ) -> tuple[dict[str, Any], str, bool]:
        operator = reporter or event["负责人"]
        # 先取上一次上报时间，再刷新，否则连续抖动的间隔会被算成 0
        last_at = self._parse(event.get("最新上报时间"))
        event["最新浓度"] = value
        event["最新上报时间"] = _fmt(moment)
        if source:
            event["上报来源"] = source

        reason_kind, reason_text = "", ""

        # 1) 阈值刚调整（编排变更是读数变化的直接原因，优先说明）
        adjusted_at = self._parse(rule.get("调整时间"))
        if adjusted_at is not None and moment - adjusted_at <= timedelta(minutes=THRESHOLD_GRACE_MINUTES):
            reason_kind = "抑制-阈值调整"
            reason_text = (
                f"阈值刚于 {rule['调整时间']} 调整，{THRESHOLD_GRACE_MINUTES} 分钟宽限期内的读数"
                "按同一事件观察，不重复派单"
            )

        # 2) 处置人刚交接（按事件负责人最近一次变更判定，记录由 handover 写入）
        handover_record = next(
            (
                row
                for row in reversed(store.rows(RECORD_MODULE))
                if row["事件编号"] == event["事件编号"] and row["记录类型"] == "处置人交接"
            ),
            None,
        )
        handover_at = self._parse(handover_record["记录时间"] if handover_record else None)
        if not reason_text and handover_at is not None and moment - handover_at <= timedelta(minutes=HANDOVER_GRACE_MINUTES):
            reason_kind = "抑制-处置人交接"
            reason_text = (
                f"处置人刚于 {handover_record['记录时间']} 交接给 {event['负责人']}，"
                f"{HANDOVER_GRACE_MINUTES} 分钟内的越限读数仍归同一事件，不重复派单"
            )

        # 3) 同一点位连续抖动：距上一次上报很短（容忍时钟/时区不一致导致的轻微倒挂）
        if (
            not reason_text
            and last_at is not None
            and abs((moment - last_at).total_seconds()) <= JITTER_GAP_MINUTES * 60
        ):
            reason_kind = "抑制-连续抖动"
            reason_text = (
                f"同一点位 {JITTER_GAP_MINUTES} 分钟内重复越限，识别为连续抖动，并入当前事件不重复派单"
            )

        escalated = LEVEL_ORDER.index(level) > LEVEL_ORDER.index(event["等级"])
        if escalated:
            event["等级"] = level
            kind = "等级升级"
            note = f"{operator} 上报浓度 {value}，事件升级为{level}"
            suppressed = False
        elif reason_text:
            kind = reason_kind
            note = reason_text
            suppressed = True
        else:
            kind = "续报读数"
            note = f"{operator} 上报浓度 {value}（{level}），并入当前事件"
            suppressed = False

        event["重复上报次数"] = int(event.get("重复上报次数", 0)) + 1
        event["抑制中"] = suppressed
        event["抑制说明"] = reason_text if suppressed else ""
        self._sync_point(point, event)
        self._add_record(event, kind, operator, note, moment,
                         suppressed=suppressed, level=event["等级"], concentration=value)
        if suppressed:
            return event, f"读数并入 {event['事件编号']}：{reason_text}", True
        if escalated:
            return event, f"{event['事件编号']} 已升级为{level}", False
        return event, f"读数已并入 {event['事件编号']}", False

    def _recover(
        self, event: dict[str, Any], point: dict[str, Any], moment: datetime, operator: str, note: str
    ) -> None:
        event["已恢复"] = True
        event["恢复时间"] = _fmt(moment)
        event["等级"] = LEVEL_NORMAL
        event["抑制中"] = False
        event["抑制说明"] = ""
        self._sync_point(point, event)
        self._add_record(event, "恢复", operator, note, moment, level=LEVEL_NORMAL)

    # ---- 处置动作 ----
    def handover(
        self, event_id: int, to_owner: str, note: str
    ) -> tuple[dict[str, Any] | None, str]:
        self._ensure_initialized()
        event = store.find(EVENT_MODULE, event_id)
        if event is None:
            return None, f"告警事件 {event_id} 不存在"
        if event["已恢复"]:
            return None, f"{event['事件编号']} 已恢复，无需交接"
        to_owner = (to_owner or "").strip()
        if not to_owner:
            return None, "交接必须指定新的负责人"
        moment = _now()
        from_owner = event["负责人"]
        event["负责人"] = to_owner
        event["抑制中"] = True
        event["抑制说明"] = (
            f"处置人刚由 {from_owner} 交接给 {to_owner}，{HANDOVER_GRACE_MINUTES} 分钟内的越限读数"
            "仍归同一事件，不重复派单"
        )
        point = self._find_point(int(event["点位ID"]))
        if point is not None:
            self._sync_point(point, event)
        text = f"处置人由 {from_owner} 交接给 {to_owner}；{note or '未备注'}；交接宽限期内抖动并入本事件"
        self._add_record(event, "处置人交接", to_owner, text, moment)
        return event, f"{event['事件编号']} 已交接给 {to_owner}，宽限期内读数不另立事件"

    def recover_event(
        self, event_id: int, operator: str, note: str
    ) -> tuple[dict[str, Any] | None, str]:
        self._ensure_initialized()
        event = store.find(EVENT_MODULE, event_id)
        if event is None:
            return None, f"告警事件 {event_id} 不存在"
        if event["已恢复"]:
            return None, f"{event['事件编号']} 已处于恢复状态"
        moment = _now()
        point = self._find_point(int(event["点位ID"]))
        if point is None:
            return None, f"监测点位 {event['点位ID']} 不存在或已归档"
        # 若浓度仍越限，恢复会被拦下来，避免状态不一致
        rule = self._find_rule(int(event["点位ID"]))
        level = _level_of(point.get("当前浓度"), rule["预警阈值"], rule["报警阈值"]) if rule else LEVEL_NORMAL
        if level != LEVEL_NORMAL:
            return None, f"当前浓度仍为{level}，请先处置或等待读数回落再恢复"
        operator = (operator or event["负责人"]).strip() or event["负责人"]
        self._recover(event, point, moment, operator, f"{operator} 确认现场安全并恢复：{note or '读数已回落'}")
        return event, f"{event['事件编号']} 已恢复，点位状态同步为正常"

    def dispose_event(
        self, event_id: int, operator: str, action: str, note: str
    ) -> tuple[dict[str, Any] | None, str]:
        self._ensure_initialized()
        event = store.find(EVENT_MODULE, event_id)
        if event is None:
            return None, f"告警事件 {event_id} 不存在"
        if event["已恢复"]:
            return None, f"{event['事件编号']} 已恢复，无需重复处置"
        action = (action or "").strip()
        if not action:
            return None, "请填写现场处置措施"
        moment = _now()
        operator = (operator or event["负责人"]).strip() or event["负责人"]
        event["抑制中"] = False
        event["抑制说明"] = ""
        point = self._find_point(int(event["点位ID"]))
        if point is not None:
            self._sync_point(point, event)
        self._add_record(event, "现场处置", operator, f"处置措施：{action}；{note or '无补充'}", moment)
        return event, f"{event['事件编号']} 处置记录已归档，事件仍由 {event['负责人']} 跟踪"

    # ---- 查询：告警中心 / 处置记录 / 点位详情 ----
    def list_events(
        self,
        *,
        status: str | None = None,
        level: str | None = None,
        keyword: str | None = None,
        include_suppressed: bool = True,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        self._ensure_initialized()
        rows = list(reversed(store.rows(EVENT_MODULE)))
        if status == "未恢复":
            rows = [row for row in rows if not row["已恢复"]]
        elif status == "已恢复":
            rows = [row for row in rows if row["已恢复"]]
        if level:
            rows = [row for row in rows if row["等级"] == level]
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("点位编号", ""))
                or keyword in str(row.get("监测气体", ""))
                or keyword in str(row.get("事件编号", ""))
            ]
        if not include_suppressed:
            rows = [row for row in rows if not row["抑制中"]]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_event(self, event_id: int) -> dict[str, Any] | None:
        self._ensure_initialized()
        return store.find(EVENT_MODULE, event_id)

    def list_records(
        self,
        *,
        event_no: str | None = None,
        point_id: int | None = None,
        suppressed_only: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        self._ensure_initialized()
        rows = list(reversed(store.rows(RECORD_MODULE)))
        if event_no:
            rows = [row for row in rows if row["事件编号"] == event_no]
        if point_id is not None:
            rows = [row for row in rows if int(row.get("点位ID", 0)) == point_id]
        if suppressed_only:
            rows = [row for row in rows if row["抑制"]]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def point_detail(self, point_id: int) -> dict[str, Any] | None:
        """点位详情：等级、负责人、恢复状态直接取当前事件，保证与告警中心一致。"""
        self._ensure_initialized()
        point = self._find_point(point_id)
        if point is None:
            return None
        active = self._active_event(point_id)
        rule = self._find_rule(point_id)
        latest = active or self._last_recovered_event(point_id)
        event_no = latest["事件编号"] if latest is not None else str(point.get("关联事件") or "")
        records, total = self.list_records(point_id=point_id, page=1, size=100)
        return {
            "点位": point,
            "处置编排": rule,
            "当前事件": active,
            "最近事件": latest,
            "等级": active["等级"] if active is not None else LEVEL_NORMAL,
            # 负责人取事件上的最新负责人（交接后也一致），没有事件才回退到编排
            "负责人": (active or latest)["负责人"] if (active or latest) is not None else (rule["负责人"] if rule else ""),
            "恢复状态": "未恢复" if active is not None else "已恢复",
            "关联事件": event_no,
            "处置记录": records,
            "记录总数": total,
        }

    def center_overview(self) -> dict[str, Any]:
        self._ensure_initialized()
        events = store.rows(EVENT_MODULE)
        active = [row for row in events if not row["已恢复"]]
        records = store.rows(RECORD_MODULE)
        return {
            "cards": [
                {"label": "进行中事件", "value": len(active)},
                {"label": "报警值事件", "value": sum(1 for row in active if row["等级"] == LEVEL_ALARM)},
                {"label": "抑制中（同一事件）", "value": sum(1 for row in active if row["抑制中"])},
                {"label": "今日已恢复", "value": sum(1 for row in events if row["已恢复"])},
                {"label": "处置记录", "value": len(records)},
            ],
            "抑制口径": [
                f"同一点位 {JITTER_GAP_MINUTES} 分钟内重复越限，按连续抖动并入当前事件",
                f"恢复后 {REOPEN_GAP_MINUTES} 分钟内再次越限，复用原事件",
                f"阈值调整后 {THRESHOLD_GRACE_MINUTES} 分钟宽限期内的读数不另立事件",
                f"处置人交接后 {HANDOVER_GRACE_MINUTES} 分钟内的读数仍归同一事件",
            ],
        }


gas_alarm_service = GasAlarmService()
