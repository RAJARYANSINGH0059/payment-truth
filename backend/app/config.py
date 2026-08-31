import os


class Settings:
    APP_ENV = os.getenv("APP_ENV", "development")

    RAZORPAY_ENV = os.getenv("RAZORPAY_ENV", "test")
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./payment_truth.db")

    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")

    ML_ARTIFACTS_DIR = os.getenv("ML_ARTIFACTS_DIR", "ml/artifacts")

    @property
    def razorpay_configured(self) -> bool:
        return bool(self.RAZORPAY_KEY_ID and self.RAZORPAY_KEY_SECRET)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.RAZORPAY_WEBHOOK_SECRET)


settings = Settings()
