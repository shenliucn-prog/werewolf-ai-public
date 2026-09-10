"""Web transport adapter for offline choices, including public-only spectators.

The game rules and saves remain OfflineSession's. This adapter owns no model
configuration, campaign state, or executable commands.
"""
import asyncio
from copy import deepcopy

from .offline_game import OfflineSession, action_choices


class WebOfflineSession(OfflineSession):
    async def ask_player(self, kind, data, *, action=None):
        if not self.spectator or kind == "ready":
            return await super().ask_player(kind, data, action=action)
        # A spectator never controls a hidden seat. Use the same lawful proxy
        # policy as the terminal, through the same durable acceptance path.
        pending = asyncio.create_task(super().ask_player(kind, data, action=action))
        try:
            await asyncio.sleep(0)
            if pending.done():
                return await pending  # committed replay needs no new decision
            options = action_choices(self, kind, data)
            selected = self.auto_choice(kind, data, options)
            request = self._human_request()
            if not super().submit(selected["payload"], request_id=request.request_id, require_request_id=True):
                raise ValueError("Could not accept the spectator's autonomous action")
            return await pending
        finally:
            if not pending.done():
                pending.cancel()
                try:
                    await pending
                except asyncio.CancelledError:
                    pass

    def submit_choice(self, choice_id, request_id):
        """HTTP submits only a menu ID, not forged speech/evidence fields."""
        if not self.pending or not isinstance(choice_id, str):
            return False
        if self.spectator and self.pending["kind"] != "ready":
            return False
        choices = action_choices(self, self.pending["kind"], self.pending["data"])
        selected = next((c for c in choices if c["id"] == choice_id), None)
        return bool(selected and super().submit(selected["payload"], request_id=request_id, require_request_id=True))

    def _delivery_event(self, event):
        # Never mutate the private ledger while constructing a transport view.
        result = deepcopy(super()._delivery_event(event))
        if self.spectator:
            if result["type"] == "private" or (result["type"] == "request" and result.get("kind") != "ready"):
                return {"type": "cursor", "event_no": result["event_no"]}
            if result["type"] == "init":
                result["player"] = None
                for seat in result["state"]["seats"]:
                    seat["is_player"] = False
        if result["type"] == "init":
            result["offline_choices"] = True
            result["spectator"] = self.spectator
        if result["type"] == "request":
            result["choices"] = [{key: c[key] for key in ("id", "group", "label")}
                                 for c in result.get("choices", [])]
        return result

    def recovery_view(self, last_event_no=0):
        result = deepcopy(super().recovery_view(last_event_no))
        result.update(offline_choices=True, spectator=self.spectator)
        if result["init"]:
            result["init"] = self._delivery_event(result["init"])
        if result["pending"]:
            pending = self._delivery_event(result["pending"])
            result["pending"] = pending if pending["type"] == "request" else None
        if self.spectator:
            result["private"] = None
            result["private_events"] = []
        return result
