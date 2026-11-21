"""Dashboard workspace integration status and configuration metadata."""

import os

from pymongo.errors import PyMongoError

from .. import accounts, gmail, paths, tracker

def workspace_payload(account):
    from .. import llm

    try:
        connected = account.get_json("gmail") is not None if account else gmail.is_connected()
    except (PyMongoError, accounts.AccountError, ValueError):
        connected = None
    return {
        "gmail": connected,
        "account": account is not None,
        "employer_password_configured": bool(os.getenv("JOBBOT_EMPLOYER_PASSWORD")),
        "llm_provider": llm.DEFAULT_PROVIDER,
        "llm_model": llm.OPENAI_MODEL if llm.DEFAULT_PROVIDER == "openai" else llm.DEFAULT_MODEL,
        "llm_available": llm.LLM.available(),
        "profile": str(paths.PROFILE),
        "statuses": list(tracker.STATUSES),
    }

