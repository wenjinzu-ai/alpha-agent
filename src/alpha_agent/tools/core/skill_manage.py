"""skill_manage 工具 —— 技能全生命周期管理（渐进式加载）。

借鉴 Hermes 的 skills_tool + skill_manager_tool 设计：
  渐进式加载（Progressive Disclosure）:
    Tier 1: list/search → 只返回元数据 (name≤64, description≤1024)
    Tier 2: view → 加载完整技能内容
    Tier 3: view(ref_file) → 按需加载参考文件

  生命周期管理:
    create/patch/edit/fork/retire/delete

Hermes 参考：
  - tools/skills_tool.py: skills_list + skill_view (渐进式加载)
  - tools/skill_manager_tool.py: SKILL_MANAGE_SCHEMA
  - agent/skill_utils.py: 技能目录管理
"""
from typing import Optional
from langchain_core.tools import tool

from alpha_agent.infra.skill_store import skill_store
from alpha_agent.utils.logger import logger


@tool
def skill_manage(
    action: str,
    name: str = "",
    content: Optional[str] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    new_name: Optional[str] = None,
    old_string: Optional[str] = None,
    new_string: Optional[str] = None,
    replace_all: bool = False,
    query: Optional[str] = None,
    limit: int = 20,
    force: bool = False,
) -> str:
    """技能全生命周期管理工具（渐进式加载）。

    借鉴 Hermes 的 skills_tool + skill_manager_tool 设计。

    渐进式加载（Progressive Disclosure）:
      Tier 1: list/search → 只返回元数据 (name + description + category)，不返回完整内容
      Tier 2: view → 加载完整技能内容（仅在需要执行时加载）

    何时使用：
    - 执行任务前先 search 查找已有技能，复用成熟方案
    - 找到技能后用 view 加载完整内容再执行
    - 用户完成了复杂任务，想保存为可复用技能 → create
    - 需要修正技能中的某个步骤或命令 → patch
    - 需要完整重写技能内容 → edit
    - 从现有技能变体创建一个新技能 → fork
    - 技能不再适用 → retire
    - 查看技能列表 → list

    Args:
        action: 操作类型 (create/patch/edit/fork/retire/delete/list/search/view)
        name: 技能名称（小写、连字符，如 "sync-stock-kline"）
        content: 技能内容（create/edit 时使用）
        category: 分类（如 "data-sync", "analysis", "maintenance"）
        description: 技能描述
        new_name: fork 时的新名称
        old_string: patch 时查找的文本
        new_string: patch 时替换的文本
        replace_all: patch 时是否替换所有匹配项
        query: search 时的搜索关键词
        limit: list/search 时返回的最大数量
        force: 是否强制删除置顶技能
    """
    try:
        if action == "create":
            if not name or not content:
                return "错误: create 操作需要 name 和 content 参数"
            skill = skill_store.create_skill(
                name=name,
                content=content,
                category=category or "general",
                description=description or "",
                display_name=name,
                source="agent_created",
                created_by="agent",
            )
            return f"✅ 技能已创建: {skill.name} (category={skill.category}, version={skill.version})"

        elif action == "patch":
            if not name or not old_string:
                return "错误: patch 操作需要 name 和 old_string 参数"
            skill = skill_store.patch_skill(
                name=name,
                old_string=old_string,
                new_string=new_string or "",
                replace_all=replace_all,
            )
            return f"✅ 技能已修补: {skill.name} (version={skill.version})"

        elif action == "edit":
            if not name:
                return "错误: edit 操作需要 name 参数"
            skill = skill_store.edit_skill(
                name=name,
                content=content,
                description=description,
                category=category,
            )
            return f"✅ 技能已编辑: {skill.name} (version={skill.version})"

        elif action == "fork":
            if not name or not new_name:
                return "错误: fork 操作需要 name 和 new_name 参数"
            skill = skill_store.fork_skill(name=name, new_name=new_name, created_by="agent")
            return f"✅ 技能已分叉: {name} -> {new_name}"

        elif action == "retire":
            if not name:
                return "错误: retire 操作需要 name 参数"
            skill = skill_store.retire_skill(name=name)
            return f"✅ 技能已退役: {skill.name}"

        elif action == "delete":
            if not name:
                return "错误: delete 操作需要 name 参数"
            skill_store.delete_skill(name=name, force=force)
            return f"✅ 技能已删除: {name}"

        elif action == "list":
            skills = skill_store.list_skills(
                category=category,
                sort_by="use_count",
                limit=limit,
            )
            if not skills:
                return "暂无技能。使用 create 创建第一个技能。"
            lines = [f"技能列表 ({len(skills)} 个):"]
            for s in skills:
                status_flag = "📌" if s.pinned else ""
                retired = " [已退役]" if s.status == "retired" else ""
                lines.append(
                    f"  {status_flag} {s.name} [{s.category}] "
                    f"v{s.version} 使用{s.use_count}次{retired}"
                )
            return "\n".join(lines)

        elif action == "view":
            if not name:
                return "错误: view 操作需要 name 参数"
            skill = skill_store.get_skill(name)
            if not skill:
                return f"未找到技能: {name}"
            lines = [
                f"# {skill.name} (v{skill.version})",
                f"分类: {skill.category}",
                f"描述: {skill.description}",
                f"使用次数: {skill.use_count}",
                f"---",
                skill.content,
            ]
            return "\n".join(lines)

        elif action == "search":
            if not query:
                return "错误: search 操作需要 query 参数"
            skills = skill_store.search_skills(query=query, category=category, limit=limit)
            if not skills:
                return f"未找到匹配 '{query}' 的技能。"
            lines = [f"搜索 '{query}' 结果 ({len(skills)} 个):"]
            for s in skills:
                lines.append(f"  {s.name} [{s.category}] - {s.description[:80]}")
            return "\n".join(lines)

        else:
            return f"错误: 未知操作 '{action}'。支持: create, patch, edit, fork, retire, delete, list, search, view"

    except ValueError as e:
        return f"❌ 操作失败: {e}"
    except Exception as e:
        logger.error(f"skill_manage error: {e}", exc_info=True)
        return f"❌ 内部错误: {e}"