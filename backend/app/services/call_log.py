"""调用日志领域服务：管理API调用记录，与 retry_queue、api_monitor、rate_limit、govern_report 联动。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 失败口径：这三类状态的调用记录视为未拿到数据的失败请求
FAILURE_STATUSES = ("超时", "限流拒绝", "鉴权失败")
SUCCESS_STATUS = "成功"


class CallLogService(BaseModuleService):
    MODULE = "call_log"
    ENTITY = "调用记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["记录编号", "请求编号", "接口端点", "请求参数", "响应状态", "响应耗时", "返回行数", "错误信息", "调用时间"]
    REQUIRED_FIELDS = ["记录编号", "接口端点", "请求参数"]
    STATUS_ORDER = ["成功", "超时", "限流拒绝", "鉴权失败"]
    ACTION_RULES = {"标记审计": "超时", "标记重试": "限流拒绝"}
    NEGATIVE_ACTIONS = []

    def create_entry(self, values: dict[str, Any]):
        """登记调用记录时按响应状态推导成功/失败状态，保证缺采匹配口径一致。"""
        entry, missing = super().create_entry(values)
        if entry is not None:
            self._sync_status_with_response(entry)
        return entry, missing

    @staticmethod
    def _sync_status_with_response(entry: dict):
        """按响应状态码推导记录状态：2xx 为成功回执，其余落入对应失败状态。"""
        code = str(entry.get("响应状态", "")).strip().lower()
        if code.startswith("2") or code in {"success", "ok", "成功"}:
            status = "成功"
        elif code.startswith(("401", "403")) or "鉴权" in code:
            status = "鉴权失败"
        elif code.startswith("429") or "限流" in code:
            status = "限流拒绝"
        else:
            status = "超时"
        entry["status"] = status
        entry["pending"] = status != "成功"
        entry["abnormal"] = status != "成功"

    def run_action(self, entry_id: int, action: str):
        """标记审计时联动流水审计；标记重试时创建重放任务并检索引用追踪状态。"""
        entry, message = super().run_action(entry_id, action)
        if entry is None:
            return entry, message
        if action == "标记审计":
            self._audit_call(entry)
            message += "，已记录管道审计"
        elif action == "标记重试":
            self._enqueue_from_log(entry)
            self._check_incr_tracker(entry)
            message += "，已创建重放任务并检查增量追踪状态"
        return entry, message

    def _audit_call(self, log: dict):
        """调用异常时创建管道审计记录。"""
        audit_rows = store.rows("pipeline_audit")
        lid = str(log["id"]).zfill(4)
        audit_rows.append({
            "id": max((int(r.get("id", 0)) for r in audit_rows), default=0) + 1,
            "记录编号": f"PIPE-CALL-{lid}",
            "管道名称": f"call_log_audit:{lid}",
            "操作人": "system",
            "操作类型": "审计",
            "变更摘要": f"调用记录{lid}标记审计:超时",
            "操作时间": "2026-11-17",
            "来源节点": "call_log",
            "审计结论": "待复核",
            "status": "待复核", "pending": True, "abnormal": True,
        })

    def _enqueue_from_log(self, log: dict):
        """从调用日志创建重放任务。"""
        retry_rows = store.rows("retry_queue")
        lid = str(log["id"]).zfill(4)
        retry_rows.append({
            "id": max((int(r.get("id", 0)) for r in retry_rows), default=0) + 1,
            "任务编号": f"RETR-CALL-{lid}",
            "失败端点": log.get("接口端点", ""),
            "失败原因": f"调用日志{lid}限流拒绝或超时",
            "重试次数": 0,
            "最大重试": 3,
            "退避策略": "linear:3s",
            "最后重试": "",
            "队列状态": "from_call_log",
            "关联请求编号": str(log.get("请求编号", "")),
            "status": "待重试", "pending": True, "abnormal": True,
        })

    def _check_incr_tracker(self, log: dict):
        """重试时检查增量追踪状态，同步游标。"""
        endpoint = log.get("接口端点", "")
        for tracker in store.rows("incr_tracker"):
            if tracker.get("目标端点") == endpoint:
                tracker["当前游标"] = f"call_{log['id']}"
                tracker["最后同步"] = "2026-11-17"

    # ---------- 缺采匹配：失败请求 × 后续回执 ----------

    @staticmethod
    def _is_failure(row: dict) -> bool:
        return row.get("status") in FAILURE_STATUSES

    @staticmethod
    def _is_receipt(row: dict) -> bool:
        return row.get("status") == SUCCESS_STATUS

    def _request_groups(self) -> dict[str, list[dict]]:
        """按请求编号聚合调用记录：一次逻辑采集与多次尝试共用同一编号，无编号记录不参与对照。"""
        groups: dict[str, list[dict]] = {}
        for row in store.rows(self.MODULE):
            number = str(row.get("请求编号", "")).strip()
            if number:
                groups.setdefault(number, []).append(row)
        return groups

    @staticmethod
    def _retry_index() -> dict[str, dict]:
        """重放队列里按关联请求编号索引的补采任务（同一编号取最新一条）。"""
        index: dict[str, dict] = {}
        for task in store.rows("retry_queue"):
            number = str(task.get("关联请求编号", "")).strip()
            if number:
                index[number] = task
        return index

    @staticmethod
    def _match_receipt(rows: list[dict], first_fail: str) -> dict | None:
        """在共享同一请求编号的记录里找实际成功回执（时间不早于首次失败），作为响应依据。"""
        receipts = [
            row for row in rows
            if CallLogService._is_receipt(row) and str(row.get("调用时间", "")) >= first_fail
        ]
        if not receipts:
            return None
        return max(receipts, key=lambda r: str(r.get("调用时间", "")))

    def match_unrecovered(
        self,
        *,
        request_no: str = "",
        fail_date: str = "",
        endpoint: str = "",
        page: int = 1,
        size: int = 3,
    ) -> dict[str, Any]:
        """失败请求与后续成功回执对照，输出带稳定位置的缺采匹配清单。

        候选集合按（失败日期, 请求编号）稳定排序：迟到的 200 回执只把该笔标记为
        已恢复，不会把它从清单里移除，翻页或重新取数时原编号位置不漂移；
        检索范围（请求编号/失败日期/接口端点）变化时由调用方重新发起查询判定候选。
        """
        retry_index = self._retry_index()
        matched: list[dict[str, Any]] = []
        for number, rows in self._request_groups().items():
            failures = [row for row in rows if self._is_failure(row)]
            if not failures:
                continue
            first_fail = min(str(row.get("调用时间", "")) for row in failures)
            last_failure = max(failures, key=lambda r: str(r.get("调用时间", "")))
            receipt = self._match_receipt(rows, first_fail)
            task = retry_index.get(number)
            matched.append({
                "请求编号": number,
                "接口端点": str(last_failure.get("接口端点", "")),
                "失败日期": first_fail,
                "最近失败时间": str(last_failure.get("调用时间", "")),
                "尝试次数": len(rows),
                "失败次数": len(failures),
                "最近响应状态": str(last_failure.get("响应状态", "")),
                "最近错误信息": str(last_failure.get("错误信息", "")),
                "恢复状态": "已恢复" if receipt else "未恢复",
                "回执记录编号": str(receipt.get("记录编号", "")) if receipt else "",
                "回执响应状态": str(receipt.get("响应状态", "")) if receipt else "",
                "回执时间": str(receipt.get("调用时间", "")) if receipt else "",
                "回执返回行数": str(receipt.get("返回行数", "")) if receipt else "",
                "派发状态": "已派发" if task else "未派发",
                "重放任务编号": str(task.get("任务编号", "")) if task else "",
                "重放任务状态": str(task.get("status", "")) if task else "",
            })
        if request_no:
            matched = [m for m in matched if request_no.casefold() in m["请求编号"].casefold()]
        if fail_date:
            matched = [m for m in matched if fail_date in m["失败日期"]]
        if endpoint:
            matched = [m for m in matched if endpoint.casefold() in m["接口端点"].casefold()]
        matched.sort(key=lambda m: (m["失败日期"], m["请求编号"]))
        total = len(matched)
        start = (page - 1) * size
        items = []
        for offset, item in enumerate(matched[start:start + size]):
            item["位置"] = start + offset + 1
            items.append(item)
        return {"items": items, "total": total, "page": page, "size": size}

    # ---------- 派发重放：以选中请求建立待补采项 ----------

    OPEN_TASK_STATUSES = ("待重试", "重试中")

    def dispatch_unrecovered(self, request_numbers: list[str]) -> dict[str, Any]:
        """把选中的请求编号派发到重放队列建立待补采项，确认结果供检索清单回写。

        领取时凭实际成功回执剔除不再需要执行的请求；已派发的编号不重复建单，
        派发中断后重新提交可安全续做，并能识别哪些请求已经成功送达。
        """
        groups = self._request_groups()
        retry_index = self._retry_index()
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw in request_numbers:
            number = str(raw).strip()
            if not number or number in seen:
                continue
            seen.add(number)
            rows = groups.get(number, [])
            failures = [row for row in rows if self._is_failure(row)]
            if not failures:
                results.append({"请求编号": number, "结果": "未找到失败请求", "任务编号": ""})
                continue
            first_fail = min(str(row.get("调用时间", "")) for row in failures)
            if self._match_receipt(rows, first_fail) is not None:
                results.append({"请求编号": number, "结果": "已送达剔除", "任务编号": ""})
                continue
            existing = retry_index.get(number)
            if existing is not None and existing.get("status") in self.OPEN_TASK_STATUSES:
                results.append({"请求编号": number, "结果": "已在队列",
                                "任务编号": str(existing.get("任务编号", ""))})
                continue
            task = self._create_recollect_task(number, failures)
            self._log_recollect(task)
            retry_index[number] = task
            results.append({"请求编号": number, "结果": "已派发",
                            "任务编号": str(task.get("任务编号", ""))})
        dispatched = sum(1 for r in results if r["结果"] == "已派发")
        skipped = sum(1 for r in results if r["结果"] == "已送达剔除")
        queued = sum(1 for r in results if r["结果"] == "已在队列")
        missing = sum(1 for r in results if r["结果"] == "未找到失败请求")
        message = f"已派发{dispatched}笔，凭成功回执剔除{skipped}笔，已在队列{queued}笔，未找到{missing}笔"
        return {
            "ok": True,
            "message": message,
            "结果": results,
            "已派发": dispatched,
            "已剔除": skipped,
            "已在队列": queued,
            "未找到": missing,
        }

    def _create_recollect_task(self, number: str, failures: list[dict]) -> dict:
        """以选中的请求编号在重放队列建立待补采项。"""
        retry_rows = store.rows("retry_queue")
        last_failure = max(failures, key=lambda r: str(r.get("调用时间", "")))
        task = {
            "id": max((int(r.get("id", 0)) for r in retry_rows), default=0) + 1,
            "任务编号": "",
            "失败端点": str(last_failure.get("接口端点", "")),
            "失败原因": f"缺采补采：请求编号{number}未收到成功回执",
            "重试次数": 0,
            "最大重试": 3,
            "退避策略": "linear:3s",
            "最后重试": "",
            "队列状态": "待补采",
            "关联请求编号": number,
            "status": "待重试", "pending": True, "abnormal": True,
        }
        task["任务编号"] = f"RETR-RECO-{task['id']:04d}"
        retry_rows.append(task)
        return task

    def _log_recollect(self, task: dict):
        """派发后写实际重采日志：与原请求共用请求编号，成功回执到达前保持未恢复口径。"""
        log_rows = store.rows(self.MODULE)
        number = str(task.get("关联请求编号", ""))
        log_rows.append({
            "id": max((int(r.get("id", 0)) for r in log_rows), default=0) + 1,
            "记录编号": f"CALL-RECO-{task['id']:04d}",
            "请求编号": number,
            "接口端点": task.get("失败端点", ""),
            "请求参数": f"recollect:req={number}",
            "响应状态": "补采中",
            "响应耗时": "0",
            "返回行数": "0",
            "错误信息": task.get("失败原因", ""),
            "调用时间": date.today().isoformat(),
            "status": "超时", "pending": True, "abnormal": True,
        })

    def calc_call_metrics(self, endpoint: str) -> dict:
        """跨模块调用指标：汇总日志+重试+监控+限流+治理。"""
        logs = [l for l in store.rows("call_log") if l.get("接口端点") == endpoint]
        retries = [r for r in store.rows("retry_queue") if r.get("失败端点") == endpoint]
        monitors = [m for m in store.rows("api_monitor") if m.get("目标端点") == endpoint]
        rate_limits = [rl for rl in store.rows("rate_limit") if rl.get("目标端点") == endpoint]
        return {
            "endpoint": endpoint,
            "total_calls": len(logs),
            "success_rate": sum(1 for l in logs if l.get("status") == "成功") / len(logs) if logs else 1.0,
            "avg_latency_ms": sum(int(l.get("响应耗时(ms)", 0)) for l in logs) / len(logs) if logs else 0,
            "pending_retries": len(retries),
            "monitors_active": sum(1 for m in monitors if m.get("status") == "监控中"),
            "rate_limits_active": sum(1 for rl in rate_limits if rl.get("status") == "生效中"),
        }
