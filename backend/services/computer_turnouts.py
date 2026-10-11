"""Durable turnout output assignments on the shared computer bridge."""
from copy import deepcopy


class ComputerTurnouts:
    def __init__(self, app, source, assignments=()):
        self.app, self.source = app, source
        self.assignments = []
        if not isinstance(assignments, list):
            assignments = []
        for row in assignments:
            try:
                value = self.validate(row)
                if any(other["turnout_id"] == value["turnout_id"] or (other["module"], other["output"]) == (value["module"], value["output"]) for other in self.assignments):
                    raise ValueError("duplicate computer switch assignment")
                self.assignments.append(value)
            except ValueError as exc:
                app.events.append({"type": "computer_turnout_invalid", "detail": str(exc)})
        self.rebase()

    @staticmethod
    def validate(row):
        if not isinstance(row, dict) or set(row) != {"turnout_id", "module", "output", "inverted", "pulse_ms"}:
            raise ValueError("switch assignment needs turnout_id, module, output, inverted and pulse_ms")
        if not isinstance(row["turnout_id"], str) or not row["turnout_id"].strip():
            raise ValueError("choose a track switch")
        for key in ("module", "output"):
            if type(row[key]) is not int or not 1 <= row[key] <= 65535:
                raise ValueError(f"switch {key} must be 1–65535")
        if type(row["inverted"]) is not bool or type(row["pulse_ms"]) is not int or not 50 <= row["pulse_ms"] <= 1000:
            raise ValueError("switch inversion must be boolean and pulse must be 50–1000 ms")
        return {**row, "turnout_id": row["turnout_id"].strip().upper()}

    def canonical_id(self, value):
        value = str(value or "").strip().upper()
        return str(self.app.turnouts[0]["id"]).upper() if value == "TO1" and self.app.turnouts else value

    def rebase(self):
        ids = {str(item["id"]).upper() for item in self.app.turnouts}
        self.source.replace_turnouts({row["turnout_id"]: row for row in self.assignments if row["turnout_id"] in ids})

    def set_assignment(self, turnout_id, assignment):
        turnout_id = self.canonical_id(turnout_id)
        old = self.assignments
        value = None if assignment is None else self.validate({**assignment, "turnout_id": turnout_id} if isinstance(assignment, dict) else assignment)
        if value and turnout_id not in {str(item["id"]).upper() for item in self.app.turnouts}:
            raise ValueError("choose an existing track switch")
        if value and any(row["turnout_id"] != turnout_id and (row["module"], row["output"]) == (value["module"], value["output"]) for row in old):
            raise ValueError("computer bridge output is already assigned to another switch")
        replacement = [row for row in old if row["turnout_id"] != turnout_id] + ([value] if value else [])
        if replacement == old:
            return
        if not self.app.simulation_mode and self.app.track_power:
            raise ValueError("switch track power off before changing switch connections")
        if self.app.runtime.interlocking.locks.get(turnout_id):
            raise ValueError("this track switch is locked by a train route")
        self.assignments = replacement
        try:
            self.rebase()
            self.app._persist_operating_plan()
        except Exception:
            self.assignments = old
            self.rebase()
            raise

    def payload(self):
        ids = {str(item["id"]).upper() for item in self.app.turnouts}
        return [{**deepcopy(row), "available": row["turnout_id"] in ids,
                 "confirmed_state": self.source.payload()["switch_states"].get(row["turnout_id"])} for row in self.assignments]

    def editor_payload(self):
        return {"assignments": self.payload(), "computer_feedback": self.source.payload(),
                "physical": not self.app.simulation_mode, "track_power": self.app.track_power,
                "turnouts": [{"id": str(item["id"]).upper(), "name": item.get("name", item["id"]),
                              "state": item.get("state", "straight"), "address": item.get("address"),
                              "locked_by": self.app.runtime.interlocking.locks.get(str(item["id"]).upper())}
                             for item in self.app.turnouts]}
