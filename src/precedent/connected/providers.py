"""Server-owned OAuth transport and bounded legacy provider reads.

GoogleService exposes the narrow native draft/reservation operations; workers never
receive this transport or an arbitrary authenticated URL proxy.
"""

from __future__ import annotations

import base64
import hashlib
import re
import time
from html.parser import HTMLParser
from urllib.parse import quote, urlencode

import httpx

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_SCOPES = {
    "openid",
    "email",
    GMAIL_SCOPE,
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events.owned",
}
SLACK_SCOPES = {"channels:read", "channels:history"}


class ProviderError(Exception):
    def __init__(self, message: str, reconnect: bool = False, status: int = 0):
        super().__init__(message)
        self.reconnect = reconnect
        self.status = status


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("p", "br", "div", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def body_text(payload: dict, limit: int = 20000) -> str:
    plain, html = [], []

    def visit(part):
        if part.get("filename") or part.get("body", {}).get("attachmentId"):
            return
        data = part.get("body", {}).get("data", "")
        if data and part.get("mimeType") in ("text/plain", "text/html"):
            try:
                decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                    "utf-8", errors="replace"
                )
            except ValueError:
                decoded = "[Unreadable message part]"
            (html if part.get("mimeType") == "text/html" else plain).append(decoded)
        for child in part.get("parts", []):
            visit(child)

    visit(payload)
    if plain:
        return "\n".join(plain)[:limit]
    parser = PlainHTML()
    parser.feed("\n".join(html))
    return "".join(parser.parts)[:limit]


def source(provider, account, message_id, thread, title, author, text, timestamp, url):
    ref = hashlib.sha256(f"{provider}:{account}:{message_id}".encode()).hexdigest()[:24]
    value = dict(
        id=ref,
        provider=provider,
        account=account,
        message_id=message_id,
        thread=thread,
        title=title,
        author=author,
        text=text,
        timestamp=timestamp,
        url=url,
        fetched_at=time.time(),
    )
    value["version"] = hashlib.sha256(
        f"{author}\n{timestamp}\n{title}\n{text}".encode()
    ).hexdigest()
    return value


