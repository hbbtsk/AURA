"""
AURA 维测系统 — Gradio 调试 UI

职责：
  - 实时观察：从 /debug/latest 拉取最新世界状态 + 角色状态
  - 历史回溯：从 /debug/snapshot/{event_id} 查询历史状态

启动方式：
    python debug_ui.py

依赖：
    pip install gradio requests
"""

import json

import gradio as gr
import requests

# ------------------------------------------------------------------
# 配置
# ------------------------------------------------------------------
BASE_URL = "http://127.0.0.1:8000/debug"
DEFAULT_REFRESH_INTERVAL = 2  # 自动刷新间隔（秒）


# ------------------------------------------------------------------
# API 调用封装（含错误处理）
# ------------------------------------------------------------------

def _fetch_latest() -> dict:
    """拉取最新快照，出错时返回含 error 字段的 dict。"""
    try:
        resp = requests.get(f"{BASE_URL}/latest", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"error": "无法连接到 AURA 后端（请确认服务已启动在 :8000）"}
    except requests.exceptions.Timeout:
        return {"error": "请求超时（后端响应慢）"}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP 错误: {e.response.status_code} - {e.response.text}"}
    except Exception as e:
        return {"error": f"未知错误: {str(e)}"}


def _fetch_snapshots(limit: int = 30) -> list:
    """拉取快照列表，出错时返回空列表。"""
    try:
        resp = requests.get(f"{BASE_URL}/snapshots", params={"limit": limit}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return data.get("snapshots", [])
    except Exception:
        return []


def _fetch_snapshot(event_id: str) -> dict:
    """按 event_id 拉取快照，出错时返回含 error 字段的 dict。"""
    try:
        resp = requests.get(f"{BASE_URL}/snapshot/{event_id}", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {"error": "无法连接到 AURA 后端"}
    except requests.exceptions.Timeout:
        return {"error": "请求超时"}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP 错误: {e.response.status_code} - {e.response.text}"}
    except Exception as e:
        return {"error": f"未知错误: {str(e)}"}


# ------------------------------------------------------------------
# UI 回调函数
# ------------------------------------------------------------------

def refresh_latest() -> tuple:
    """
    刷新最新状态。

    返回：
        (event_id_text, timestamp_text, world_state_json, role_states_json, status_text)
    """
    data = _fetch_latest()
    if "error" in data:
        return (
            "—",
            "—",
            data["error"],
            "",
            f"❌ {data['error']}",
        )

    event_id = data.get("event_id", "—")
    timestamp = data.get("timestamp", "—")
    world_state = data.get("world_state", {})
    role_states = data.get("role_states", {})

    world_json = json.dumps(world_state, ensure_ascii=False, indent=2) if world_state else "（空）"
    role_json = json.dumps(role_states, ensure_ascii=False, indent=2) if role_states else "（空）"

    return (
        event_id,
        str(timestamp),
        world_json,
        role_json,
        f"✅ 已刷新 | event_id: {event_id}",
    )


def load_history_dropdown() -> gr.update:
    """加载最近 30 条事件到下拉框。"""
    snapshots = _fetch_snapshots(limit=30)
    if not snapshots:
        return gr.update(choices=[], value=None)

    choices = []
    for s in snapshots:
        eid = s.get("event_id", "unknown")
        ts = s.get("timestamp", 0)
        label = f"{eid} @ {ts:.3f}"
        choices.append((label, eid))

    return gr.update(choices=choices, value=choices[0][1] if choices else None)


def load_history_snapshot(event_id: str) -> tuple:
    """
    加载指定事件的历史状态。

    返回：
        (world_state_json, role_states_json, status_text)
    """
    if not event_id:
        return (
            "请先选择事件",
            "",
            "❌ 未选择事件",
        )

    data = _fetch_snapshot(event_id)
    if "error" in data:
        return (
            data["error"],
            "",
            f"❌ {data['error']}",
        )

    world_state = data.get("world_state", {})
    role_states = data.get("role_states", {})

    world_json = json.dumps(world_state, ensure_ascii=False, indent=2) if world_state else "（空）"
    role_json = json.dumps(role_states, ensure_ascii=False, indent=2) if role_states else "（空）"

    return (
        world_json,
        role_json,
        f"✅ 已加载 | event_id: {event_id}",
    )


def auto_refresh_latest() -> tuple:
    """供 Gradio 定时器调用的自动刷新包装。"""
    return refresh_latest()


# ------------------------------------------------------------------
# Gradio 界面构建
# ------------------------------------------------------------------

with gr.Blocks(title="AURA 维测系统") as demo:
    gr.Markdown("# 🧠 AURA 维测系统")
    gr.Markdown("实时观察 + 历史回溯 | 数据来自 AURA 后端 `/debug/*` 端点")

    with gr.Tabs():
        # ======================== 实时观察 ========================
        with gr.TabItem("实时观察"):
            gr.Markdown("### 当前最新状态")

            with gr.Row():
                with gr.Column(scale=1):
                    event_id_text = gr.Textbox(
                        label="当前事件 ID",
                        value="—",
                        interactive=False,
                    )
                with gr.Column(scale=1):
                    timestamp_text = gr.Textbox(
                        label="时间戳",
                        value="—",
                        interactive=False,
                    )

            with gr.Row():
                with gr.Column(scale=1):
                    world_state_box = gr.Textbox(
                        label="世界状态 (world_state)",
                        value="点击刷新按钮加载...",
                        lines=20,
                        max_lines=30,
                        interactive=False,
                        autoscroll=False,
                    )
                with gr.Column(scale=1):
                    role_states_box = gr.Textbox(
                        label="角色 8 层模型 (role_states)",
                        value="",
                        lines=20,
                        max_lines=30,
                        interactive=False,
                        autoscroll=False,
                    )

            with gr.Row():
                refresh_btn = gr.Button("🔄 刷新", variant="primary")
                status_text = gr.Textbox(
                    label="状态",
                    value="等待刷新...",
                    interactive=False,
                )

            # 绑定刷新按钮
            refresh_btn.click(
                fn=refresh_latest,
                inputs=[],
                outputs=[
                    event_id_text,
                    timestamp_text,
                    world_state_box,
                    role_states_box,
                    status_text,
                ],
            )

            # 自动刷新（每 2 秒）—— 使用 gr.Timer（Gradio 6.x）
            auto_refresh_timer = gr.Timer(value=DEFAULT_REFRESH_INTERVAL, active=True)
            auto_refresh_timer.tick(
                fn=auto_refresh_latest,
                inputs=[],
                outputs=[
                    event_id_text,
                    timestamp_text,
                    world_state_box,
                    role_states_box,
                    status_text,
                ],
            )

        # ======================== 历史回溯 ========================
        with gr.TabItem("历史回溯"):
            gr.Markdown("### 查询历史状态快照")

            with gr.Row():
                history_dropdown = gr.Dropdown(
                    label="选择历史事件",
                    choices=[],
                    value=None,
                    interactive=True,
                )
                load_list_btn = gr.Button("📋 加载事件列表")
                load_snapshot_btn = gr.Button("🔍 加载选中状态", variant="primary")

            with gr.Row():
                history_world_box = gr.Textbox(
                    label="历史世界状态",
                    value="选择事件并点击加载...",
                    lines=20,
                    max_lines=30,
                    interactive=False,
                    autoscroll=False,
                )
                history_role_box = gr.Textbox(
                    label="历史角色状态",
                    value="",
                    lines=20,
                    max_lines=30,
                    interactive=False,
                    autoscroll=False,
                )

            history_status_text = gr.Textbox(
                label="状态",
                value="等待操作...",
                interactive=False,
            )

            # 绑定按钮事件
            load_list_btn.click(
                fn=load_history_dropdown,
                inputs=[],
                outputs=[history_dropdown],
            )

            load_snapshot_btn.click(
                fn=load_history_snapshot,
                inputs=[history_dropdown],
                outputs=[
                    history_world_box,
                    history_role_box,
                    history_status_text,
                ],
            )

    gr.Markdown("---")
    gr.Markdown(
        "**提示**：确保 AURA 后端已启动在 `http://127.0.0.1:8000`，"
        "且 `/debug` 路由已挂载。"
    )


# ------------------------------------------------------------------
# 入口
# ------------------------------------------------------------------

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        show_error=True,
    )
