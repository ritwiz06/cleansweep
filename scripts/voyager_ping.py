"""List the models Voyager serves and send one short message to the configured model."""

from __future__ import annotations

import os

from openai import OpenAI

from cleansweep.core.config import load_config


def main() -> None:
    load_config()  # loads .env
    client = OpenAI(
        base_url=os.environ.get("VOYAGER_BASE_URL"), api_key=os.environ.get("VOYAGER_API_KEY")
    )
    print("models:")
    for model in client.models.list():
        print(" ", model.id)
    model = os.environ.get("VOYAGER_MODEL")
    if model:
        reply = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "Say hello in five words."}]
        )
        print(f"\n{model}: {reply.choices[0].message.content}")


if __name__ == "__main__":
    main()
