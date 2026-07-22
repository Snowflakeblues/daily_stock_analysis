# -*- coding: utf-8 -*-
"""AlphaSift stock screening API routes."""

from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.deps import get_config_dep
from api.v1.errors import api_error
from src.config import Config
from src.services.alphasift_service import AlphaSiftService
from src.services.task_queue import TaskStatus as QueueTaskStatus
from src.services.task_queue import get_task_queue

router = APIRouter()

ALPHASIFT_HOTSPOT_REFRESH_REPORT_TYPE = "alphasift_hotspot_refresh"
ALPHASIFT_HOTSPOT_REFRESH_STOCK_CODE = "alphasift_hotspots"
_hotspot_refresh_submit_lock = threading.Lock()
_hotspot_refresh_task_params: Dict[str, Tuple[str, int]] = {}


class AlphaSiftScreenRequest(BaseModel):
    market: str = Field("cn", min_length=1, max_length=16)
    strategy: str = Field("dual_low", min_length=1, max_length=64)
    max_results: int = Field(20, ge=1, le=100)


class AlphaSiftStrategyResponse(BaseModel):
    id: str
    name: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    tag: str = ""
    tags: List[str] = Field(default_factory=list)
    market_scope: List[str] = Field(default_factory=list)
    market: str = ""


class AlphaSiftScreenAccepted(BaseModel):
    task_id: str
    trace_id: str
    status: str = "pending"
    message: str
    strategy: str
    market: str
    max_results: int


class AlphaSiftScreenTaskStatus(BaseModel):
    task_id: str
    trace_id: Optional[str] = None
    status: str
    progress: int = 0
    message: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class AlphaSiftHotspotRefreshRequest(BaseModel):
    provider: str = Field("akshare", max_length=32)
    top: int = Field(12, ge=1, le=50)


class AlphaSiftHotspotRefreshAccepted(BaseModel):
    task_id: str
    trace_id: str
    status: str = "pending"
    message: str
    reused: bool = False
    provider: str
    top: int


class AlphaSiftHotspotRefreshTaskStatus(BaseModel):
    task_id: str
    trace_id: Optional[str] = None
    status: str
    progress: int = 0
    message: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


def _service(config: Config) -> AlphaSiftService:
    return AlphaSiftService(config=config)


def _screening_task_not_found(task_id: str) -> HTTPException:
    return api_error(
        404,
        "alphasift_screen_task_not_found",
        f"选股任务 {task_id} 不存在或已过期",
    )


def _hotspot_refresh_task_not_found(task_id: str) -> HTTPException:
    return api_error(
        404,
        "alphasift_hotspot_refresh_task_not_found",
        f"热点题材刷新任务 {task_id} 不存在或已过期",
    )


def _task_status_value(task: Any) -> str:
    return task.status.value if isinstance(task.status, QueueTaskStatus) else str(task.status)


def _find_active_hotspot_refresh_task(task_queue: Any) -> Optional[Any]:
    for task in task_queue.list_pending_tasks():
        if task.report_type == ALPHASIFT_HOTSPOT_REFRESH_REPORT_TYPE:
            return task
    return None


