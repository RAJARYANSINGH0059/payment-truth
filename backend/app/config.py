import os

# Resolves to <repo_root>/ml/artifacts regardless of the process's current
# working directory. Previously this defaulted to the bare relative string
# "ml/artifacts", which only resolved correctly if the process happened to
# be launched from the repo root — the README's own documented "Local
# development (without Docker)" instructions (`cd backend && uvicorn ...`)
# launch it from backend/ instead, silently missing the committed model
# and reporting ml_model: not_trained. Docker/Render were unaffected
# because Dockerfile already sets ML_ARTIFACTS_DIR as an absolute path.
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_DEFAULT_ML_ARTIFACTS_DIR = os.path.join(_REPO_ROOT, "ml", "artifacts")


class Settings:
    APP_ENV = os.getenv("APP_ENV", "development")

    RAZORPAY_ENV = os.getenv("RAZORPAY_ENV", "test")
    RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./payment_truth.db")

    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")

    ML_ARTIFACTS_DIR = os.getenv("ML_ARTIFACTS_DIR", _DEFAULT_ML_ARTIFACTS_DIR)

    @property
    def razorpay_configured(self) -> bool:
        return bool(self.RAZORPAY_KEY_ID and self.RAZORPAY_KEY_SECRET)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.RAZORPAY_WEBHOOK_SECRET)


settings = Settings()
