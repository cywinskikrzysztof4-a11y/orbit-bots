"""Rdzeń Agenta Orbit — niezależny od UI silnik agentowy z pętlą function-calling.
Używa darmowego endpointu Gemini zgodnego z formatem OpenAI:
https://generativelanguage.googleapis.com/v1beta/openai/
Model: gemini-3.5-flash-lite. Klucz wyłącznie z env LLM_API_KEY (nigdy w kodzie/logach).
MAX_TOOL_STEPS = 6. Zwraca odpowiedź + listę wykonanych kroków (narzędzie, argumenty, skrót wyniku).
"""
import os
import json
import logging
import requests
from typing import Callable, Any
from . import activity

logger = logging.getLogger("orbit.agent")

MAX_TOOL_STEPS = 6
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-3.5-flash-lite"

class Tool:
    """Definicja narzędzia zgodna ze schematem OpenAI Function Calling."""
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[..., Any],
        requires_confirmation: bool = False,
        summary_fn: Callable[[Any], str] | None = None
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.requires_confirmation = requires_confirmation
        self.summary_fn = summary_fn

    def to_openai_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }

    def summarize(self, result: Any) -> str:
        if self.summary_fn:
            try:
                return self.summary_fn(result)
            except Exception:
                pass
        if isinstance(result, dict):
            if "error" in result:
                return f"Błąd: {result['error']}"
            if "summary" in result:
                return str(result["summary"])
            if "message" in result:
                return str(result["message"])
            if len(result) == 1:
                k, v = next(iter(result.items()))
                return f"{k}: {v}"
        text = str(result)
        if len(text) > 160:
            return text[:157] + "..."
        return text

class AgentStep:
    def __init__(self, tool: str, arguments: dict, result_summary: str, result: Any = None):
        self.tool = tool
        self.arguments = arguments
        self.result_summary = result_summary
        self.result = result

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "result_summary": self.result_summary,
            "result": self.result
        }

class AgentResult:
    def __init__(
        self,
        answer: str,
        steps: list[dict | AgentStep],
        paused: bool = False,
        pause_reason: str = "",
        pending_action: dict | None = None,
        pending_2fa: dict | None = None
    ):
        self.answer = answer
        self.steps = [s.to_dict() if isinstance(s, AgentStep) else s for s in steps]
        self.paused = paused
        self.pause_reason = pause_reason
        self.pending_action = pending_action
        self.pending_2fa = pending_2fa

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "steps": self.steps,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "pending_action": self.pending_action,
            "pending_2fa": self.pending_2fa
        }

