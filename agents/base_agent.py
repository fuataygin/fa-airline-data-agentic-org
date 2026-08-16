"""
agents/base_agent.py
---------------------
Shared plumbing for every agent in the FA Airline Data organisation,
built on Google's Gemini **Interactions API** (`client.interactions.create`)
— the API Google recommends for all new projects as of June 2026.

Each Agent is: a name, a personality/system prompt, an optional set of
tools it's allowed to call, and a `.run(task_prompt)` method that talks
to the Gemini API — including a full function-calling loop, so an agent
like the Researcher can call the live Google Sheet tool as many times as
it needs before producing its final written output.

Docs: https://ai.google.dev/gemini-api/docs/interactions-overview
      https://ai.google.dev/gemini-api/docs/function-calling
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from google import genai

from config import DEFAULT_MODEL


@dataclass
class AgentTurnLog:
    """A lightweight record of what an agent did, for the console + audit trail."""
    agent_name: str
    tool_calls: List[str] = field(default_factory=list)
    output_chars: int = 0


class Agent:
    def __init__(
        self,
        name: str,
        role_title: str,
        system_prompt: str,
        model: Optional[str] = None,
        tools: Optional[List[dict]] = None,
        tool_impl: Optional[Dict[str, Callable[..., str]]] = None,
        max_tool_turns: int = 6,
        max_tokens: int = 4096,
    ):
        self.name = name
        self.role_title = role_title
        self.system_prompt = system_prompt
        self.model = model or DEFAULT_MODEL
        self.tools = tools or []
        self.tool_impl = tool_impl or {}
        self.max_tool_turns = max_tool_turns
        self.max_tokens = max_tokens

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env, "
                "add your key (from https://aistudio.google.com/apikey), and "
                "make sure it's loaded (main.py does this for you via "
                "python-dotenv)."
            )
        self.client = genai.Client(api_key=api_key)
        self.last_log: Optional[AgentTurnLog] = None

    def _create(self, **kwargs):
        """Thin wrapper so every call consistently re-applies this agent's
        system_instruction, tools, and generation_config — the Interactions
        API treats these as interaction-scoped, not carried over by
        previous_interaction_id."""
        create_kwargs = dict(
            model=self.model,
            system_instruction=self.system_prompt,
            generation_config={"max_output_tokens": self.max_tokens},
        )
        if self.tools:
            create_kwargs["tools"] = self.tools
        create_kwargs.update(kwargs)
        return self.client.interactions.create(**create_kwargs)

    def run(self, task_prompt: str) -> str:
        """
        Sends `task_prompt` to this agent, resolving any function calls the
        model makes along the way, and returns the final text output.
        """
        log = AgentTurnLog(agent_name=self.name)

        interaction = self._create(input=task_prompt)

        turns = 0
        while True:
            fc_steps = [s for s in interaction.steps if s.type == "function_call"]

            if fc_steps and turns < self.max_tool_turns:
                result_inputs = []
                for step in fc_steps:
                    fn = self.tool_impl.get(step.name)
                    args = dict(step.arguments) if step.arguments else {}
                    log.tool_calls.append(f"{step.name}({args})")

                    if fn is None:
                        result_payload = {
                            "error": f"no local implementation registered for tool '{step.name}'"
                        }
                    else:
                        try:
                            result_payload = {"result": fn(**args)}
                        except Exception as exc:  # noqa: BLE001 - surface any tool error to the model
                            result_payload = {"error": f"tool '{step.name}' raised: {exc}"}

                    result_inputs.append(
                        {
                            "type": "function_result",
                            "name": step.name,
                            "call_id": step.id,
                            "result": result_payload,
                        }
                    )

                interaction = self._create(
                    previous_interaction_id=interaction.id,
                    input=result_inputs,
                )
                turns += 1
                continue

            final_text = (interaction.output_text or "").strip()
            log.output_chars = len(final_text)
            self.last_log = log
            return final_text
