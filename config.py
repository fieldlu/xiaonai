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

    # 识图专用通道（可选）：智谱 GLM-4.6V-Flash（免费视觉模型；不切付费 glm-4.5v，
    # 2026-09-03 定版全链免费）。Sensenova free 多模态识图常被服务端 429（图片后端繁忙）
    # 而文本正常——因此识图与文本主模型解耦：配置了 glm_api_key 后，识图请求走 GLM，
    # 文本对话仍走 active_*。未配置 glm_api_key 时 vision_* 自动回退到 active_*。
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    glm_model: str = "glm-4.6v-flash"
    # 文本回退链第二顺位用的 GLM 文本模型（免费，2026-09-03 定版）
    glm_text_model: str = "glm-4.7-flash"

    # Agnes（识图首选通道，2026-09-03）：agnes-2.5-flash，OpenAI 兼容 chat/completions，
    # 支持 image_url 输入（实测 base64 data URI 可用，2.5s 出描述），现价 ¥0/百万 token。
    agnes_api_key: str = ""
    agnes_base_url: str = "https://api.agnes-ai.cn/v1"
    agnes_model: str = "agnes-2.5-flash"

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

    @property
    def text_openclaw_chain(self) -> list[str]:
        """文本回复生成回退链（OpenClaw provider/model 前缀形式，2026-09-03 用户定版，全免费）：

        Sensenova(active_*) → GLM-4.7-flash（免费文本档）→ Agnes（agnes-2.5-flash，¥0）。
        Sensenova 超时/挂掉时依次降级；provider 需在 ~/.openclaw/openclaw.json 注册同名条目。
        """
        chain = [self.active_openclaw_model]
        if self.glm_api_key:
            chain.append(f"glm/{self.glm_text_model}")
        if self.agnes_api_key:
            chain.append(f"agnes/{self.agnes_model}")
        return chain

    # ---- 识图通道分派（vision_*）----
    # 识图与文本解耦：配置 glm_api_key（智谱 GLM-4.6V-Flash 免费视觉模型）时识图走 GLM；
    # 否则回退 active_*（当前为 Sensenova），保持改造前行为。
    @property
    def vision_base_url(self) -> str:
        return self.glm_base_url if self.glm_api_key else self.active_base_url

    @property
    def vision_api_key(self) -> str:
        return self.glm_api_key if self.glm_api_key else self.active_api_key

    @property
    def vision_model(self) -> str:
        return self.glm_model if self.glm_api_key else self.active_model


bot_config = BotConfig()  # type: ignore[call-arg]
