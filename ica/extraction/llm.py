"""Couche LLM indépendante du fournisseur.

``LLMClient`` est un Protocol à une seule méthode : n'importe quelle API (Gemini, Anthropic,
endpoint compatible OpenAI, modèle local) s'intègre en ~30 lignes. Le fournisseur est choisi par
configuration (``LLM_PROVIDER``), jamais dans le code métier.

``call_validated`` impose la discipline : la réponse doit être un JSON conforme au modèle Pydantic ;
sinon l'erreur de validation est renvoyée au modèle (2 réparations max) puis l'appel échoue
proprement. Aucun JSON invalide n'atteint le reste du système.
"""
from __future__ import annotations

import base64
import http.client
import json
import logging
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional, Protocol, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLMFatalError(LLMError):
    """Refus qui se reproduira à chaque appel (clé refusée, modèle inaccessible, crédits ou quota du jour
    épuisés) : il faut arrêter l'analyse tout de suite au lieu de la poursuivre partie par partie."""


_FATAL_HINTS = {
    401: "clé API refusée par le fournisseur : vérifiez LLM_API_KEY / GEMINI_API_KEY dans .env",
    403: "accès refusé : votre clé n'a pas le droit d'utiliser ce modèle, ou elle est invalide. Vérifiez la clé et le nom du modèle dans .env",
    402: "crédits du fournisseur épuisés : rechargez le compte ou changez de fournisseur",
    404: "modèle ou adresse introuvable : vérifiez le nom du modèle (LLM_MODEL / LLM_VISION_MODEL) et LLM_BASE_URL",
}


class LLMClient(Protocol):
    def generate(self, *, system: str, user: str, images: Optional[list[bytes]] = None) -> str:
        """Retourne le texte brut de la réponse (attendu : un objet JSON)."""
        ...


# --------------------------------------------------------------------------- HTTP helper


def _is_daily_quota(body: str) -> bool:
    b = body.lower().replace(" ", "")
    return "perday" in b or "requestsperday" in b or ("quota" in b and "day" in b and "limitexceeded" in b)


# Activité des appels à l'IA : journal du serveur + ligne « en direct » de la tâche affichée à l'utilisateur.
log = logging.getLogger("ica.llm")
_local = threading.local()
MAX_TIMEOUT_RETRIES = 2  # pas de réponse du tout : 2 nouvelles tentatives au plus, pour signaler vite un service muet


DEFAULT_TIMEOUT = 180
SLEEP_SLACK = 120  # une étape qui dure 2 min de plus que prévu : l'ordinateur s'est mis en veille


class LLMInterrupted(LLMError):
    """L'ordinateur s'est mis en veille (ou a été suspendu) pendant l'appel : inutile de poursuivre l'analyse."""


def _env_timeout() -> int:
    try:
        return max(30, int(os.environ.get("LLM_TIMEOUT", DEFAULT_TIMEOUT)))
    except ValueError:
        return DEFAULT_TIMEOUT


def _check_awake(t_wall: float, expected: float) -> None:
    """Une attente de quelques secondes qui a duré des heures signifie une mise en veille : on arrête proprement."""
    elapsed = time.time() - t_wall
    if elapsed > expected + SLEEP_SLACK:
        raise LLMInterrupted(f"analyse interrompue : une étape prévue pour {expected:.0f} s a duré {elapsed / 60:.0f} min "
                             "(l'ordinateur s'est probablement mis en veille). Relancez l'analyse en gardant l'ordinateur allumé.")


def set_activity_reporter(fn: Optional[Callable[[str], None]]) -> None:
    """Rattache au fil d'exécution courant une fonction qui reçoit chaque étape des appels (tâche de fond)."""
    _local.report = fn


def _report(msg: str) -> None:
    log.info(msg)
    fn = getattr(_local, "report", None)
    if fn:
        fn(msg)


