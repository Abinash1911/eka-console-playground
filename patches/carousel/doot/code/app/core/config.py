import os
import json
import logging

from pydantic_settings import BaseSettings
from functools import lru_cache

# Support loading a JSON blob injected into an environment variable (common when
# Kubernetes mounts secrets as a single JSON string). The docker-compose / k8s
# manifest may set `scribesnap=${SECRETS}` so check for that and populate
# individual environment variables before Pydantic reads them.
def _load_json_secret_env():
    for env_name in ("scribesnap", "SCRIBESNAP", "SECRETS"):
        raw = os.environ.get(env_name)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            logging.getLogger(__name__).warning(
                "Environment variable %s present but not valid JSON", env_name
            )
            return
        for k, v in data.items():
            key = k.upper()
            # Do not overwrite any explicit environment variables already set
            if key not in os.environ or os.environ.get(key) == "":
                os.environ[key] = str(v)
        logging.getLogger(__name__).info("Loaded secret JSON from %s", env_name)
        return


# Load JSON secrets (if provided) as early as possible
_load_json_secret_env()

class Settings(BaseSettings):

    ENVIRONMENT: str = "development"
    APP_NAME: str = "scribe-snap"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    THINKING_ACK_ENABLED: bool = True
    # Show the doctor step of a doctor_card as a carousel with profile pictures (where the
    # provider can and every doctor has one) instead of a list.
    DOCTOR_CAROUSEL_ENABLED: bool = False

    # config for direct meta whatsapp message provider.
    WHATSAPP_API_URL: str = "https://graph.facebook.com/v18.0"
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""
    # Meta App Secret — used to validate X-Hub-Signature-256 on incoming Meta webhooks
    META_APP_SECRET: str = ""
    
    BACKEND_API_URL: str = ""
    BACKEND_API_TIMEOUT: int = 30


    # config for interakt whatsapp message provider.
    WHATSAPP_PROVIDER: str = "interakt"
    INTERAKT_API_KEY: str = ""
    INTERAKT_API_URL: str = "https://api.interakt.ai/v1"
    INTERAKT_PHONE_NUMBER_ID: str = ""
    INTERAKT_WABA_ID: str = ""
    INTERAKT_WEBHOOK_SECRET: str = ""

    # config for interakt tech-partner (ISV) provider.
    # Shared across all onboarded WABAs — sends go through Interakt's amped-express
    # (Meta-Graph-compatible) API with x-access-token=<ISV> and x-waba-id=<waba_id>.
    # Per-WABA waba_id / phone_number_id arrive dynamically from dev-console.
    INTERAKT_ISV_TOKEN: str = ""
    # v24.0 matches what dev-console's amped-express integration already uses; newer
    # interactive types (Flows nfm_reply, address_message, cta_url) need >= v18.
    INTERAKT_AMPED_URL: str = "https://amped-express.interakt.ai/api/v24.0"

    # Dynamic (DB-configured) webhook integrations are cached in Redis (shared across
    # pods) for this many seconds. After expiry the next webhook for that agent
    # re-fetches the integration config from dev-console — bounds staleness fleet-wide
    # when a provider/credentials change, without needing a pod restart.
    DYNAMIC_INTEGRATION_TTL_SECONDS: int = 300

    # Diagnostic: log every raw event Turn sends (subscription header + full JSON
    # body) before any routing. Off by default; set true only when you need to
    # inspect webhook shapes.
    TURN_LOG_RAW_EVENTS: bool = False

    # --- Turn.io journey integration ---
    # While a Turn journey owns a conversation we mute the LLM agent so the user
    # doesn't get double replies (journey + agent). Ownership is read per-inbound
    # from Turn's own fields (author.journey_uuid + chat.state) — no Redis flag or
    # TTL. See app/bridge/medassist/bridge.py and app/services/journey_state.py.
    JOURNEY_MUTE_ENABLED: bool = True
    # Comma-separated words/pill titles that start a journey. Used only to suppress
    # the agent's reply to the trigger (message #1) and to start pill-triggered
    # journeys via the API. MUST stay in sync with the triggers configured in Turn
    # (e.g. "menu,jooorney").
    JOURNEY_TRIGGER_WORDS: str = ""
    # trigger-word → journey-name map, for starting a journey PROGRAMMATICALLY when
    # the trigger arrives as an interactive reply (pill/quick-reply), which Turn's
    # native text triggers don't match. Format: comma-separated
    # "trigger_word:journey_name" pairs, trigger lowercased
    # (e.g. "test a journey:Test journey"). The journey NAME is resolved to a uuid
    # at runtime via GET /v1/stacks — no hardcoded uuids. A raw uuid value is still
    # accepted for backward compatibility. Empty = disabled.
    JOURNEY_START_MAP: str = ""
    # Accumulate the journey Q&A (journey questions + inbound answers) and inject it
    # into the LLM as context once the journey ends.
    JOURNEY_CONTEXT_INJECTION_ENABLED: bool = True
    # Lifetime of the accumulation buffer + pending context summary.
    JOURNEY_DATA_TTL_SECONDS: int = 3600
    # Log-only probe of Turn's Flow Results API at journey end, to evaluate whether
    # journeys expose structured answers. Does not affect behavior.
    JOURNEY_FLOW_RESULTS_PROBE: bool = True

    # Voice2Rx API Configuration
    VOICE2RX_API_URL: str = "https://api.eka.care/voice/v1"

    REDIS_URL: str = ""
    
    SESSION_EXPIRE_MINUTES: int = 30
    MAX_AUDIO_SIZE_MB: int = 16
    
    TEMP_AUDIO_DIR: str = "/tmp/scribe-snap_audio"
    # Public base URL where this app is reachable (used to serve generated PDFs)
    APP_BASE_URL: str = "https://ec68-125-17-125-117.ngrok-free.app"

    # Directory to store generated documents (PDFs)
    TEMP_DOC_DIR: str = "/tmp/scribe-snap_docs"

    # Voice2Rx Template IDs
    DICTATION_TEMPLATE_ID: str = ""
    CONSULTATION_TEMPLATE_ID: str = ""

    BACKEND_TOKEN: str = ""
    AUTH_API_URL: str = "http://localhost:80"
    BACKEND_API_URL: str = ""  # Primary backend API URL (ensure this is set)

    # AWS S3 Configuration (uses default credential chain: IAM role, env vars, ~/.aws/credentials)
    AWS_REGION: str = "ap-south-1"  # Default region for ekascribe
    S3_BUCKET: str = "m-prod-ekascribe-batch"
    S3_PRESIGNED_URL_EXPIRY: int = 3600  # 1 hour in seconds

    # Medassist API Configuration
    MEDASSIST_BASE_URL: str = ""
    # agent_id is passed per-request via the webhook URL ?agent_id= query param

    # Dev-console internal API — used to fetch dynamic integration configs at runtime
    DEV_CONSOLE_INTERNAL_URL: str = ""

    # Local/dev only: long-lived workspace Bearer sent to *.eka.care so a laptop
    # can reach prod's public hosts without the VPN. Never set in prod.
    LOCAL_BEARER_TOKEN: str = ""

    # Message audit log (DynamoDB); empty disables it.
    MESSAGE_AUDIT_TABLE: str = "scribesnap-message-audit"

    # Netcore (Pepipost) WhatsApp provider — global / fallback credentials
    NETCORE_BEARER_TOKEN: str = ""
    NETCORE_API_URL: str = "https://waapi.pepipost.com/api/v2"
    NETCORE_WEBHOOK_SECRET: str = ""

    class Config:
        # Read from environment variables only (for production with Kubernetes secrets)
        # For local development, you can use python-dotenv or export variables manually
        case_sensitive = True
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
