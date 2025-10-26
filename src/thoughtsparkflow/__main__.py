# Activate script: `.\.venv\Scripts\Activate.ps1`. 
# Run with: `python -m thoughtsparkflow`

from __future__ import annotations

import logging

from thoughtsparkflow.application.use_cases.generate_drafts_process import GenerateDraftsProcess
from thoughtsparkflow.config.loader import load_config
from thoughtsparkflow.infrastructure.cms.wordpress_adapter import WordPressAdapter, WordPressAdapterConfig


def main() -> int:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("thoughtsparkflow")
    log.info("Start.")

    cfg = load_config()

    process = GenerateDraftsProcess(
        wp=WordPressAdapter(
            WordPressAdapterConfig(
                base_url=str(cfg.env.wp_api_url),
                user=cfg.env.wp_user,
                password=cfg.env.wp_password,
            )
        ),
        text=None,
        img=None,
        log=log,
    )

    try:
        result = process.invoke()
    except Exception as exc:
        log.exception("Draft generation failed: %s", exc)
        return 2

    log.info("Result(%s)", result)
    log.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
