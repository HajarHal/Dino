"""Comptes : inscription, connexion, déconnexion (« Quitter »).

- Mot de passe : jamais stocké ; empreinte scrypt salée (``hash_password`` / ``check_password``).
- Session : jeton aléatoire dans un cookie httpOnly (SameSite=Lax) ; la base ne garde que son empreinte SHA-256.
  Durée : 30 jours. « Quitter » supprime la session : les contrats restent, il faut se reconnecter.
- Essais : après 5 échecs pour un e-mail, nouvelle tentative possible après 60 secondes.
- Utilisateur courant : ``CURRENT_USER`` (contextvar), rempli par le garde de l'API pour chaque requête.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .db import Account, AuthSession, Document

COOKIE = "dino_session"
SESSION_DAYS = 30
MIN_PASSWORD = 8
MAX_FAILS, LOCK_SECONDS = 5, 60
LEGACY_USER = "local"  # données créées avant les comptes : reprises par le premier compte créé

CURRENT_USER: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("current_user", default=None)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_fails: dict[str, tuple[int, float]] = {}
_fails_lock = threading.Lock()


class AuthError(ValueError):
    pass


# --------------------------------------------------------------------------------------------- mots de passe


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        algo, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
    return hmac.compare_digest(got.hex(), digest)


def clean_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL.match(e) or len(e) > 254:
        raise AuthError("Adresse e-mail invalide.")
    return e


# --------------------------------------------------------------------------------------------- comptes


def signup(s: Session, email: str, password: str) -> Account:
    e = clean_email(email)
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Le mot de passe doit contenir au moins {MIN_PASSWORD} caractères.")
    if s.scalar(select(Account).where(Account.email == e)):
        raise AuthError("Un compte existe déjà avec cette adresse e-mail.")
    # Premier compte : il reprend les contrats déjà enregistrés sur ce poste (avant l'arrivée des comptes).
    first = s.scalar(select(func.count()).select_from(Account)) == 0
    legacy = first and s.scalar(select(func.count()).select_from(Document).where(Document.user_id == LEGACY_USER)) > 0
    acc = Account(email=e, password_hash=hash_password(password), **({"id": LEGACY_USER} if legacy else {}))
    s.add(acc)
    s.commit()
    return acc


def login(s: Session, email: str, password: str) -> Account:
    e = (email or "").strip().lower()
    with _fails_lock:
        n, until = _fails.get(e, (0, 0.0))
        if until > time.time():
            raise AuthError(f"Trop d'essais. Réessayez dans {int(until - time.time()) + 1} secondes.")
    acc = s.scalar(select(Account).where(Account.email == e))
    if acc is None or not check_password(password or "", acc.password_hash):
        with _fails_lock:
            n = _fails.get(e, (0, 0.0))[0] + 1
            _fails[e] = (0, time.time() + LOCK_SECONDS) if n >= MAX_FAILS else (n, 0.0)
        raise AuthError("E-mail ou mot de passe incorrect.")
    with _fails_lock:
        _fails.pop(e, None)
    return acc


# --------------------------------------------------------------------------------------------- sessions


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def open_session(s: Session, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    s.add(AuthSession(token_hash=_digest(token), user_id=user_id,
                      expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)))
    s.commit()
    return token


def user_for(s: Session, token: Optional[str]) -> Optional[Account]:
    if not token:
        return None
    sess = s.get(AuthSession, _digest(token))
    if sess is None:
        return None
    exp = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        s.delete(sess)
        s.commit()
        return None
    return s.get(Account, sess.user_id)


def close_session(s: Session, token: Optional[str]) -> None:
    if token:
        s.execute(delete(AuthSession).where(AuthSession.token_hash == _digest(token)))
        s.commit()