def _post_json(url: str, headers: dict[str, str], payload: dict, timeout: int, max_retries: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    model = payload.get("model") or url.rsplit("/models/", 1)[-1].split(":")[0]
    delay = 2.0
    last: Optional[Exception] = None
    timeouts = 0
    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method="POST")
        t0, t_wall = time.monotonic(), time.time()
        _report(f"Appel à l'IA ({model}){f', tentative {attempt + 1}' if attempt else ''}…")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            _report(f"Réponse de l'IA reçue en {time.monotonic() - t0:.0f} s")
            return out
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            if e.code in _FATAL_HINTS:
                _report(f"Refus du fournisseur (HTTP {e.code})")
                raise LLMFatalError(f"HTTP {e.code} — {_FATAL_HINTS[e.code]}. Détail : {body[:200]}")
            if e.code == 429 and _is_daily_quota(body):  # attendre ne sert à rien : quota du jour épuisé
                raise LLMFatalError(
                    "Quota quotidien du fournisseur d'IA épuisé (offre gratuite). Réessayez demain, ou activez la "
                    "facturation sur votre compte (Google AI Studio / OpenRouter). Détail : " + body[:200]
                )
            last = LLMError(f"HTTP {e.code}: {body}")
            if e.code not in (408, 429, 500, 502, 503, 504) or attempt == max_retries:
                raise last
            why = "trop de demandes (limite par minute du fournisseur)" if e.code == 429 else f"service indisponible (HTTP {e.code})"
        except (TimeoutError, socket.timeout) as e:
            timeouts += 1
            last = LLMError(f"pas de réponse de l'IA après {timeout} s ({model})")
            if timeouts > MAX_TIMEOUT_RETRIES or attempt == max_retries:
                raise LLMError(f"le service d'IA ne répond pas ({timeouts} essais de {timeout} s, modèle {model}) : "
                               "réessayez plus tard ou choisissez un modèle plus rapide") from e
            why = f"pas de réponse après {timeout} s"
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, OSError, ValueError) as e:
            # Connexion coupée en cours de réponse (IncompleteRead), réinitialisée, ou JSON tronqué :
            # erreur transitoire, retentée ; ne doit jamais interrompre une analyse longue.
            if isinstance(getattr(e, "reason", None), (TimeoutError, socket.timeout)):
                timeouts += 1
            last = LLMError(f"réseau : {type(e).__name__}: {e}")
            if attempt == max_retries or timeouts > MAX_TIMEOUT_RETRIES:
                raise last
            why = f"erreur réseau ({type(e).__name__})"
        _check_awake(t_wall, timeout)
        _report(f"{why} — nouvelle tentative dans {delay:.0f} s")
        t_wall = time.time()
        time.sleep(delay)
        _check_awake(t_wall, delay)
        delay = min(delay * 2, 30.0)
    raise last or LLMError("échec inconnu")


# --------------------------------------------------------------------------- fournisseurs


