"""Hermes background model adapter; validators retain the existing result contract."""
from benka_integrations.models import (AgentRunError, AgentRunResult, run_agent_json,
                                       extract_json_payload, strip_markdown_fences)
