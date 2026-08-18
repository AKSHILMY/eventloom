# providers sub-package — each module (openai, anthropic) imports its own
# SDK lazily, only when explicitly imported (e.g. `from
# eventloom.contrib.pydantic_v1.providers.openai import OpenAIStreamClient`).
# Importing `eventloom.contrib.pydantic_v1.providers` itself pulls in neither.