class Providers:
    def __init__(self, config: dict, client: httpx.AsyncClient | None = None):
        self.config = config
        self.client = client or httpx.AsyncClient(timeout=20, follow_redirects=False)

    async def request(self, method, url, **kwargs):
        try:
            response = await self.client.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise ProviderError("Provider could not be reached. Try again shortly.") from None
        if response.status_code == 429:
            delay = response.headers.get("retry-after", "a short delay")
            raise ProviderError(
                f"Provider rate limit reached. Retry after {delay} seconds.", status=429
            )
        if response.status_code in (401, 403):
            raise ProviderError(
                "Access expired, was revoked, or lacks permission. Reconnect.",
                True,
                status=response.status_code,
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"Provider request failed ({response.status_code}).", status=response.status_code
            )
        data = response.json()
        if data.get("ok") is False:
            code = data.get("error", "unknown_error")
            safe = code if re.fullmatch(r"[a-z_]+", code) else "unknown_error"
            raise ProviderError(
                f"Slack returned {safe}.",
                safe in ("invalid_auth", "token_revoked", "token_expired", "missing_scope"),
            )
        return data

    def authorization_url(self, provider, state, challenge):
        cfg = self.config[provider]
        params = dict(client_id=cfg["client_id"], redirect_uri=cfg["redirect_uri"], state=state)
        if provider == "gmail":
            params.update(
                response_type="code",
                scope=cfg.get("scope", GMAIL_SCOPE + " openid email"),
                access_type="offline",
                include_granted_scopes="true",
                prompt="consent",
                code_challenge=challenge,
                code_challenge_method="S256",
            )
            return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
        params["user_scope"] = ",".join(sorted(SLACK_SCOPES))
        return "https://slack.com/oauth/v2/authorize?" + urlencode(params)

    async def exchange(self, provider, code, verifier):
        cfg = self.config[provider]
        data = dict(
            client_id=cfg["client_id"],
            client_secret=cfg["client_secret"],
            redirect_uri=cfg["redirect_uri"],
            code=code,
        )
        if provider == "gmail":
            data.update(grant_type="authorization_code", code_verifier=verifier)
            token = await self.request("POST", "https://oauth2.googleapis.com/token", data=data)
            scopes = set(token.get("scope", "").split())
            identity = await self.request(
                "GET",
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": "Bearer " + token["access_token"]},
            )
            if not identity.get("sub") or not identity.get("email_verified"):
                raise ProviderError("Google account identity could not be verified.")
            return dict(
                token=token,
                account=identity["sub"],
                email=identity["email"],
                label=identity["email"],
                scopes=sorted(scopes),
            )
        response = await self.request("POST", "https://slack.com/api/oauth.v2.access", data=data)
        token = response.get("authed_user", {})
        scopes = set(token.get("scope", "").split(","))
        if not SLACK_SCOPES <= scopes or not token.get("access_token"):
            raise ProviderError("Slack user channel read access was not granted.")
        profile = await self.slack(token["access_token"], "auth.test")
        if profile.get("user_id") != token.get("id"):
            raise ProviderError("Slack account identity did not match the grant.")
        return dict(
            token=token,
            account=profile["team_id"] + ":" + profile["user_id"],
            team=profile["team_id"],
            user=profile["user_id"],
            label=profile.get("team", "Slack") + " · " + profile.get("user", "Member"),
            scopes=sorted(scopes),
        )

    async def refresh(self, provider, token):
        if not token.get("refresh_token"):
            raise ProviderError("This grant needs a new sign-in.", True)
        cfg = self.config[provider]
        url = (
            "https://oauth2.googleapis.com/token"
            if provider == "gmail"
            else "https://slack.com/api/oauth.v2.access"
        )
        result = await self.request(
            "POST",
            url,
            data=dict(
                grant_type="refresh_token",
                refresh_token=token["refresh_token"],
                client_id=cfg["client_id"],
                client_secret=cfg["client_secret"],
            ),
        )
        return {**token, **result, "expires_at": time.time() + result.get("expires_in", 3600)}

    async def revoke(self, provider, token):
        if provider == "gmail":
            response = await self.client.post(
                "https://oauth2.googleapis.com/revoke", data={"token": token["access_token"]}
            )
            if response.status_code != 200:
                raise ProviderError("Local access removed; revoke the grant in Google settings.")
        else:
            await self.slack(token["access_token"], "auth.revoke")

    async def gmail(self, token, path, **params):
        return await self.request(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/" + path,
            headers={"Authorization": "Bearer " + token},
            params=params,
        )

    async def slack(self, token, method, **params):
        allowed = {
            "auth.test",
            "auth.revoke",
            "conversations.list",
            "conversations.history",
            "conversations.replies",
        }
        if method not in allowed:
            raise ProviderError("Slack operation is not permitted.")
        return await self.request(
            "GET",
            "https://slack.com/api/" + method,
            headers={"Authorization": "Bearer " + token},
            params=params,
        )

    async def choices(self, provider, token):
        if provider == "gmail":
            result = await self.gmail(token, "labels")
            return [{"id": r["id"], "name": r["name"]} for r in result.get("labels", [])]
        result = await self.slack(
            token, "conversations.list", types="public_channel", exclude_archived="true", limit=200
        )
        return [{"id": r["id"], "name": r["name"]} for r in result.get("channels", [])]

    async def fetch(self, provider, grant):
        token, selection = grant["token"]["access_token"], grant["selection"]
        rows, complete = [], True
        if provider == "gmail":
            result = await self.gmail(
                token,
                "messages",
                labelIds=selection["ids"][0],
                q=f"newer_than:{selection['days']}d",
                maxResults=30,
            )
            complete = not result.get("nextPageToken")
            for item in result.get("messages", []):
                msg = await self.gmail(
                    token, "messages/" + quote(item["id"], safe=""), format="full"
                )
                headers = {r["name"].lower(): r["value"] for r in msg["payload"].get("headers", [])}
                rows.append(
                    source(
                        provider,
                        grant["account"],
                        msg["id"],
                        msg["threadId"],
                        headers.get("subject", "No subject"),
                        headers.get("from", "Unknown sender"),
                        body_text(msg["payload"]),
                        headers.get("date", ""),
                        "https://mail.google.com/mail/u/?authuser="
                        + quote(grant.get("email", grant["account"]), safe="")
                        + "#all/"
                        + msg["threadId"],
                    )
                )
        else:
            for channel in selection["ids"]:
                result = await self.slack(
                    token,
                    "conversations.history",
                    channel=channel,
                    oldest=str(time.time() - selection["days"] * 86400),
                    limit=15,
                )
                complete &= not bool(
                    result.get("has_more") or result.get("response_metadata", {}).get("next_cursor")
                )
                messages = result.get("messages", [])
                for parent in list(messages):
                    if parent.get("reply_count"):
                        replies = await self.slack(
                            token,
                            "conversations.replies",
                            channel=channel,
                            ts=parent["ts"],
                            limit=15,
                        )
                        complete &= not bool(
                            replies.get("has_more")
                            or replies.get("response_metadata", {}).get("next_cursor")
                        )
                        messages.extend(
                            r for r in replies.get("messages", []) if r["ts"] != parent["ts"]
                        )
                for msg in messages:
                    rows.append(
                        source(
                            provider,
                            grant["account"],
                            channel + ":" + msg["ts"],
                            channel + ":" + msg.get("thread_ts", msg["ts"]),
                            channel,
                            msg.get("user", msg.get("bot_id", "Unknown author")),
                            msg.get("text", "")[:20000],
                            msg["ts"],
                            "https://app.slack.com/client/"
                            + grant["team"]
                            + "/"
                            + channel
                            + "/thread/"
                            + channel
                            + "-"
                            + msg.get("thread_ts", msg["ts"]),
                        )
                    )
        return {
            "sources": rows,
            "complete": complete,
            "fetched_at": time.time(),
            "note": "Selected recent window" if complete else "Partial: retrieval limit reached",
        }
