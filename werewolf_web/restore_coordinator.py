"""Shared restore policy; adapters own file access, registry locks and errors.

Connection credentials/commands come from trusted local settings or CLI inputs,
never from save payloads. The session validates the saved endpoint and driver.
"""
import asyncio

from . import driver as driver_mod


def runtime_kwargs(payload, saved, *, command=None, model=None, effort=None,
                   max_calls=None):
    driver, adapter = payload.get("driver"), payload.get("adapter")
    if driver is None:
        driver, adapter = driver_mod.infer_legacy_driver(
            payload.get("planner"), payload.get("campaign_counted"))
    kwargs = driver_mod.restore_runtime_kwargs(driver, adapter, saved, command=command)
    if kwargs is None:
        return None
    if model:
        kwargs["model"] = model
    if effort:
        kwargs["effort"] = effort
    if max_calls is not None:
        kwargs["max_calls"] = max_calls
    return kwargs


async def restore_and_verify(session, payload, *, resume_campaign):
    """Restore -> campaign reconcile -> reserve -> persist -> live preflight.

    Return False for a refused campaign. All validation/I/O/model exceptions
    propagate for each adapter to report using its existing error contract.
    No registration or model request occurs before successful save validation.
    """
    session.restore(payload)
    if session.campaign_profile and not resume_campaign(
            session.campaign_profile, session.session_id, session):
        return False
    planner = session.planner
    if planner is not None:
        planner.reserve()
        session._checkpoint()
        await asyncio.to_thread(planner.preflight_check)
    return True
