"""Connection lifecycle, bounded in-memory retrieval and local preparation artifacts."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import time
from email.utils import parseaddr

from precedent.connected.providers import ProviderError, Providers
from precedent.connected.store import Vault


class Service:
    def __init__(self, vault: Vault, providers: Providers):
        self.vault, self.providers = vault, providers
        self.cache: dict = {}
        self.lock = asyncio.Lock()

    def public_connections(self):
        result = []
        for provider in ("gmail", "slack"):
            grant = self.vault.get("connection:" + provider) or {}
            cfg = self.providers.config.get(provider, {})
            ready = all(cfg.get(k) for k in ("client_id", "client_secret", "redirect_uri"))
            result.append(
                {
                    k: v
                    for k, v in dict(
                        provider=provider,
                        configured=ready,
                        label=grant.get("label"),
                        status=grant.get("status", "Not connected"),
                        scopes=grant.get("scopes", []),
                        selection=grant.get("selection"),
                        error=grant.get("error"),
                    ).items()
                }
            )
        return result

    def begin(self, provider, session):
        if provider not in ("gmail", "slack"):
            raise ValueError("Unknown provider")
        cfg = self.providers.config[provider]
        if not all(cfg.get(k) for k in ("client_id", "client_secret", "redirect_uri")):
            raise ValueError(
                "The application OAuth client is not configured yet. Developer setup is "
                "required once."
            )
        if provider == "slack" and not cfg["redirect_uri"].startswith("https://"):
            raise ValueError("Slack requires an HTTPS callback address.")
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        self.vault.put(
            "oauth:" + state,
            dict(provider=provider, session=session, verifier=verifier, expires=time.time() + 600),
        )
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        return self.providers.authorization_url(provider, state, challenge)

    async def callback(self, provider, state, code, denied=False):
        pending = self.vault.consume("oauth:" + state)
        if not pending or pending["provider"] != provider:
            raise ValueError("Authorization expired or was already used. Start again.")
        if not self.vault.authenticated(pending["session"]):
            raise ValueError("The initiating owner session is no longer valid.")
        if denied or not code:
            raise ValueError("Authorization was cancelled. No new connection was saved.")
        grant = await self.providers.exchange(provider, code, pending["verifier"])
        old = self.vault.get("connection:" + provider)
        if old and old["account"] == grant["account"] and not grant["token"].get("refresh_token"):
            if old["token"].get("refresh_token"):
                grant["token"]["refresh_token"] = old["token"]["refresh_token"]
        if grant["token"].get("expires_in"):
            grant["token"]["expires_at"] = time.time() + grant["token"]["expires_in"]
        grant.update(provider=provider, status="Choose sources", generation=secrets.token_hex(16))
        self.vault.put("connection:" + provider, grant)
        self.cache.clear()

    async def grant(self, provider):
        grant = self.vault.get("connection:" + provider)
        if not grant or grant.get("status") == "Reconnect needed":
            raise ProviderError("Connect this provider before continuing.", True)
        token = grant["token"]
        if token.get("expires_at", float("inf")) < time.time() + 60:
            try:
                grant["token"] = await self.providers.refresh(provider, token)
                self.vault.put("connection:" + provider, grant)
            except ProviderError:
                grant.update(status="Reconnect needed", error="Sign in again to restore access.")
                self.vault.put("connection:" + provider, grant)
                raise
        return grant

    async def select(self, provider, ids, days):
        if days not in (1, 3, 7):
            raise ValueError("Choose a one, three or seven day window.")
        async with self.lock:
            grant = await self.grant(provider)
            choices = await self.providers.choices(provider, grant["token"]["access_token"])
            allowed = {r["id"] for r in choices}
            ids = list(dict.fromkeys(ids))
            if not ids or not set(ids) <= allowed or len(ids) > (1 if provider == "gmail" else 2):
                raise ValueError("Choose one Gmail label or up to two accessible Slack channels.")
            grant.update(
                selection={"ids": ids, "days": days},
                status="Ready",
                generation=secrets.token_hex(16),
                error=None,
            )
            self.vault.put("connection:" + provider, grant)
            self.cache.clear()

    async def fetch(self, provider, fresh=False):
        async with self.lock:
            grant = await self.grant(provider)
            if not grant.get("selection"):
                raise ProviderError("Choose sources before reading this connection.")
            cached = self.cache.get(provider)
            if (
                not fresh
                and cached
                and cached["generation"] == grant["generation"]
                and time.time() - cached["fetched_at"] < 120
            ):
                return cached
            generation = grant["generation"]
            try:
                result = await self.providers.fetch(provider, grant)
            except ProviderError as exc:
                self.cache.pop(provider, None)
                if exc.reconnect:
                    grant.update(
                        status="Reconnect needed", error=str(exc), generation=secrets.token_hex(16)
                    )
                    self.vault.put("connection:" + provider, grant)
                raise
            current = self.vault.get("connection:" + provider)
            if not current or current["generation"] != generation:
                raise ProviderError("Access changed during retrieval. Reload the workspace.")
            result["generation"] = generation
            self.cache[provider] = result
            return result

    async def sources(self, fresh=False):
        result = []
        for provider in ("gmail", "slack"):
            result.extend((await self.fetch(provider, fresh))["sources"])
        return result

    async def disconnect(self, provider):
        async with self.lock:
            grant = self.vault.get("connection:" + provider)
            self.vault.delete("connection:" + provider)
            self.cache.clear()
            self.forget()
            if grant:
                try:
                    await self.providers.revoke(provider, grant["token"])
                except (ProviderError, Exception):
                    return (
                        "Local access removed. Also remove Precedent in provider account settings."
                    )
        return "Disconnected. Local preparation artifacts removed."

    def forget(self):
        for item in self.vault.list("artifact:"):
            self.vault.delete("artifact:" + item["id"])
        self.cache.clear()

    def artifacts(self):
        identity = self.vault.identity()
        return [a for a in self.vault.list("artifact:") if a["workspace"] == identity]

    async def save(self, fields: dict, actor: str):
        identity = self.vault.identity()
        if fields.get("workspace") != identity:
            raise ValueError("Workspace access changed. Reopen the form.")
        sources = {s["id"]: s for s in await self.sources()}
        selected = [s.strip() for s in fields.get("sources", "").split(",") if s.strip()]
        if not selected or any(s not in sources for s in selected):
            raise ValueError("Cite current selected source IDs, separated by commas.")
        if {sources[s]["provider"] for s in selected} != {"gmail", "slack"}:
            raise ValueError("This preparation needs both email and Slack evidence.")
        origin = sources.get(fields.get("reply_to"))
        if not origin or origin["provider"] != "gmail" or origin["id"] not in selected:
            raise ValueError("Select the cited email to reply to.")
        recipient = parseaddr(origin["author"])[1]
        if (
            not recipient
            or "@" not in recipient
            or fields.get("recipient", "").casefold() != recipient.casefold()
        ):
            raise ValueError("Recipient must match the selected email sender.")
        for name in ("subject", "brief", "body", "topic"):
            if not fields.get(name, "").strip() or len(fields[name]) > 10000:
                raise ValueError(f"Enter a {name} of 1–10,000 characters.")
        business = identity + ":" + origin["thread"] + ":" + fields["topic"].strip().casefold()
        aid = hashlib.sha256(business.encode()).hexdigest()[:24]
        existing = self.vault.get("artifact:" + aid)
        revision = int(fields.get("revision", "0"))
        if existing and existing["revision"] != revision:
            raise ValueError(
                "A saved preparation already exists or was edited. Reopen it before changing."
            )
        artifact = {
            k: fields[k].strip() for k in ("recipient", "subject", "brief", "body", "topic")
        }
        artifact.update(
            id=aid,
            workspace=identity,
            reply_to=origin["id"],
            thread=origin["thread"],
            sources=[
                {k: sources[s][k] for k in ("id", "version", "provider", "account")}
                for s in selected
            ],
            revision=revision + 1,
            status="Local draft — not sent",
            updated=time.time(),
            expires=time.time() + 86400,
            actor=actor,
        )
        with self.vault.lock:
            current = self.vault.get("artifact:" + aid)
            if (current or {}).get("revision", 0) != revision or self.vault.identity() != identity:
                raise ValueError("The preparation or access changed. Reload before saving.")
            self.vault.put("artifact:" + aid, artifact, actor)
        return aid
