"""Framework adapters. Each subpackage (`fastapi`, and later `flask`,
`websocket`, ...) is optional and only imports its target framework lazily —
`eventloom.adapters` itself has no side effects and no framework imports, so
`import eventloom` never requires FastAPI (or any other framework) to be
installed. Install the matching extra to pull in a framework's adapter
dependencies, e.g. `pip install eventloom[fastapi]`.
"""
