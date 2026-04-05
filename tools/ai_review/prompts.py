#!/usr/bin/env python3
from __future__ import annotations

import json
import textwrap


REVIEWER_SYSTEM = (
    "你是一名资深软件审查工程师。请始终使用简体中文。"
    "你的目标不是挑语法和格式，而是判断这次改动会不会让真实业务出问题。"
    "请先理解仓库在做什么，再审查代码。"
    "允许结合上下文做推断，但必须明确区分“直接证据”和“上下文推断”，不要编造仓库里不存在的事实。"
)

FIXER_SYSTEM = (
    "你是一名谨慎的软件修复工程师。请始终使用简体中文。"
    "只修复有明确证据支持的问题，只做最小必要改动，不做大重构，不引入新密钥，不改变业务语义。"
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


def _role_focus(role: str) -> str:
    return {
        "code": "重点检查业务流程、数据流、调用链、重连补偿、静默失败、边界条件和回归风险。",
        "security": "重点检查密钥、认证、权限、危险默认值、外部网络暴露、依赖和 workflow 风险。",
        "docs-runtime": "重点检查部署步骤、运行一致性、文档失真、监控缺口、运维可观测性。",
        "operations": "重点检查高可用、容灾、告警、故障恢复、数据连续性和运维风险。",
        "code-health": "重点检查结构退化、重复逻辑、维护成本、模块边界和长期稳定性。",
        "workflow-release": "重点检查 CI/CD、发布流程、自动化权限、回滚能力和流水线漂移。",
    }.get(role, "重点检查最重要的工程和业务风险。")


def _business_focus() -> str:
    return textwrap.dedent(
        """
        这个仓库大概率不是普通网站，而是 CTP 行情/数据抓取与分发系统。审查时请优先判断下面这些“代码能跑但业务可能仍然失败”的问题：
        1. 数据源是否过于单一，某个行情地址失效后是否会直接断流。
        2. 账号、认证、BrokerID、前置地址是否和代码强耦合，换公司接口时是否容易失效。
        3. 是否存在“静默回退”到默认配置、默认账号、默认 demo 数据的行为，让系统看起来正常但其实没连上真实链路。
        4. 是否可能出现“进程还活着，但其实已经抓不到新数据”的静默失败。
        5. 重连、心跳、失败切换、消息堆积、重复数据、脏数据、过期数据是否处理到位。
        6. seed、worker、admin、dashboard、Kafka、Redis、MySQL 这些组件是否真的串成完整闭环，而不是各自能启动但业务链路不通。
        7. 高可用是否只是部署层面看起来有多实例，但真实数据链路仍然单点。
        8. 合约列表、订阅逻辑、月份切换、交易日切换是否可能导致“程序正常但漏抓关键行情”。
        9. 指标、涨跌幅、最新价等展示口径是否可能和真实业务口径不一致，误导人判断。
        10. 如果这次改动碰到运行配置、接口地址、认证解析、Docker、workflow，请提高风险判断，不要轻易给乐观结论。
        """
    ).strip()


def build_reviewer_prompt(role: str, payload: dict) -> str:
    files = "\n".join(f"- {path}" for path in payload.get("included_files", []))
    skipped = payload.get("skipped_count", payload.get("skipped_files", 0))

    return textwrap.dedent(
        f"""
        仓库: {payload.get('repository')}
        基线提交: {payload.get('base_sha')}
        当前提交: {payload.get('head_sha')}
        审查角色: {role}

        {_role_focus(role)}

        已纳入审查的文件:
        {files or "- none"}

        因限制被跳过的文件数: {skipped}

        审查方法要求:
        1. 先回答“这个仓库是在干什么”，再判断这次改动会不会伤到这个业务。
        2. diff 只是触发点，不是全部事实来源；必须结合 MCP bundle 理解仓库目的、上下游和历史风险。
        3. 优先找隐藏的业务问题，不要把篇幅浪费在格式、命名、小重构建议上。
        4. 只输出 1 到 3 个最有价值的问题；如果没有，就明确说这轮没看到值得立刻处理的大问题。
        5. 每个问题都要写清楚：问题是什么、为什么对业务有影响、你是根据什么判断的。
        6. 能直接从输入里看到的，标注“直接证据”；需要结合上下文推断的，标注“上下文推断”。
        7. 用大白话写，尽量让产品、运营、老板也能看懂，避免堆专业术语。
        8. 如果 MCP 降级、工具缺失、证据不足，要直接说，不要装作自己已经看全了。

        CTP 业务重点检查清单:
        {_business_focus()}

        请严格输出 Markdown，并使用以下标题:
        ## 这个仓库是在干什么
        用 2 到 4 句话解释仓库目标、主链路和你判断依据。

        ## 最值得注意的 1-3 个问题
        - 每条格式:
          [高/中/低] 一句话问题标题
          影响: 用大白话说明会出什么事。
          判断依据: 直接证据 / 上下文推断 + 依据。
          建议: 只给最实际的建议。
        - 如果没有明显问题，原样输出:
          - 这轮没看到需要立刻处理的大问题。

        ## 大白话建议
        - 给 1 到 3 条最值得做的动作。

        ## 测试/验证缺口
        - 只写最关键的验证缺口；如果没有，原样输出:
          - 这轮没有额外必须补的验证动作。

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
        你要把多个 reviewer 的输出合并成一份短、小、准、能让非技术同学看懂的中文报告。

        合并要求:
        1. 先说明“这个仓库是在干什么”，证明你真的理解了仓库主业务。
        2. 只保留 1 到 3 个最重要的问题，不要把 issue 写成长文。
        3. 优先指出业务层、流程层、数据链路层的风险，而不是语法、格式、命名。
        4. 如果只是上下文推断，必须明确写“上下文推断”，不要冒充实锤。
        5. 如果 MCP 降级、证据不完整、某些 reviewer 失败，也要说清楚，不要假装看全了。
        6. 输出要口语化、大白话，不要写成论文，不要复述整段 reviewer 原文。

        请严格输出 Markdown，并使用以下标题:
        ## 这个仓库是在干什么
        用 2 到 4 句话说明仓库目标、关键链路、你为何这么判断。

        ## 最值得注意的 1-3 个问题
        - 每条格式:
          [高/中/低] 一句话问题标题
          影响: 用大白话说明真实后果。
          判断依据: 直接证据 / 上下文推断 + 依据。
          建议: 一句最实际的建议。
        - 如果没有明显问题，原样输出:
          - 这轮没看到需要立刻处理的大问题。

        ## 大白话建议
        - 给 1 到 3 条最值得做的动作。

        ## 测试/验证缺口
        - 只写最关键的验证缺口；如果没有，原样输出:
          - 这轮没有额外必须补的验证动作。

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
        5. 输出必须是 JSON，格式如下:
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
