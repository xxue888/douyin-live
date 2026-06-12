import asyncio
import sys


def configure_windows_event_loop_policy():
    if sys.platform != "win32":
        return

    policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if policy_cls is None:
        return

    if not isinstance(asyncio.get_event_loop_policy(), policy_cls):
        asyncio.set_event_loop_policy(policy_cls())