@router.get("/status")
def alphasift_status(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    return _service(config).status()


@router.get("/strategies")
def alphasift_strategies(
    request: Request,
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    return _service(config).strategies()


@router.get("/hotspots")
def alphasift_hotspots(
    provider: str = Query("", max_length=32),
    top: int = Query(12, ge=1, le=50),
    refresh: bool = Query(False),
    include_details: bool = Query(False),
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    refresh_value = refresh if isinstance(refresh, bool) else bool(getattr(refresh, "default", False))
    include_details_value = (
        include_details
        if isinstance(include_details, bool)
        else bool(getattr(include_details, "default", False))
    )
    return _service(config).hotspots(
        provider=provider,
        top=top,
        refresh=refresh_value,
        include_details=include_details_value,
    )


@router.post(
    "/hotspots/refresh/tasks",
    status_code=202,
    response_model=AlphaSiftHotspotRefreshAccepted,
)
def alphasift_start_hotspot_refresh_task(
    request: AlphaSiftHotspotRefreshRequest,
    config: Config = Depends(get_config_dep),
) -> AlphaSiftHotspotRefreshAccepted:
    provider = request.provider.strip() or "akshare"
    task_queue = get_task_queue()

    with _hotspot_refresh_submit_lock:
        active_task = _find_active_hotspot_refresh_task(task_queue)
        if active_task is not None:
            active_provider, active_top = _hotspot_refresh_task_params.get(
                active_task.task_id,
                (provider, request.top),
            )
            return AlphaSiftHotspotRefreshAccepted(
                task_id=active_task.task_id,
                trace_id=active_task.trace_id or active_task.task_id,
                status=_task_status_value(active_task),
                message=active_task.message or "热点题材后台刷新任务正在运行",
                reused=True,
                provider=active_provider,
                top=active_top,
            )

        _hotspot_refresh_task_params.clear()
        task_id = uuid.uuid4().hex
        _hotspot_refresh_task_params[task_id] = (provider, request.top)

        def run_hotspot_refresh() -> Dict[str, Any]:
            task_queue.update_task_progress(
                task_id,
                10,
                "正在后台刷新热点题材，当前页面继续使用最近一次有效缓存",
            )
            service = _service(config)
            live_result = service.hotspots(
                provider=provider,
                top=request.top,
                refresh=True,
                include_details=False,
            )
            if not isinstance(live_result, dict) or live_result.get("enabled") is False:
                message = live_result.get("message") if isinstance(live_result, dict) else None
                raise RuntimeError(message or "AlphaSift 热点题材刷新未返回有效结果")

            task_queue.update_task_progress(
                task_id,
                90,
                "热点题材已刷新，正在确认最新缓存",
            )
            cached_result = service.hotspots(
                provider=provider,
                top=request.top,
                refresh=False,
                include_details=False,
            )
            source_errors = live_result.get("source_errors")
            return {
                "provider": cached_result.get("provider_used") or live_result.get("provider_used") or provider,
                "top": request.top,
                "hotspot_count": cached_result.get("hotspot_count", live_result.get("hotspot_count", 0)),
                "cached_at": cached_result.get("cached_at") or live_result.get("cached_at"),
                "fallback_used": bool(live_result.get("fallback_used")),
                "source_errors": source_errors if isinstance(source_errors, list) else [],
            }

        try:
            task = task_queue.submit_background_task(
                run_hotspot_refresh,
                stock_code=ALPHASIFT_HOTSPOT_REFRESH_STOCK_CODE,
                stock_name="AlphaSift 热点题材",
                report_type=ALPHASIFT_HOTSPOT_REFRESH_REPORT_TYPE,
                message="热点题材后台刷新任务已提交",
                task_id=task_id,
                trace_id=task_id,
            )
        except Exception:
            _hotspot_refresh_task_params.pop(task_id, None)
            raise

    return AlphaSiftHotspotRefreshAccepted(
        task_id=task.task_id,
        trace_id=task.trace_id or task.task_id,
        status=_task_status_value(task),
        message=task.message or "热点题材后台刷新任务已提交",
        reused=False,
        provider=provider,
        top=request.top,
    )


@router.get(
    "/hotspots/refresh/tasks/{task_id}",
    response_model=AlphaSiftHotspotRefreshTaskStatus,
)
def alphasift_hotspot_refresh_task_status(task_id: str) -> AlphaSiftHotspotRefreshTaskStatus:
    task = get_task_queue().get_task(task_id)
    if task is None or task.report_type != ALPHASIFT_HOTSPOT_REFRESH_REPORT_TYPE:
        raise _hotspot_refresh_task_not_found(task_id)

    result = task.result if task.status == QueueTaskStatus.COMPLETED and isinstance(task.result, dict) else None
    task_status = _task_status_value(task)
    if task_status not in {QueueTaskStatus.PENDING.value, QueueTaskStatus.PROCESSING.value}:
        with _hotspot_refresh_submit_lock:
            _hotspot_refresh_task_params.pop(task.task_id, None)

    return AlphaSiftHotspotRefreshTaskStatus(
        task_id=task.task_id,
        trace_id=task.trace_id or task.task_id,
        status=task_status,
        progress=task.progress,
        message=task.message,
        error=task.error,
        result=result,
    )


@router.get("/hotspots/{topic:path}")
def alphasift_hotspot_detail(
    topic: str,
    provider: str = Query("", max_length=32),
    refresh: bool = Query(False),
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    refresh_value = refresh if isinstance(refresh, bool) else bool(getattr(refresh, "default", False))
    return _service(config).hotspot_detail(topic=topic, provider=provider, refresh=refresh_value)


@router.post("/install")
def alphasift_install(
    request: Request,
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    return _service(config).install(request=request)


@router.post("/screen/tasks", status_code=202, response_model=AlphaSiftScreenAccepted)
def alphasift_start_screen_task(
    request: AlphaSiftScreenRequest,
    http_request: Request,
    config: Config = Depends(get_config_dep),
) -> AlphaSiftScreenAccepted:
    task_id = uuid.uuid4().hex
    task_queue = get_task_queue()

    def run_screen() -> Dict[str, Any]:
        task_queue.update_task_progress(
            task_id,
            20,
            "正在执行 AlphaSift 选股，外部数据源较慢时会持续后台运行",
        )
        result = _service(config).screen(
            strategy=request.strategy,
            market=request.market,
            max_results=request.max_results,
        )
        task_queue.update_task_progress(
            task_id,
            90,
            f"选股已完成，正在整理 {result.get('candidate_count', 0)} 条候选",
        )
        return result

    task = task_queue.submit_background_task(
        run_screen,
        stock_code="alphasift_screen",
        stock_name=f"{request.strategy} / {request.market}",
        report_type="alphasift_screen",
        message="AlphaSift 选股任务已提交",
        task_id=task_id,
        trace_id=task_id,
    )
    return AlphaSiftScreenAccepted(
        task_id=task.task_id,
        trace_id=task.trace_id or task.task_id,
        status=task.status.value if isinstance(task.status, QueueTaskStatus) else str(task.status),
        message=task.message or "AlphaSift 选股任务已提交",
        strategy=request.strategy,
        market=request.market,
        max_results=request.max_results,
    )


@router.get("/screen/tasks/{task_id}", response_model=AlphaSiftScreenTaskStatus)
def alphasift_screen_task_status(task_id: str) -> AlphaSiftScreenTaskStatus:
    task = get_task_queue().get_task(task_id)
    if task is None or task.report_type != "alphasift_screen":
        raise _screening_task_not_found(task_id)

    result = task.result if task.status == QueueTaskStatus.COMPLETED and isinstance(task.result, dict) else None
    return AlphaSiftScreenTaskStatus(
        task_id=task.task_id,
        trace_id=task.trace_id or task.task_id,
        status=task.status.value if isinstance(task.status, QueueTaskStatus) else str(task.status),
        progress=task.progress,
        message=task.message,
        error=task.error,
        result=result,
    )


@router.post("/screen")
def alphasift_screen(
    request: AlphaSiftScreenRequest,
    http_request: Request,
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    return _service(config).screen(
        strategy=request.strategy,
        market=request.market,
        max_results=request.max_results,
    )
