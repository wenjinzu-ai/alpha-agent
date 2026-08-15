"""Profile 系统 —— 将 Worker 的 prompt+工具配置转为 YAML Profile。

delegate_task 概念：
  - 每个 Profile 包含 system_prompt、tools、max_iterations 等
  - delegate_task 时加载 Profile，创建专用子 Agent
  - 用 YAML 文件存储，便于版本控制和团队共享
"""
from pathlib import Path
from typing import Any

import yaml

PROFILES_DIR = Path(__file__).parent.parent.parent.parent / "profiles"


class ProfileLoader:
    """Profile 加载器，管理 YAML Profile 的读取和缓存。"""

    def __init__(self, profiles_dir: Path | None = None):
        self._profiles_dir = profiles_dir or PROFILES_DIR
        self._cache: dict[str, dict] = {}

    def list_profiles(self) -> list[str]:
        return sorted([
            p.stem
            for p in self._profiles_dir.glob("*.yaml")
            if not p.name.startswith("_")
        ])

    def load(self, name: str) -> dict[str, Any]:
        if name in self._cache:
            return self._cache[name]

        profile_path = self._profiles_dir / f"{name}.yaml"
        if not profile_path.exists():
            raise FileNotFoundError(
                f"Profile '{name}' not found at {profile_path}. "
                f"Available: {self.list_profiles()}"
            )

        with open(profile_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self._cache[name] = data
        return data

    def get_system_prompt(self, name: str) -> str:
        return self.load(name).get("system_prompt", "")

    def get_tools(self, name: str) -> list[str]:
        return self.load(name).get("tools", [])

    def get_max_iterations(self, name: str) -> int:
        return self.load(name).get("max_iterations", 10)

    def get_display_name(self, name: str) -> str:
        return self.load(name).get("display_name", name)

    def invalidate_cache(self, name: str | None = None):
        if name:
            self._cache.pop(name, None)
        else:
            self._cache.clear()

    def get_profile_summary(self, name: str) -> str:
        profile = self.load(name)
        return (
            f"Profile: {profile['name']} ({profile['display_name']})\n"
            f"Description: {profile['description']}\n"
            f"Tools: {', '.join(profile.get('tools', []))}\n"
            f"Max Iterations: {profile.get('max_iterations', 10)}"
        )


profile_loader = ProfileLoader()
