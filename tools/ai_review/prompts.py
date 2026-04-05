#!/usr/bin/env python3
from __future__ import annotations

import json
import textwrap


REVIEWER_SYSTEM = (
    "你是一名资深软件审查工程师。请使用简体中文输出，结论必须基于输入证据。"
    "允许结合上下文做推断，但必须明确区分直接证据与上下文推断。"
    "不要编造仓库中不存在的事实。"
)

FIXER_SYSTEM = (
    "你是一名谨慎的软件修复工程师。请基于审查报告和上下文证据生成最小必要修复。"
    "必须使用简体中文。只修复有明确证据支持的问题，不做大规模重构。"
    "输出必须是合法 JSON，不要使用 Markdown 代码块。"
)


def _context_excerpt(payload: dict) -> str:
    context = payload.get("mcp_context") or {}
    if not context:
        return "无 MCP 上下文。"
    compact = {
        "mcp_enabled": context.get("mcp_enabled"),
        "mcp_sources": context.get("mcp_sources", []),
        "degraded": context.get("degraded", False),
        "degraded_reasons": context.get("degraded_reasons", []),
        "changed_files": context.get("changed_files", []),
        "impacted_files": context.get("impacted_files", []),
        "related_files": context.get("related_files", []),
        "related_configs": context.get("related_configs", []),
        "related_commit_messages": context.get("related_commit_messages", []),
        "related_issues": context.get("related_issues", []),
        "related_prs": context.get("related_prs", []),
        "recent_failed_runs": context.get("recent_failed_runs", []),
        "commit_checks": context.get("commit_checks", []),
        "external_search": context.get("external_search", []),
        "policy_assessment": context.get("policy_assessment", {}),
    }
    return json.dumps(compact, ensure_ascii=False, indent=2)


def build_reviewer_prompt(role: str, payload: dict) -> str:
    files = "\n".join(f"- {path}" for path in payload.get("included_files", []))
    skipped = payload.get("skipped_count", payload.get("skipped_files", 0))
    role_focus = {
        "code": "重点检查逻辑缺陷、数据流、调用链影响面、边界条件和回归风险。",
        "security": "重点检查密钥、认证、权限、危险默认值、网络暴露、依赖与 workflow 风险。",
        "docs-runtime": "重点检查文档漂移、部署步骤、配置一致性、运行时缺口和可观测性。",
        "operations": "重点检查部署可靠性、高可用、告警、故障恢复和运维风险。",
        "code-health": "重点检查可维护性、重复逻辑、结构退化和测试缺口。",
        "workflow-release": "重点检查 CI/CD、发布流程、权限、安全与自动化漂移。",
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

        审查规则:
        1. diff 是触发点，不是全部事实来源。
        2. 必须优先引用直接证据；如使用 MCP 上下文推断，需写明“上下文推断”。
        3. 不要因为上下文不足而编造问题。
        4. 高风险问题优先，重复问题合并。

        请严格输出 Markdown，并使用以下标题:
        ## 总结
        用一小段说明整体结论。
        ## 发现
        - 每条问题格式:
          [严重级别] 路径 - 问题、影响、建议；如属上下文推断，需在句内注明“上下文推断”
        - 如果没有重要问题，必须原样输出:
          - 未发现需要优先处理的重大问题。
        ## 测试缺口
        - 说明最重要的验证缺口；如果没有，必须原样输出:
          - 本轮审查未识别出关键的额外测试缺口。

        原始 diff:
        {payload.get('review_material', '')}

        MCP 上下文包:
        {_context_excerpt(payload)}
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
        你是 {label} 的 coordinator。
        请把多个 reviewer 的输出合并成一份简洁、去重、证据优先的最终报告。
        如果 reviewer 使用了上下文推断，请保留该标记。
        如果 MCP 上下文降级或部分失败，也必须在总结中点出。

        请严格输出 Markdown，并使用以下标题:
        ## 总结
        用一小段说明整体结论。
        ## 发现
        - 合并后的高价值问题，按严重程度排序。
        - 如果没有重要问题，必须原样输出:
          - 未发现需要优先处理的重大问题。
        ## 测试缺口
        - 说明最重要的测试或验证缺口；如果没有，必须原样输出:
          - 本轮审查未识别出关键的额外测试缺口。
        ## Agent 明细
        - 每个 reviewer 一条，格式为 `角色: ok` 或 `角色: failed: 原因`

        上下文:
        仓库: {payload.get('repository')}
        当前提交: {payload.get('head_sha')}
        MCP 上下文:
        {_context_excerpt(payload)}

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
        你要根据下面的 AI 审查报告和 MCP 上下文，对仓库进行一次“谨慎、自包含、最小必要”的自动修复。

        约束:
        1. 只允许修改已提供内容的文件。
        2. 只修复审查报告中明确提到，且能从 diff 或 MCP 上下文确认的问题。
        3. 不要做大规模重构，不要改变业务语义，不要新增密钥。
        4. 如果没有明确可自动修复的问题，请返回空变更。
        5. 输出必须是 JSON，格式严格如下:
        {{
          "summary": "一句中文总结",
          "root_cause_guess": "根因判断",
          "evidence_sources": ["diff", "mcp.related_issues"],
          "changes": [
            {{
              "path": "相对路径",
              "content": "修复后的完整文件内容"
            }}
          ]
        }}

        仓库: {payload.get('repository')}
        基线提交: {payload.get('base_sha')}
        当前提交: {payload.get('head_sha')}

        审查报告:
        {report_text}

        MCP 上下文:
        {_context_excerpt(payload)}

        可修改文件当前内容:
        {files_json}
        """
    ).strip()