class GeminiClient:
    """API REST Google AI Studio (offre gratuite incluse). Variables : GEMINI_API_KEY, GEMINI_MODEL."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, timeout: Optional[int] = None, max_retries: int = 5):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self.timeout, self.max_retries = timeout or _env_timeout(), max_retries
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY manquante (fichier .env ou variable d'environnement)")

    def generate(self, *, system: str, user: str, images: Optional[list[bytes]] = None) -> str:
        parts: list[dict] = [{"text": user}]
        for img in images or []:
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(img).decode()}})
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        out = _post_json(url, {"x-goog-api-key": self.api_key}, payload, self.timeout, self.max_retries)
        try:
            return "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError) as e:
            raise LLMError(f"réponse Gemini inattendue : {str(out)[:300]}") from e


class AnthropicClient:
    """API Messages d'Anthropic. Variables : ANTHROPIC_API_KEY, ANTHROPIC_MODEL (obligatoire, aucun défaut codé en dur)."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, timeout: Optional[int] = None, max_retries: int = 5, max_tokens: int = 4096):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "")
        self.timeout, self.max_retries, self.max_tokens = timeout or _env_timeout(), max_retries, max_tokens
        if not self.api_key or not self.model:
            raise LLMError("ANTHROPIC_API_KEY et ANTHROPIC_MODEL sont requis")

    def generate(self, *, system: str, user: str, images: Optional[list[bytes]] = None) -> str:
        content: list[dict] = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(i).decode()}}
            for i in images or []
        ]
        content.append({"type": "text", "text": user})
        payload = {"model": self.model, "max_tokens": self.max_tokens, "system": system, "messages": [{"role": "user", "content": content}]}
        out = _post_json(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, payload, self.timeout, self.max_retries,
        )
        try:
            return "".join(b.get("text", "") for b in out["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise LLMError(f"réponse Anthropic inattendue : {str(out)[:300]}") from e


class OpenAICompatibleClient:
    """Chat Completions API. Variables : LLM_API_KEY, LLM_MODEL, LLM_VISION_MODEL, LLM_MAX_TOKENS, LLM_BASE_URL."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        vision_model: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[int] = None,
        max_retries: int = 5,
    ):
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL", "")
        self.vision_model = vision_model or os.environ.get("LLM_VISION_MODEL") or self.model
        # Modèles de secours (OpenRouter) : si le premier est saturé ou indisponible, la même requête part
        # vers le suivant, dans le même appel. Listes séparées par des virgules.
        split = lambda v: [m.strip() for m in (v or "").split(",") if m.strip()]
        self.fallbacks = split(os.environ.get("LLM_FALLBACK_MODELS"))
        self.vision_fallbacks = split(os.environ.get("LLM_VISION_FALLBACK_MODELS")) or self.fallbacks
        self.last_model: Optional[str] = None  # modèle qui a réellement répondu
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
        try:
            self.max_tokens = max_tokens if max_tokens is not None else int(os.environ.get("LLM_MAX_TOKENS", "4096"))
        except ValueError as e:
            raise LLMError("LLM_MAX_TOKENS doit être un entier positif") from e
        self.timeout, self.max_retries = timeout or _env_timeout(), max_retries
        # Paramètres propres au fournisseur, en JSON (ex. désactiver le raisonnement d'un modèle).
        try:
            self.extra_body = json.loads(os.environ.get("LLM_EXTRA_BODY") or "{}")
        except ValueError as e:
            raise LLMError("LLM_EXTRA_BODY doit être un objet JSON valide") from e
        if not self.api_key or not self.model:
            raise LLMError("LLM_API_KEY et LLM_MODEL sont requis pour openai_compatible")
        if self.max_tokens < 1:
            raise LLMError("LLM_MAX_TOKENS doit être un entier positif")

    def generate(self, *, system: str, user: str, images: Optional[list[bytes]] = None) -> str:
        content: str | list[dict] = user
        if images:
            content = [{"type": "text", "text": user}]
            content.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(image).decode()}"},
                }
                for image in images
            )
        payload = {
            "model": self.vision_model if images else self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        backups = self.vision_fallbacks if images else self.fallbacks
        if backups:
            payload["models"] = [payload["model"], *[m for m in backups if m != payload["model"]]]
        payload.update(self.extra_body)
        endpoint = self.base_url if self.base_url.endswith("/chat/completions") else f"{self.base_url}/chat/completions"
        # Une réponse coupée (finish_reason = length) n'est jamais un JSON valide : la « réparer » ne sert à rien.
        # On relance une fois avec un budget doublé, puis on échoue avec une explication.
        for attempt in range(2):
            out = _post_json(endpoint, {"Authorization": f"Bearer {self.api_key}"}, payload, self.timeout, self.max_retries)
            try:
                self.last_model = out.get("model") or payload["model"]
                choice = out["choices"][0]
                message = choice["message"]
            except (KeyError, IndexError, TypeError) as e:
                raise LLMError(f"réponse OpenAI-compatible inattendue : {str(out)[:300]}") from e
            if choice.get("finish_reason") != "length":
                break
            if attempt == 0:
                payload["max_tokens"] = payload["max_tokens"] * 2
                continue
            raise LLMError(
                f"Réponse du modèle coupée : limite de {payload['max_tokens']} tokens atteinte. Augmentez LLM_MAX_TOKENS, "
                "ou choisissez un modèle sans raisonnement (ex. google/gemma-4-31b-it) pour LLM_VISION_MODEL."
            )
        response = message.get("content")
        if isinstance(response, list):
            response = "".join(part.get("text", "") for part in response if part.get("type") == "text")
        if isinstance(response, str) and response.strip():
            return response
        # Modèles « à raisonnement » : la réponse peut se trouver dans un champ séparé.
        for key in ("reasoning_content", "reasoning"):
            alt = message.get(key)
            if isinstance(alt, str) and "{" in alt:
                return alt
        reason = choice.get("finish_reason")
        hint = (" Le modèle a épuisé LLM_MAX_TOKENS en réfléchissant : augmentez-le, ou désactivez le raisonnement "
                "via LLM_EXTRA_BODY." if reason == "length" else "")
        raise LLMError(f"réponse OpenAI-compatible sans contenu texte (finish_reason={reason}).{hint}")


class PerplexityAgentClient:
    """API « Agent » de Perplexity (POST /v1/agent), qui remplace depuis le 27/09/2026 son ancienne API compatible OpenAI.

    Variables : PERPLEXITY_API_KEY, PERPLEXITY_MODEL (CG, texte), PERPLEXITY_VISION_MODEL (photos de CP),
    LLM_MAX_TOKENS, LLM_TIMEOUT. Les modèles s'écrivent « fournisseur/modèle » (ex. openai/gpt-5.6-luna).

    Recherche web : jamais activée. On nomme un modèle sans « effort » ni outil : d'après la documentation de Perplexity,
    la réponse vient alors uniquement du modèle et des documents fournis, sans résultat web mêlé au contrat.
    """

    URL = "https://api.perplexity.ai/v1/agent"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, vision_model: Optional[str] = None,
                 max_tokens: Optional[int] = None, timeout: Optional[int] = None, max_retries: int = 5):
        self.api_key = api_key or os.environ.get("PERPLEXITY_API_KEY", "")
        self.model = model or os.environ.get("PERPLEXITY_MODEL", "openai/gpt-5.6-luna")
        self.vision_model = vision_model or os.environ.get("PERPLEXITY_VISION_MODEL") or self.model
        try:
            self.max_tokens = max_tokens if max_tokens is not None else int(os.environ.get("LLM_MAX_TOKENS", "8192"))
        except ValueError as e:
            raise LLMError("LLM_MAX_TOKENS doit être un entier positif") from e
        self.timeout, self.max_retries = timeout or _env_timeout(), max_retries
        if not self.api_key:
            raise LLMError("PERPLEXITY_API_KEY manquante (fichier .env)")

    def generate(self, *, system: str, user: str, images: Optional[list[bytes]] = None) -> str:
        content: list[dict] = [{"type": "input_text", "text": user}]
        content += [{"type": "input_image", "image_url": f"data:image/jpeg;base64,{base64.b64encode(i).decode()}"} for i in images or []]
        payload = {
            "model": self.vision_model if images else self.model,
            "instructions": system,
            "input": [{"type": "message", "role": "user", "content": content}],
            "max_output_tokens": self.max_tokens,
            "max_steps": 1,          # une seule étape : pas d'outil, pas de recherche
            "temperature": 0,
        }
        for attempt in range(2):  # réponse coupée faute de budget : une relance avec budget doublé
            out = _post_json(self.URL, {"Authorization": f"Bearer {self.api_key}"}, payload, self.timeout, self.max_retries)
            text = self._text(out)
            status = out.get("status")
            if status == "incomplete":
                if attempt == 0:
                    payload["max_output_tokens"] *= 2
                    continue
                break  # toujours coupée : un JSON partiel n'est jamais renvoyé
            if text.strip():
                return text
            err = (out.get("error") or {}).get("message") if isinstance(out.get("error"), dict) else out.get("error")
            raise LLMError(f"réponse Perplexity sans texte (statut {status}{f' : {err}' if err else ''})")
        raise LLMError(f"réponse Perplexity coupée : limite de {payload['max_output_tokens']} tokens atteinte (augmentez LLM_MAX_TOKENS)")

    @staticmethod
    def _text(out: dict) -> str:
        """Texte final : éléments « message » de output[], puis leurs contenus « output_text »."""
        parts: list[str] = []
        for item in out.get("output") or []:
            if item.get("type") != "message":
                continue
            for c in item.get("content") or []:
                if c.get("type") == "output_text" and isinstance(c.get("text"), str):
                    parts.append(c["text"])
        return "".join(parts)


class MockLLM:
    """Client de test : renvoie des réponses préparées, dans l'ordre. Enregistre les appels."""

    def __init__(self, responses: list[str | dict]):
        self._responses = [r if isinstance(r, str) else json.dumps(r) for r in responses]
        self.calls: list[dict] = []

    def generate(self, *, system: str, user: str, images: Optional[list[bytes]] = None) -> str:
        self.calls.append({"system": system, "user": user, "n_images": len(images or [])})
        if not self._responses:
            raise LLMError("MockLLM : plus de réponse préparée")
        return self._responses.pop(0)


def make_llm_from_env() -> LLMClient:
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if provider == "gemini":
        return GeminiClient()
    if provider == "anthropic":
        return AnthropicClient()
    if provider == "openai_compatible":
        return OpenAICompatibleClient()
    if provider == "perplexity":
        return PerplexityAgentClient()
    raise LLMError(f"LLM_PROVIDER inconnu : {provider}")


# --------------------------------------------------------------------------- appel validé


def _extract_json(text: str) -> str:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def call_validated(
    llm: LLMClient, model_cls: Type[T], *, system: str, user: str,
    images: Optional[list[bytes]] = None, max_repairs: int = 2,
) -> T:
    prompt = user
    last_error = ""
    for attempt in range(max_repairs + 1):
        raw = llm.generate(system=system, user=prompt, images=images)
        try:
            return model_cls.model_validate_json(_extract_json(raw))
        except (ValidationError, ValueError) as e:
            last_error = str(e)[:1500]
            prompt = (
                f"{user}\n\nTa réponse précédente n'est pas valide ({last_error}).\n"
                "Corrige-la et renvoie UNIQUEMENT l'objet JSON conforme au schéma demandé."
            )
    raise LLMError(f"Réponse non conforme après {max_repairs + 1} tentatives : {last_error}")
