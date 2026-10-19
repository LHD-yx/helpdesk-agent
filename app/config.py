"""全局配置层。

约定：项目里任何地方要读配置，都只允许 `from app.config import get_settings`。
不允许在业务代码里出现 os.getenv 或硬编码的 API 地址。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：本文件在 app/ 里，往上退一级就是项目根。
BASE_DIR = Path(__file__).resolve().parent.parent

# 各家「OpenAI 兼容」服务的预设。键就是 .env 里 LLM_PROVIDER 的取值。
# base_url 一律带 /v1，这是 OpenAI 兼容协议的路径约定。
PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        # 以硅基流动控制台「模型广场」的当前 ID 为准，模型 ID 会更新
        "model": "deepseek-ai/DeepSeek-V3",
    },
    "siliconflow-free": {
        "base_url": "https://api.siliconflow.cn/v1",
        # 免费模型，用来跑评测集、做不敏感时间的批量任务
        "model": "Qwen/Qwen2.5-7B-Instruct",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
    },
}


def preset_for(provider: str) -> dict[str, str]:
    """按供应商名取预设。

    名字写错时，报错信息里直接把所有合法取值列出来——
    让人不用翻源码就知道怎么改。
    """
    preset = PROVIDER_PRESETS.get(provider)
    if preset is None:
        raise ValueError(
            f"未知的 provider='{provider}'。"
            f"可选：{sorted(PROVIDER_PRESETS)}；"
            f"或者直接用 LLM_BASE_URL / LLM_MODEL 显式指定。"
        )
    return preset


class Settings(BaseSettings):
    """全部配置项集中在这里。字段名小写，环境变量名大写，pydantic 自动对应。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",  # 必须写，否则 Windows 下中文注释易乱码
        extra="ignore",             # .env 里多写的变量不报错，方便临时调试
        case_sensitive=False,       # LLM_API_KEY 和 llm_api_key 都认
    )

    # ---------- LLM ----------
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = ""   # 留空则回落到预设
    llm_model: str = ""      # 留空则回落到预设
    llm_temperature: float = 0.2
    llm_timeout: float = 30.0
    llm_max_retries: int = 2

    # 备用供应商：主供应商挂了自动切过去。留空 = 不启用降级。
    llm_fallback_provider: str = ""
    llm_fallback_api_key: str = ""

    # ---------- 应用 ----------
    app_env: str = "dev"
    log_level: str = "INFO"

    # ---------- 派生属性：把「预设 + 可覆盖」这件事只实现一次 ----------
    @property
    def resolved_base_url(self) -> str:
        return self.llm_base_url or preset_for(self.llm_provider)["base_url"]

    @property
    def resolved_model(self) -> str:
        return self.llm_model or preset_for(self.llm_provider)["model"]

    @property
    def has_fallback(self) -> bool:
        """只有供应商名和 key 都配了，才认为降级可用。"""
        return bool(self.llm_fallback_provider and self.llm_fallback_api_key)

    def validate_providers(self) -> None:
        """启动即校验供应商配置：配错了立刻炸，不要等第一次调用模型才发现。

        这里故意不用 pydantic 的 @model_validator —— pydantic 会把整个
        输入字典回显进错误信息（含 api key 前缀），报错里不该出现密钥。
        用裸 ValueError，消息干净、只带必要信息。
        """
        if self.llm_provider not in PROVIDER_PRESETS:
            # 留一个后门：只要同时显式给了 base_url 和 model，就允许自定义服务
            if not (self.llm_base_url and self.llm_model):
                raise ValueError(
                    f"未知的 LLM_PROVIDER='{self.llm_provider}'。"
                    f"可选：{sorted(PROVIDER_PRESETS)}；"
                    f"或者同时设置 LLM_BASE_URL 和 LLM_MODEL 指向自定义服务。"
                )
        if self.llm_fallback_provider and self.llm_fallback_provider not in PROVIDER_PRESETS:
            raise ValueError(
                f"未知的 LLM_FALLBACK_PROVIDER='{self.llm_fallback_provider}'。"
                f"可选：{sorted(PROVIDER_PRESETS)}。"
            )

    @property
    def masked_key(self) -> str:
        """打印日志用的脱敏 key。任何时候都不要把完整 key 写进日志。"""
        key = self.llm_api_key
        if not key:
            return "(未配置)"
        if len(key) <= 12:
            return "***"
        return f"{key[:6]}...{key[-4:]}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例。全项目共用一份配置，避免反复读盘、也避免各处配置不一致。"""
    settings = Settings()
    # 校验放在这里，而不是放在类定义里：get_settings() 是全项目唯一的配置入口，
    # 从这里卡住，等于所有调用方都自动获得 fail-fast。
    settings.validate_providers()
    return settings
