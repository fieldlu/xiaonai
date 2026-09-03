from pydantic_settings import BaseSettings, SettingsConfigDict


class BotConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="allow")

    # ---- LLM 提供者 ----
    # 默认商汤日日新 SenseNova 6.8-flash-lite；可经 llm_provider=mimo 一键切回小米 MiMo V2.5。
    # 两套凭据/端点独立存放（MiMo 保留作将来续费回切）；active_* 按开关解析出当前生效的一组。
    llm_provider: str = "sensenova"  # "mimo" | "sensenova"

    # MiMo（保留作备选回切）
    mimo_api_key: str = ""
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    mimo_model: str = "mimo-v2.5"

    # Sensenova（商汤日日新）
    sensenova_api_key: str = ""
    sensenova_base_url: str = "https://token.sensenova.cn/v1"
    sensenova_model: str = "sensenova-6.8-flash-lite"

    # 其它（天气等，非 LLM 主链路）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    qw_api_key: str = ""
    qw_api_host: str = ""
    none_bot_port: int = 8080
    bot_admins: list[int] = []
    news_groups: list[int] = []
    weather_groups: list[int] = []
    default_city: str = "武汉"

    # WHUT WebVPN credentials
    whut_username: str = ""
    whut_password: str = ""
    whut_vpn_ticket: str = ""
    webvpn_proxy: str = ""

    # ---- 动态分派 ----
    @property
    def active_base_url(self) -> str:
        """当前生效的 OpenAI 兼容端点（调用点用这个）。"""
        return self.sensenova_base_url if self.llm_provider == "sensenova" else self.mimo_base_url

    @property
    def active_api_key(self) -> str:
        """当前生效的 API Key。"""
        return self.sensenova_api_key if self.llm_provider == "sensenova" else self.mimo_api_key

    @property
    def active_model(self) -> str:
        """当前生效的模型名。"""
        return self.sensenova_model if self.llm_provider == "sensenova" else self.mimo_model

    @property
    def active_openclaw_model(self) -> str:
        """OpenClaw CLI 的 --model 参数（provider/model 前缀形式）。

        链路 B（人格层 call_openclaw）经 openclaw.json 的 models.providers 解析此前缀。
        sensenova → sensenova/sensenova-6.8-flash-lite；mimo → mimo/mimo-v2.5。
        与 llm_provider 联动，实现链路 A + 链路 B 一键回切。
        """
        prov = "sensenova" if self.llm_provider == "sensenova" else "mimo"
        mdl = self.sensenova_model if self.llm_provider == "sensenova" else self.mimo_model
        return f"{prov}/{mdl}"


bot_config = BotConfig()  # type: ignore[call-arg]
