#!/usr/bin/env python3
from __future__ import annotations

import textwrap


REVIEWER_SYSTEM = (
    "你是一名资深软件审查工程师。请使用简体中文输出，保持结论准确、简洁、高信号。"
    "绝不编造仓库快照中不存在的事实。"
)

FIXER_SYSTEM = (
    "你是一名资深修复工程师。请基于审查结论直接生成可落地的修复方案。"
    "必须使用简体中文。只修复有明确证据支持的问题，不得编造需求。"
    "输出必须是合法 JSON，不要包裹 Markdown 代码块。"
)


def build_reviewer_prompt(role: str, payload: dict) -> str:
    files = "\n".join(f"- {path}" for path in payload.get("included_files", []))
    skipped = payload.get("skipped_files", 0)
    role_focus = {
        "code": "重点检查逻辑缺陷、回归风险、数据流问题和缺失验证。",
        "security": "重点检查密钥泄露、危险默认值、认证、网络暴露、命令执行风险和 workflow 滥用。",
        "docs-runtime": "重点检查文档失真、运维手册、部署一致性和运行时可观测性缺口。",
        "operations": "重点检查可部署性、高可用行为、运行健康度和事故风险。",
        "code-health": "重点检查可维护性、正确性、重复代码和测试缺口。",
        "workflow-release": "重点检查 CI/CD 正确性、自动化安全、发布漂移和密钥处理。",
    }.get(role, "重点检查最重要的工程风险。")

    return textwrap.dedent(
        f"""
        仓库: {payload.get('repository')}
        基线提交: {payload.get('base_sha')}
        当前提交: {payload.get('head_sha')}
        审查角色: {role}

        {role_focus}

        已纳入审查的文件:
        {files or "- none"}

        因限制被跳过的文件数: {skipped}

        请严格输出 Markdown，并使用以下标题:
        ## 总结
        用一小段话说明整体结论。

        ## 发现
        - 使用项目符号，格式为:
          [严重级别] 路径 - 问题、影响、建议修复
        - 如果没有重要问题，必须原样输出:
          - 未发现需要优先处理的重大问题。

        ## 测试缺口
        - 说明最重要的缺失验证；如果没有，必须原样输出:
          - 本轮审查未识别出关键的额外测试缺口。

        审查材料:
        {payload.get('review_material', '')}
        """
    ).strip()


def build_coordinate_prompt(kind: str, payload: dict, reviewer_results: list[dict]) -> str:
    sections = []
    for result in reviewer_results:
        role = result.get("role", "unknown")
        if result.get("ok"):
            sections.append(f"### Reviewer: {role}\n{result.get('content', '')}")
        else:
            sections.append(f"### Reviewer: {role}\nFAILED: {result.get('error', 'unknown error')}")

    label = "AI 代码审查" if kind == "review" else "AI 仓库巡查"
    joined = "\n\n".join(sections)
    return textwrap.dedent(
        f"""
        你是 {label} 的协调员。
        请将多个 reviewer 的输出合并成一份简洁、明确、去重后的最终报告。
        保留高价值问题，并明确指出失败的 agent。

        请严格输出 Markdown，并使用以下标题:
        ## 总结
        用一小段话说明整体结论。

        ## 发现
        - 合并后的问题，按严重程度排序。
        - 如果没有重要问题，必须原样输出:
          - 未发现需要优先处理的重大问题。

        ## 测试缺口
        - 说明最重要的缺失验证；如果没有，必须原样输出:
          - 本轮审查未识别出关键的额外测试缺口。

        ## Agent 明细
        - 每个 reviewer 角色一条项目符号，状态写成 `ok` 或 `failed: <原因>`。

        上下文:
        仓库: {payload.get('repository')}
        当前提交: {payload.get('head_sha')}

        Reviewer 输出:
        {joined}
        """
    ).strip()


def build_fix_prompt(payload: dict, report_text: str, file_snapshots: list[dict]) -> str:
    files_json = "\n\n".join(
        f"### {item['path']}\n```text\n{item['content']}\n```" for item in file_snapshots
    )
    return textwrap.dedent(
        f"""
        你要根据下面的 AI 审查报告，对仓库进行一次“谨慎、自包含、最小必要”的自动修复。

        约束：
        1. 只允许修改已提供内容的文件。
        2. 只修复审查报告中明确提到、且能从上下文确认的问题。
        3. 不要做大规模重构，不要改业务语义，不要新增密钥。
        4. 如果报告没有明确可自动修复的问题，请返回空变更。
        5. 输出必须是 JSON，格式严格如下：
        {{
          "summary": "一句中文总结",
          "changes": [
            {{
              "path": "相对路径",
              "content": "该文件修复后的完整文本内容"
            }}
          ]
        }}

        仓库: {payload.get('repository')}
        基线提交: {payload.get('base_sha')}
        当前提交: {payload.get('head_sha')}

        本次审查报告：
        {report_text}

        可修改文件当前内容：
        {files_json}
        """
    ).strip()
