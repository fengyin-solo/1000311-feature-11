"""气体告警联动处置业务规则。

监测点位 × 监测气体 × 阈值三者之间挂一份「处置编排」：读数上报后按编排匹配阈值定级，
同一点位同一气体的活动事件会被识别为同一事件并做抖动/调阈/交接抑制。告警中心、处置
记录、点位详情三处看到的等级、负责人、恢复状态都从这里的单一数据派生，避免各写一份。

状态流转只能在本服务里改，路由层不做业务判断。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

POINT_MODULE = "gas_detect"
RULE_MODULE = "gas_alarm_rule"
EVENT_MODULE = "gas_alarm_event"
RECORD_MODULE = "gas_alarm_record"

# 读数在活动事件发生后多久内回到阈值以下，视为同一事件的恢复
RECOVER_WINDOW = timedelta(minutes=30)
# 阈值调整后多久内再次越限，视为「阈值刚被调整」而非新事件
THRESHOLD_WINDOW = timedelta(minutes=10)

LEVEL_ORDER = ["正常", "预警", "报警"]
EVENT_OPEN = "处置中"
EVENT_RECOVERED = "已恢复"

RECORD_REPORT = "读数上报"
RECORD_SUPPRESS = "抖动抑制"
RECORD_ESCALATE = "等级升级"
RECORD_THRESHOLD = "阈值调整"
RECORD_HANDOVER = "负责人交接"
RECORD_ACTION = "现场处置"
RECORD_RECOVER = "自动恢复"

DEFAULT_OWNER = "值班长"
DEFAULT_NOTIFY = "工单提醒"


def _now() -> datetime:
    return datetime.now()


def _fmt(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _parse(value: Any) -> float | None:
    """把「当前浓度」解析成数值；示例数据里可能是占位文字，解析不了就返回 None。"""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


class GasAlarmService:
    # ---------------------------------------------------------------- 初始化
    def ensure_seed(self) -> None:
        """第一次使用时补齐编排与事件示例数据；之后内存仓库里已有数据就不再重建。"""
        if not store.rows(RULE_MODULE):
            store.rows(RULE_MODULE).extend([
                {
                    "id": 1,
                    "点位编号": "GAS-0001",
                    "监测气体": "甲烷",
                    "预警阈值": 25.0,
                    "报警阈值": 50.0,
                    "负责人": "王值班",
                    "通知方式": "短信+工单",
                    "threshold_updated_at": None,
                },
                {
                    "id": 2,
                    "点位编号": "GAS-0002",
                    "监测气体": "硫化氢",
                    "预警阈值": 8.0,
                    "报警阈值": 15.0,
                    "负责人": "李巡检",
                    "通知方式": "工单提醒",
                    "threshold_updated_at": None,
                },
            ])
        # 点位示例数据是占位文字，这里替换成可参与阈值判定的演示点位
        points = store.rows(POINT_MODULE)
        demo = {
            "GAS-0001": ("甲烷", "滨河路1号管沟", 12.0, 50.0, "2026-08-10", 20.0),
            "GAS-0002": ("硫化氢", "滨河路2号管沟", 5.0, 15.0, "2026-08-12", 6.0),
            "GAS-0003": ("一氧化碳", "建设大道3号管沟", 8.0, 30.0, "2026-09-01", 9.0),
        }
        if points and any(str(p.get("点位编号", "")).startswith("GAS_-") for p in points):
            points.clear()
            for index, (code, (gas, trench, concentration, threshold, calibrated, _)) in enumerate(demo.items(), start=1):
                points.append({
                    "id": index,
                    "status": "正常",
                    "pending": False,
                    "abnormal": False,
                    "点位编号": code,
                    "监测气体": gas,
                    "所在管沟": trench,
                    "当前浓度": concentration,
                    "报警阈值": threshold,
                    "上次标定日": calibrated,
                    "监测时间": _fmt(_now()),
                    "点位状态": "正常",
                })

    # ---------------------------------------------------------------- 工具
    @staticmethod
    def _next_id(rows: list[dict[str, Any]]) -> int:
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    def _point(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(POINT_MODULE):
            if str(row.get("点位编号", "")) == code:
                return row
        return None

    def _rule(self, code: str, gas: str) -> dict[str, Any] | None:
        for rule in store.rows(RULE_MODULE):
            if str(rule.get("点位编号", "")) == code and str(rule.get("监测气体", "")) == gas:
                return rule
        return None

    def _open_event(self, code: str, gas: str) -> dict[str, Any] | None:
        for event in store.rows(EVENT_MODULE):
            if (
                str(event.get("点位编号", "")) == code
                and str(event.get("监测气体", "")) == gas
                and event.get("事件状态") == EVENT_OPEN
            ):
                return event
        return None

    def _add_record(
        self,
        event_id: int | None,
        code: str,
        gas: str,
        kind: str,
        *,
        level: str | None = None,
        owner: str | None = None,
        detail: str = "",
        operator: str | None = None,
        suppressed: bool = False,
    ) -> dict[str, Any]:
        record = {
            "id": self._next_id(store.rows(RECORD_MODULE)),
            "事件id": event_id,
            "点位编号": code,
            "监测气体": gas,
            "记录类型": kind,
            "等级": level or "",
            "负责人": owner or "",
            "恢复状态": "",
            "处置说明": detail,
            "操作人": operator or owner or "",
            "是否抑制": suppressed,
            "记录时间": _fmt(_now()),
        }
        store.rows(RECORD_MODULE).append(record)
        return record

    @staticmethod
    def _level_of(concentration: float, rule: dict[str, Any] | None, point: dict[str, Any] | None = None) -> str:
        warn = _parse(rule.get("预警阈值")) if rule else None
        alarm = _parse(rule.get("报警阈值")) if rule else None
        # 未挂处置编排时，回退用点位档案上的报警阈值；只能识别报警，给不出预警分级
        if alarm is None and point is not None:
            alarm = _parse(point.get("报警阈值"))
        if alarm is not None and concentration >= alarm:
            return "报警"
        if warn is not None and concentration >= warn:
            return "预警"
        return "正常"

    # ---------------------------------------------------------------- 处置编排
    def list_rules(self, *, keyword: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(RULE_MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("点位编号", ""))]
        return [self._rule_view(row) for row in rows]

    def _rule_view(self, rule: dict[str, Any]) -> dict[str, Any]:
        point = self._point(str(rule.get("点位编号", "")))
        view = dict(rule)
        view["所在管沟"] = str(point.get("所在管沟", "")) if point else ""
        return view

    def save_rule(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        code = str(values.get("点位编号") or "").strip()
        gas = str(values.get("监测气体") or "").strip()
        warn = _parse(values.get("预警阈值"))
        alarm = _parse(values.get("报警阈值"))
        owner = str(values.get("负责人") or "").strip() or DEFAULT_OWNER
        notify = str(values.get("通知方式") or "").strip() or DEFAULT_NOTIFY
        if not code or not gas:
            return None, "处置编排需同时指定监测点位与监测气体"
        if warn is None or alarm is None:
            return None, "预警阈值与报警阈值必须是数值"
        if warn >= alarm:
            return None, "预警阈值应小于报警阈值，否则编排无法按级判定"
        now = _now()
        existing = self._rule(code, gas)
        if existing is None:
            if self._point(code) is None:
                return None, f"监测点位 {code} 不存在，无法挂处置编排"
            rule = {
                "id": self._next_id(store.rows(RULE_MODULE)),
                "点位编号": code,
                "监测气体": gas,
                "预警阈值": warn,
                "报警阈值": alarm,
                "负责人": owner,
                "通知方式": notify,
                "threshold_updated_at": None,
            }
            store.rows(RULE_MODULE).append(rule)
            self._add_record(
                self._open_event(code, gas).get("id") if self._open_event(code, gas) else None,
                code, gas, RECORD_REPORT, owner=owner,
                detail=f"已建立处置编排：预警 {warn}、报警 {alarm}",
            )
            return self._rule_view(rule), "处置编排已建立"
        # 阈值调整：记录调整时间，供事件引擎在窗口期内抑制为同一事件
        threshold_changed = warn != _parse(existing.get("预警阈值")) or alarm != _parse(existing.get("报警阈值"))
        existing["预警阈值"] = warn
        existing["报警阈值"] = alarm
        existing["负责人"] = owner
        existing["通知方式"] = notify
        if threshold_changed:
            existing["threshold_updated_at"] = now
            event = self._open_event(code, gas)
            self._add_record(
                event.get("id") if event else None,
                code, gas, RECORD_THRESHOLD, owner=owner,
                detail=f"阈值调整为预警 {warn}、报警 {alarm}",
                operator=owner,
            )
            if event is not None:
                self._sync_point(event)
        return self._rule_view(existing), "处置编排已更新"

    # ---------------------------------------------------------------- 读数上报 / 事件引擎
    def ingest_reading(
        self,
        code: str,
        concentration: float,
        *,
        operator: str | None = None,
        read_time: datetime | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        point = self._point(code)
        if point is None:
            return None, f"监测点位 {code} 不存在或已归档"
        gas = str(point.get("监测气体", ""))
        rule = self._rule(code, gas)
        now = read_time or _now()

        point["当前浓度"] = concentration
        point["监测时间"] = _fmt(now)

        level = self._level_of(concentration, rule, point)
        owner = str(rule.get("负责人", DEFAULT_OWNER)) if rule else DEFAULT_OWNER
        open_event = self._open_event(code, gas)

        # 1) 未越限：有活动事件则在恢复窗口内自动恢复，否则只是一条正常读数
        if level == "正常":
            if open_event is None:
                point["status"] = point["点位状态"] = "正常"
                point["pending"] = False
                point["abnormal"] = False
                self._add_record(None, code, gas, RECORD_REPORT, level="正常", owner=owner,
                                 detail=f"读数 {concentration}，低于预警阈值", operator=operator)
                return point, f"{code} 读数正常（{concentration}）"
            open_event["恢复时间"] = _fmt(now)
            open_event["事件状态"] = EVENT_RECOVERED
            open_event["抑制说明"] = open_event.get("抑制说明") or ""
            open_event["处置说明"] = f"读数回落至 {concentration}，{RECOVER_WINDOW.seconds // 60} 分钟内未再越限，事件自动恢复"
            self._add_record(open_event["id"], code, gas, RECORD_RECOVER,
                             level=open_event["当前等级"], owner=open_event["负责人"],
                             detail=open_event["处置说明"], operator=operator)
            self._sync_point(open_event)
            return self._event_view(open_event), f"事件 {open_event['事件编号']} 已恢复"

        # 2) 已越限且存在活动事件：先识别「同一事件」（交接/调阈/抖动），再看等级是否升级
        if open_event is not None:
            open_event["最近读数"] = concentration
            open_event["最近上报时间"] = _fmt(now)
            kind, reason = self._classify(open_event, rule, level, owner, operator, now)
            if kind == "handover":
                self._add_record(open_event["id"], code, gas, RECORD_HANDOVER, level=level,
                                 owner=open_event["负责人"], detail=reason, operator=operator)
                open_event["抑制说明"] = reason
            elif kind == "threshold":
                open_event["上报次数"] = int(open_event.get("上报次数", 1)) + 1
                open_event["抑制说明"] = reason
                self._add_record(open_event["id"], code, gas, RECORD_SUPPRESS, level=level,
                                 owner=open_event["负责人"], detail=reason,
                                 operator=operator, suppressed=True)
            elif (
                level != open_event["当前等级"]
                and LEVEL_ORDER.index(level) > LEVEL_ORDER.index(str(open_event["当前等级"]))
            ):
                # 等级实质升级：更新事件等级，不作为重复告警抑制
                old = open_event["当前等级"]
                open_event["当前等级"] = level
                detail = f"浓度 {concentration} 达{level}阈值，等级由{old}升级为{level}"
                self._add_record(open_event["id"], code, gas, RECORD_ESCALATE, level=level,
                                 owner=open_event["负责人"], detail=detail, operator=operator)
                open_event["处置说明"] = detail
                open_event["抑制说明"] = ""
                self._sync_point(open_event)
                return self._event_view(open_event), f"事件 {open_event['事件编号']} 已由{old}升级为{level}"
            else:
                # 同等级重复越限读数：连续抖动，并入同一事件
                open_event["上报次数"] = int(open_event.get("上报次数", 1)) + 1
                reason = (
                    f"点位 {code} 在事件 {open_event['事件编号']} 处置期间连续抖动"
                    f"（本次读数 {concentration}，{level}），判定为同一事件，抑制重复告警"
                )
                open_event["抑制说明"] = reason
                self._add_record(open_event["id"], code, gas, RECORD_SUPPRESS, level=level,
                                 owner=open_event["负责人"], detail=reason,
                                 operator=operator, suppressed=True)
            self._sync_point(open_event)
            return self._event_view(open_event), reason

        # 3) 越限且没有活动事件：开出新事件并套用处置编排
        event = {
            "id": self._next_id(store.rows(EVENT_MODULE)),
            "事件编号": f"GE-{now:%Y%m%d}-{self._next_id(store.rows(EVENT_MODULE)):03d}",
            "点位编号": code,
            "监测气体": gas,
            "所在管沟": str(point.get("所在管沟", "")),
            "当前等级": level,
            "等级": level,
            "负责人": owner,
            "通知方式": str(rule.get("通知方式", DEFAULT_NOTIFY)) if rule else DEFAULT_NOTIFY,
            "事件状态": EVENT_OPEN,
            "恢复状态": "未恢复",
            "首次读数": concentration,
            "最近读数": concentration,
            "上报次数": 1,
            "抑制说明": "",
            "处置说明": f"读数 {concentration} 触发{level}，按处置编排通知{owner}（{rule.get('通知方式', DEFAULT_NOTIFY) if rule else DEFAULT_NOTIFY}）",
            "首次上报时间": _fmt(now),
            "最近上报时间": _fmt(now),
            "恢复时间": None,
        }
        store.rows(EVENT_MODULE).append(event)
        self._add_record(event["id"], code, gas, RECORD_REPORT, level=level, owner=owner,
                         detail=event["处置说明"], operator=operator)
        self._sync_point(event)
        return self._event_view(event), f"已开出告警事件 {event['事件编号']}（{level}）"

    def _classify(
        self,
        event: dict[str, Any],
        rule: dict[str, Any] | None,
        level: str,
        owner: str,
        operator: str | None,
        now: datetime,
    ) -> tuple[str, str]:
        """识别一次越限读数与已有活动事件的关系。

        返回 (类别, 说明)，类别取 handover（处置人交接）、threshold（阈值刚调整）、
        chatter（连续抖动）之一；三类都并入同一事件、不重复开单。
        """
        code = str(event["点位编号"])
        gas = str(event["监测气体"])
        # 处置人交接：上报人或编排负责人与事件负责人不一致
        if operator and operator != event.get("负责人"):
            reason = f"处置人由{event['负责人']}交接给{operator}，事件 {event['事件编号']} 保持同一单，负责人同步更新"
            event["负责人"] = operator
            return "handover", reason
        if operator is None and owner != event.get("负责人"):
            event["负责人"] = owner
        # 阈值刚被调整：调整动作发生在抑制窗口内
        updated = rule.get("threshold_updated_at") if rule else None
        if isinstance(updated, datetime) and now - updated <= THRESHOLD_WINDOW:
            reason = (
                f"{code} 的{gas}阈值刚于 {_fmt(updated)} 调整（预警 {rule.get('预警阈值')}、"
                f"报警 {rule.get('报警阈值')}），{THRESHOLD_WINDOW.seconds // 60} 分钟内再次越限，"
                f"并入事件 {event['事件编号']}，不开新单"
            )
            return "threshold", reason
        # 连续抖动：处置期间同等级读数反复触发
        reason = (
            f"点位 {code} 在事件 {event['事件编号']} 处置期间连续抖动（{level}读数反复越限），"
            "判定为同一事件，抑制重复告警"
        )
        return "chatter", reason

    # ---------------------------------------------------------------- 现场处置 / 交接
    def handle_event(
        self,
        event_id: int,
        action: str,
        *,
        operator: str | None = None,
        note: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        event = store.find(EVENT_MODULE, event_id)
        if event is None:
            return None, f"告警事件 {event_id} 不存在或已归档"
        if event.get("事件状态") != EVENT_OPEN:
            return None, f"事件 {event['事件编号']} 已恢复，不能继续处置"
        if action == "恢复":
            now = _now()
            event["事件状态"] = EVENT_RECOVERED
            event["恢复状态"] = "已恢复"
            event["恢复时间"] = _fmt(now)
            event["抑制说明"] = event.get("抑制说明") or ""
            tail = f"；{note}" if note else ""
            event["处置说明"] = f"处置人 {operator or event['负责人']} 现场确认恢复{tail}"
            self._add_record(event["id"], event["点位编号"], event["监测气体"], RECORD_ACTION,
                             level=event["当前等级"], owner=event["负责人"],
                             detail=event["处置说明"], operator=operator)
            self._sync_point(event)
            return self._event_view(event), f"事件 {event['事件编号']} 已现场确认恢复"
        if action != "处置":
            return None, f"动作「{action}」不属于告警联动可执行范围"
        detail = f"处置人 {operator or event['负责人']} 执行现场处置"
        if note:
            detail += f"：{note}"
        self._add_record(event["id"], event["点位编号"], event["监测气体"], RECORD_ACTION,
                         level=event["当前等级"], owner=event["负责人"], detail=detail,
                         operator=operator)
        event["处置说明"] = detail
        return self._event_view(event), f"事件 {event['事件编号']} 已记录现场处置"

    def handover_event(
        self,
        event_id: int,
        new_owner: str,
        *,
        operator: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        event = store.find(EVENT_MODULE, event_id)
        if event is None:
            return None, f"告警事件 {event_id} 不存在或已归档"
        new_owner = new_owner.strip()
        if not new_owner:
            return None, "交接需要指定新的负责人"
        if new_owner == event.get("负责人"):
            return None, f"事件 {event['事件编号']} 本就由 {new_owner} 负责，无需交接"
        detail = f"负责人由 {event['负责人']} 交接给 {new_owner}，沿用同一事件 {event['事件编号']}，不重复开单"
        event["负责人"] = new_owner
        event["抑制说明"] = detail
        self._add_record(event["id"], event["点位编号"], event["监测气体"], RECORD_HANDOVER,
                         level=event["当前等级"], owner=new_owner, detail=detail,
                         operator=operator or new_owner)
        self._sync_point(event)
        return self._event_view(event), detail

    # ---------------------------------------------------------------- 同步
    def _sync_point(self, event: dict[str, Any]) -> None:
        """把事件的等级、负责人、恢复状态回写到监测点位，三处看到同一份数据。"""
        point = self._point(str(event["点位编号"]))
        if point is None:
            return
        recovered = event.get("事件状态") == EVENT_RECOVERED
        point["告警事件id"] = event["id"]
        point["告警等级"] = "" if recovered else event["当前等级"]
        point["告警负责人"] = event["负责人"]
        point["恢复状态"] = "已恢复" if recovered else "未恢复"
        point["抑制说明"] = "" if recovered else event.get("抑制说明", "")
        point["点位状态"] = "正常" if recovered else str(event["当前等级"]) + "值"
        point["status"] = point["点位状态"]
        point["pending"] = not recovered
        point["abnormal"] = not recovered

    def _event_view(self, event: dict[str, Any]) -> dict[str, Any]:
        view = dict(event)
        view["恢复状态"] = "已恢复" if event.get("事件状态") == EVENT_RECOVERED else "未恢复"
        view["等级"] = event.get("当前等级")
        return view

    # ---------------------------------------------------------------- 查询
    def list_events(
        self,
        *,
        status: str | None = None,
        level: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(EVENT_MODULE)
        if status in ("未恢复", EVENT_OPEN):
            rows = [row for row in rows if row.get("事件状态") == EVENT_OPEN]
        elif status == EVENT_RECOVERED:
            rows = [row for row in rows if row.get("事件状态") == EVENT_RECOVERED]
        if level:
            rows = [row for row in rows if row.get("当前等级") == level]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("点位编号", "")) or keyword in str(row.get("事件编号", ""))]
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._event_view(row) for row in rows[start:start + size]], total

    def list_records(
        self,
        *,
        event_id: int | None = None,
        code: str | None = None,
        suppressed: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(RECORD_MODULE)
        if event_id is not None:
            rows = [row for row in rows if row.get("事件id") == event_id]
        if code:
            rows = [row for row in rows if str(row.get("点位编号", "")) == code]
        if suppressed is not None:
            rows = [row for row in rows if bool(row.get("是否抑制")) == suppressed]
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = []
        for row in rows[start:start + size]:
            view = dict(row)
            event = store.find(EVENT_MODULE, int(row.get("事件id") or 0)) if row.get("事件id") else None
            if event is not None:
                view["等级"] = event.get("当前等级")
                view["负责人"] = event.get("负责人")
                view["恢复状态"] = "已恢复" if event.get("事件状态") == EVENT_RECOVERED else "未恢复"
                view["事件编号"] = event.get("事件编号")
            else:
                view["事件编号"] = ""
            page_rows.append(view)
        return page_rows, total

    def point_detail(self, code: str) -> dict[str, Any] | None:
        """点位详情：点位字段 + 处置编排 + 当前活动事件，三处口径一致。"""
        point = self._point(code)
        if point is None:
            return None
        gas = str(point.get("监测气体", ""))
        rule = self._rule(code, gas)
        event = self._open_event(code, gas)
        recent, _ = self.list_records(code=code, page=1, size=10)
        return {
            "点位": dict(point),
            "处置编排": self._rule_view(rule) if rule else None,
            "活动事件": self._event_view(event) if event else None,
            "最近记录": recent,
        }

    def summary(self) -> dict[str, Any]:
        events = store.rows(EVENT_MODULE)
        open_events = [row for row in events if row.get("事件状态") == EVENT_OPEN]
        return {
            "活动事件": len(open_events),
            "报警中": sum(1 for row in open_events if row.get("当前等级") == "报警"),
            "预警中": sum(1 for row in open_events if row.get("当前等级") == "预警"),
            "已恢复": sum(1 for row in events if row.get("事件状态") == EVENT_RECOVERED),
            "抑制读数": sum(1 for row in store.rows(RECORD_MODULE) if row.get("是否抑制")),
            "编排规则": len(store.rows(RULE_MODULE)),
        }


gas_alarm_service = GasAlarmService()
