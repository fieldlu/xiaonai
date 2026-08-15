from pydantic_settings import BaseSettings, SettingsConfigDict


class BotConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="allow")

    mimo_api_key: str = ""
    mimo_base_url: str = "https://opencode.ai/zen/go/v1"
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


bot_config = BotConfig()  # type: ignore[call-arg]
