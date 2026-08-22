from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings


class SecretEncryptionError(RuntimeError):
    pass


class ProviderSecretCipher:
    def __init__(self, settings: Settings | None = None) -> None:
        raw_key = (settings or get_settings()).ai_provider_secret_key.strip()
        if not raw_key:
            raise SecretEncryptionError(
                "系统尚未配置 AI_PROVIDER_SECRET_KEY，无法安全保存 Provider 密钥"
            )
        try:
            self._fernet = Fernet(raw_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise SecretEncryptionError("AI_PROVIDER_SECRET_KEY 格式无效") from exc

    def encrypt(self, secret: str) -> str:
        value = secret.strip()
        if not value:
            raise SecretEncryptionError("Provider API Key 不能为空")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError) as exc:
            raise SecretEncryptionError("Provider 密钥无法解密，请重新填写") from exc


def secret_hint(secret: str) -> str:
    suffix = secret.strip()[-4:]
    return f"••••••••{suffix}" if suffix else "••••••••"
