"""Optional, non-core integrations that aren't a transport adapter
(`eventloom.adapters.*`) and aren't needed by plain `import eventloom`.

Each subpackage here is opt-in and only imports its extra dependencies
lazily/on demand — importing `eventloom.contrib` itself has no side effects
and requires nothing beyond eventloom's own core dependencies. Install the
matching extra to pull in a subpackage's own dependencies, e.g.
`pip install eventloom[pydantic-v1]` for `eventloom.contrib.pydantic_v1`.
"""
