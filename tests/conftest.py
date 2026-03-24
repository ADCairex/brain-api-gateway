"""
Shared test fixtures for brain-api-gateway tests.

Sets up a deterministic test environment with a fixed SECRET_KEY so that
pydantic-settings can initialise without a real .env file.  This must happen
before any src module is imported, which is why the env-var is injected at
module import time (conftest.py is loaded by pytest before test modules).
"""

import os

# Inject a deterministic secret before any src module is imported.
# pydantic-settings reads SECRET_KEY when config.py is first imported, so this
# must be set here — not inside a fixture — to avoid an ImportError.
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-only"