class Agent:
    """Agent autonomiczny z pętlą wywołań narzędzi (function-calling)."""
    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools: list[Tool] | None = None,
        model: str | None = None,
        base_url: str | None = None,
        max_steps: int = MAX_TOOL_STEPS
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tools: dict[str, Tool] = {t.name: t for t in (tools or [])}
        self.model = model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/") + "/"
        self.max_steps = max_steps

    def register_tool(self, tool: Tool):
        self.tools[tool.name] = tool

    def _get_api_key(self) -> str | None:
        # Zgodnie z wymaganiem: klucz TYLKO z env LLM_API_KEY (nigdy w kodzie/repo)
        return os.environ.get("LLM_API_KEY", "").strip() or None

    def run(self, prompt: str, history: list[dict] | None = None) -> AgentResult:
        """Główna pętla wykonawcza agenta: prompt + opcjonalna historia -> odpowiedź + kroki."""
        tid = activity.start_task(f"agent:{self.name}")
        try:
            return self._run_loop(prompt, history)
        finally:
            activity.finish_task(tid)

    def _run_loop(self, prompt: str, history: list[dict] | None = None) -> AgentResult:
        api_key = self._get_api_key()
        if not api_key:
            return AgentResult(
                answer="Brak skonfigurowanego klucza LLM_API_KEY w zmiennych środowiskowych. "
                       "Ustaw zmienną LLM_API_KEY (darmowy klucz Gemini z aistudio.google.com), aby uruchomić rozumowanie agenta.",
                steps=[]
            )

        messages = [{"role": "system", "content": self.system_prompt}]
        if history:
            for h in history:
                if h.get("role") in ("user", "assistant"):
                    messages.append({"role": h["role"], "content": h.get("content", "")})
        messages.append({"role": "user", "content": prompt})

        tools_schema = [t.to_openai_tool() for t in self.tools.values()] if self.tools else None
        steps: list[dict] = []
        step_count = 0

        while step_count < self.max_steps:
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.2
            }
            if tools_schema:
                payload["tools"] = tools_schema
                payload["tool_choice"] = "auto"

            try:
                # Wywołanie endpointu OpenAI chat completions
                endpoint = self.base_url + "chat/completions"
                resp = requests.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json=payload,
                    timeout=60
                )
                if resp.status_code != 200:
                    err_msg = resp.text[:200]
                    return AgentResult(
                        answer=f"Błąd wywołania modelu Gemini API ({resp.status_code}): {err_msg}",
                        steps=steps
                    )
                data = resp.json()
            except Exception as e:
                return AgentResult(
                    answer=f"Błąd komunikacji z modelem LLM: {str(e)}",
                    steps=steps
                )

            choices = data.get("choices", [])
            if not choices:
                return AgentResult(answer="Model nie zwrócił odpowiedzi.", steps=steps)

            choice = choices[0]
            msg = choice.get("message", {})
            tool_calls = msg.get("tool_calls")

            # Jeśli brak wywołań narzędzi lub odpowiedź tekstowa końcowa
            if not tool_calls:
                answer_text = msg.get("content") or ""
                return AgentResult(answer=answer_text, steps=steps)

            # Dołącz odpowiedź asystenta z tool_calls do historii
            messages.append(msg)

            # Obsługa każdego wywołania narzędzia
            for tc in tool_calls:
                step_count += 1
                call_id = tc.get("id", f"call_{step_count}")
                fn = tc.get("function", {})
                tool_name = fn.get("name")
                args_str = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
                except Exception:
                    args = {}

                tool_obj = self.tools.get(tool_name)
                if not tool_obj:
                    res_val = {"error": f"Narzędzie '{tool_name}' nie jest zarejestrowane."}
                    summary = f"Błąd: nieznane narzędzie {tool_name}"
                elif tool_obj.requires_confirmation:
                    # Akcja wymagająca zatwierdzenia (zakupy, wysyłanie, publikacja)
                    from core import accounts
                    act = accounts.request_action_approval(
                        agent_id=self.name,
                        action_type=tool_name,
                        description=f"Wywołanie '{tool_name}' z argumentami: {json.dumps(args, ensure_ascii=False)}",
                        payload=args
                    )
                    summary = f"Wstrzymano: wymagane zatwierdzenie w UI (ID akcji: {act['id']})"
                    res_val = {"status": "pending_approval", "action_id": act["id"], "message": summary}
                    steps.append({
                        "tool": tool_name,
                        "arguments": args,
                        "result_summary": summary,
                        "result": res_val
                    })
                    return AgentResult(
                        answer=f"Operacja '{tool_name}' wymaga potwierdzenia użytkownika. Dodano zadanie do kolejki zatwierdzeń (ID: {act['id']}). Sprawdź zakładkę Konta w panelu.",
                        steps=steps,
                        paused=True,
                        pause_reason="pending_approval",
                        pending_action=act
                    )
                else:
                    try:
                        res_val = tool_obj.handler(**args)
                        # Sprawdź czy narzędzie zwróciło stan żądania 2FA
                        if isinstance(res_val, dict) and res_val.get("status") == "needs_2fa":
                            prompt_2fa = res_val.get("prompt", "Podaj kod uwierzytelniający 2FA")
                            summary = f"Pauza: oczekiwanie na kod 2FA ({prompt_2fa})"
                            steps.append({
                                "tool": tool_name,
                                "arguments": args,
                                "result_summary": summary,
                                "result": res_val
                            })
                            return AgentResult(
                                answer=f"Agent wstrzymał działanie: wymagany kod 2FA. {prompt_2fa}",
                                steps=steps,
                                paused=True,
                                pause_reason="needs_2fa",
                                pending_2fa=res_val
                            )
                        summary = tool_obj.summarize(res_val)
                    except Exception as err:
                        res_val = {"error": str(err)}
                        summary = f"Błąd wykonania: {str(err)}"

                steps.append({
                    "tool": tool_name,
                    "arguments": args,
                    "result_summary": summary,
                    "result": res_val
                })

                content_str = json.dumps(res_val, ensure_ascii=False) if not isinstance(res_val, str) else res_val
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": content_str
                })

                if step_count >= self.max_steps:
                    break

        # Po osiągnięciu limitu 6 kroków poproś o podsumowanie końcowe
        messages.append({
            "role": "user",
            "content": "Osiągnięto limit kroków narzędzi. Na podstawie dotychczasowych danych podsumuj krótko odpowiedź."
        })
        try:
            resp = requests.post(
                self.base_url + "chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={"model": self.model, "messages": messages, "temperature": 0.2},
                timeout=30
            )
            if resp.status_code == 200:
                final_text = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                return AgentResult(answer=final_text or "Osiągnięto limit kroków narzędzi.", steps=steps)
        except Exception:
            pass

        return AgentResult(answer="Osiągnięto limit 6 kroków wykonania narzędzi.", steps=steps)
