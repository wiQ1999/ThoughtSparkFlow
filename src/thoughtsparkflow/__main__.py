# Create venv: `python -m venv .venv`
# Activate script: `.\.venv\Scripts\Activate.ps1`. 
# Install or upgrade env: `python -m pip install -e .`
# Run with: `python -m thoughtsparkflow`

from __future__ import annotations

import logging

from thoughtsparkflow.application.use_cases.generate_drafts_process import GenerateDraftsProcess
from thoughtsparkflow.application.use_cases.post_featured_image_process import PostFeaturedImageInput, PostFeaturedImageProcess
from thoughtsparkflow.config.loader import load_config
from thoughtsparkflow.infrastructure.cms.wordpress_adapter import WordPressAdapter, WordPressAdapterConfig
from thoughtsparkflow.infrastructure.genai import OpenAIWebAPIConfig
from thoughtsparkflow.infrastructure.genai.image_adapter import OpenAIImageGenerator
from thoughtsparkflow.infrastructure.genai.text_adapter import OpenAITextGenerator


def main() -> int:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("thoughtsparkflow")
    log.info("Start.")

    cfg = load_config()

    wp_adapter = WordPressAdapter(
        WordPressAdapterConfig(
            base_url=str(cfg.env.wp_api_url),
            user=cfg.env.wp_user,
            password=cfg.env.wp_password,
        )
    )
    openai_cfg = OpenAIWebAPIConfig(api_key=cfg.env.openai_api_key)

    process = GenerateDraftsProcess(
        wp=wp_adapter,
        text=OpenAITextGenerator(openai_cfg),
        img=OpenAIImageGenerator(openai_cfg),
        log=log,
    )

    try:
        result = process.invoke(2)
    except Exception as exc:
        log.exception("Draft generation failed: %s", exc)
        return 2

    log.info("Result(%s)", result)
    log.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
