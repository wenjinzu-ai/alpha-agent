from typing import Optional, Dict, Any
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage
from langchain_core.output_parsers import StrOutputParser

from alpha_agent.config import settings
from alpha_agent.utils.logger import logger


class LLMService:
    def __init__(self):
        self._model: Optional[BaseChatModel] = None
        self._enabled: bool = False
        self._init_done: bool = False

    @property
    def enabled(self) -> bool:
        self._ensure_init()
        return self._enabled

    @property
    def model(self) -> Optional[BaseChatModel]:
        self._ensure_init()
        return self._model

    def _ensure_init(self):
        if self._init_done:
            return
        try:
            if not settings.llm_api_key or settings.llm_api_key == "sk-your-api-key":
                logger.warning("LLM API Key 未配置，LLM 功能禁用")
                self._enabled = False
                self._init_done = True
                return

            from langchain_openai import ChatOpenAI

            self._model = ChatOpenAI(
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                temperature=settings.llm_temperature,
                timeout=120,
                max_tokens=4096,
                max_retries=3,
            )
            self._enabled = True
            logger.info(f"LLM 初始化完成: provider={settings.llm_provider}, model={settings.llm_model}")
        except Exception as e:
            logger.warning(f"LLM 初始化失败: {e}")
            self._enabled = False
        self._init_done = True

    def chat(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        if not self.enabled:
            return ""
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            response = self._model.invoke(messages, **kwargs)
            parser = StrOutputParser()
            return parser.invoke(response)
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return ""

    def chat_with_messages(self, messages: list, **kwargs) -> str:
        if not self.enabled:
            return ""
        try:
            response = self._model.invoke(messages, **kwargs)
            parser = StrOutputParser()
            return parser.invoke(response)
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return ""

    def structured_output(self, system_prompt: str, user_prompt: str, schema) -> Optional[Any]:
        if not self.enabled:
            return None
        try:
            from langchain_core.prompts import ChatPromptTemplate
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("human", user_prompt),
            ])
            chain = prompt | self._model.with_structured_output(schema)
            return chain.invoke({})
        except Exception as e:
            logger.error(f"LLM 结构化输出失败: {e}")
            return None


_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service