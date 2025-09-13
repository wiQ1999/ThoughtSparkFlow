# Run with: `python -m src`

from __future__ import annotations
from config.env_settings import EnvSettings

def main() -> int:
    print(f"TSF: Start.")

    env = EnvSettings()
    print("Environment variables loaded:")
    print(env.wp_api_url, env.wp_user, env.wp_password, env.openai_api_key)

    print(f"TSF: Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
