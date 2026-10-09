"""Block-entry actions. Occupancy contacts never identify a decoder by themselves."""

from copy import deepcopy
import math
import threading
import time
import uuid

from .automation_recording import PlaybackPlan


class TrackTriggerController:
    @staticmethod
    def detector_limits(profile):
        if profile in {"z21", "z21_white", "z21_start", "dr5000"}:
            return 1, 255, 8
        if profile == "xpressnet":
            return 0, 127, 8
        if profile == "ecos":
            return 1, 256, 16
        return 0, 65535, 65535

    def __init__(self, app, definitions=()):
        self.app = app
        self.definitions = []
        self.results = {}
        self.pulses = {}
        self._base_feedback = dict(app.feedback_map)
        self._occupied = None
        self._positions = {}
        self._reported = {}
        self._pending = set()
        for value in definitions:
            try:
                self.definitions.append(self.validate(value, references=False))
            except ValueError as exc:
                app.events.append({"type": "track_trigger_invalid", "detail": str(exc)})
        self.rebase()

    def validate(self, raw, *, references=True):
        if not isinstance(raw, dict):
            raise ValueError("track trigger must be an object")
        value = dict(id=str(raw.get("id") or uuid.uuid4().hex),
                     name=str(raw.get("name") or "Track trigger").strip()[:80],
                     block_id=str(raw.get("block_id", "")).strip().upper(),
                     enabled=raw.get("enabled", True), train_scope=raw.get("train_scope", "any"),
                     train_ids=raw.get("train_ids", []), direction=raw.get("direction", "both"),
                     actions=deepcopy(raw.get("actions", [])), detector=deepcopy(raw.get("detector")))
        if not value["block_id"] or type(value["enabled"]) is not bool:
            raise ValueError("a block and boolean enabled setting are required")
        if value["train_scope"] not in ("any", "selected") or value["direction"] not in ("both", "forward", "reverse"):
            raise ValueError("choose any or selected trains and a valid direction")
        if not isinstance(value["train_ids"], list) or any(not isinstance(item, str) for item in value["train_ids"]):
            raise ValueError("train_ids must be a list of train IDs")
        value["train_ids"] = list(dict.fromkeys(self.app._canonical_train_id(item) for item in value["train_ids"]))
        if value["train_scope"] == "selected" and not value["train_ids"]:
            raise ValueError("choose at least one train")
        if references:
            if value["block_id"] not in {str(item["id"]).upper() for item in self.app.blocks}:
                raise ValueError("choose an existing trigger block")
            if any(item not in {train["id"] for train in self.app.trains} for item in value["train_ids"]):
                raise ValueError("a selected train no longer exists")
        detector = value["detector"]
        if detector is not None:
            if not isinstance(detector, dict) or set(detector) != {"module", "input"}:
                raise ValueError("detector needs a module and input")
            if (type(detector["module"]) is not int or not 0 <= detector["module"] <= 65535
                    or type(detector["input"]) is not int or not 1 <= detector["input"] <= 65535):
                raise ValueError("detector needs an integer module and positive input")
            if references:
                profile = self.app._active_hardware_profile().id
                if profile == "simulation":
                    profile = self.app._settings["hardware"]["system"]
                minimum, maximum, inputs = self.detector_limits(profile)
                if not minimum <= detector["module"] <= maximum or detector["input"] > inputs:
                    raise ValueError(f"detector for {profile} needs module {minimum}–{maximum} and input 1–{inputs}")
                key = (detector["module"], detector["input"])
                other_mapping = dict(self._base_feedback)
                for definition in self.definitions:
                    if definition["id"] != value["id"] and definition["detector"]:
                        other_mapping[(definition["detector"]["module"], definition["detector"]["input"])] = definition["block_id"]
                existing = other_mapping.get(key)
                if existing and str(existing).upper() != value["block_id"]:
                    raise ValueError("that detector contact is already mapped to another block")
        if not isinstance(value["actions"], list) or not 1 <= len(value["actions"]) <= 16:
            raise ValueError("add between 1 and 16 trigger actions")
        for action in value["actions"]:
            if not isinstance(action, dict):
                raise ValueError("trigger actions must be objects")
            if action.get("type") == "function":
                number = action.get("function_number")
                if type(number) is not int or not 0 <= number <= 31:
                    raise ValueError("choose a decoder function F0–F31")
                if references and number >= self.app._active_hardware_profile().max_functions:
                    raise ValueError("this command station does not support the configured function number")
                if action.get("mode") not in ("on", "off", "pulse") or action.get("target", "locomotive") not in ("locomotive", "rolling_stock"):
                    raise ValueError("choose function on, off or pulse and its decoder target")
                if action["mode"] == "pulse":
                    duration = action.get("duration_s", 1)
                    if isinstance(duration, bool) or not isinstance(duration, (float, int)) or not math.isfinite(duration) or not .1 <= duration <= 60:
                        raise ValueError("pulse duration must be between 0.1 and 60 seconds")
                if action.get("target") == "rolling_stock":
                    item = self.app.runtime.train_database.get_inventory(str(action.get("item_id", "")))
                    if references and (item is None or item.decoder_address is None or not any(f["function_number"] == number for f in item.decoder_functions)):
                        raise ValueError("choose rolling stock with this configured decoder function")
            elif action.get("type") == "routine":
                if not isinstance(action.get("program_id"), str) or not action["program_id"]:
                    raise ValueError("choose a saved routine")
                if references and not any(item["id"] == action["program_id"] for item in self.app._automation_programs):
                    raise ValueError("the selected routine no longer exists")
            else:
                raise ValueError("trigger actions support functions and saved routines")
        return value

    def upsert(self, raw):
        value = self.validate(raw, references=not isinstance(raw, dict) or raw.get("enabled") is not False)
        old = self.definitions
        self.definitions = [item for item in old if item["id"] != value["id"]] + [value]
        try:
            self.sync_mapping()
            self.app._persist_operating_plan()
        except Exception:
            self.definitions = old
            self.sync_mapping()
            raise
        self.results.pop(value["id"], None)
        return value

    def remove(self, trigger_id):
        old = self.definitions
        self.definitions = [item for item in old if item["id"] != trigger_id]
        if len(old) == len(self.definitions):
            raise ValueError("track trigger not found")
        try:
            self.sync_mapping()
            self.app._persist_operating_plan()
        except Exception:
            self.definitions = old
            self.sync_mapping()
            raise
        self.results.pop(trigger_id, None)

    def feedback_for_profile(self, profile, *, report=False):
        blocks = {str(block["id"]).upper() for block in self.app.blocks}
        mapping = {key: value for key, value in self._base_feedback.items() if str(value).upper() in blocks}
        minimum, maximum, inputs = self.detector_limits(profile)
        if any(not minimum <= module <= maximum or not 1 <= contact <= inputs for module, contact in mapping):
            raise ValueError("existing feedback mappings are incompatible with the selected command station")
        for definition in self.definitions:
            detector = definition["detector"]
            if detector and definition["block_id"] in blocks:
                key = detector["module"], detector["input"]
                reason = ("Detector mapping is incompatible with this command station"
                          if not minimum <= key[0] <= maximum or not 1 <= key[1] <= inputs
                          else "Detector contact is already mapped to another block"
                          if key in mapping and str(mapping[key]).upper() != definition["block_id"] else "")
                if reason:
                    if report:
                        self.result(definition, None, "inactive", reason)
                    continue
                mapping[key] = definition["block_id"]
        return mapping

    def rebase(self):
        """Reset observation after edits/startup; an already occupied section is not an entry."""
        profile = "simulation" if self.app.simulation_mode else self.app._active_hardware_profile().id
        mapping = self.feedback_for_profile(profile, report=True)
        method = getattr(self.app.runtime.track, "replace_feedback_map", None)
        if method:
            method(mapping)
        self.app.feedback_map = mapping
        snapshot = self.app.runtime.track.get_snapshot()
        self._positions = {motion.train_id: str(motion.block_id).upper() for motion in snapshot.trains}
        self._reported = dict(self._positions)
        self._occupied = None
        self._pending.clear()

    def sync_mapping(self):
        profile = "simulation" if self.app.simulation_mode else self.app._active_hardware_profile().id
        mapping = self.feedback_for_profile(profile)
        if mapping == self.app.feedback_map:
            return
        if not self.app.simulation_mode and self.app.track_power:
            raise ValueError("switch track power off before adding, changing or removing detector mappings")
        self.rebase()

    def before_tick(self):
        snapshot = self.app.runtime.track.get_snapshot()
        moving = {tid for tid, control in self.app.runtime.dispatcher.trains.items() if control.desired_speed > 0}
        moving.update(m.train_id for m in snapshot.trains if m.speed > 0 or m.target_speed > 0)
        return snapshot, moving

    def observe(self, before, stopped_trains=()):
        snapshot = self.app.runtime.track.get_snapshot()
        positions = {motion.train_id: str(motion.block_id).upper() for motion in snapshot.trains}
        if self.app.simulation_mode:
            previous = {m.train_id: str(m.block_id).upper() for m in before[0].trains}
            entries = [(tid, block) for tid, block in positions.items() if tid in previous and previous[tid] != block]
            self._positions = positions
            if self.app.track_power:
                for train_id, block in entries:
                    self.fire(train_id, block, stopped_trains=stopped_trains)
            return
        if (not self.app.track_power or not snapshot.powered
                or not self.app.runtime.connection.status.connected
                or not getattr(self.app.runtime.track, "feedback_healthy", True)):
            self.cancel_all()
            self._occupied = None
            self._pending.clear()
            return
        occupied = {str(block).upper() for block, values in snapshot.occupied_blocks.items() if values}
        if self._occupied is None:
            self._occupied = occupied
            return
        entered = occupied - self._occupied
        self._pending.intersection_update(occupied)
        self._occupied = occupied
        # Keep private route tracking through every mapped detector. This does not
        # change safety occupancy or claim that an occupancy contact measures ID.
        for tid, reported in positions.items():
            if self._reported.get(tid) != reported:
                self._positions[tid] = reported
        self._reported = positions
        mapped = {str(value).upper() for value in self.app.feedback_map.values()}
        for block in sorted(entered & mapped):
            identified = {str(tid) for bid, values in snapshot.occupied_blocks.items() if str(bid).upper() == block
                          for tid in values if tid in self.app.runtime.dispatcher.trains}
            if not identified:
                for motion in before[0].trains:
                    if motion.train_id not in before[1]:
                        continue
                    current = self._positions.get(motion.train_id, str(motion.block_id).upper())
                    train = next((t for t in self.app.trains if t["id"] == motion.train_id), {})
                    route = tuple(str(node).upper() for node in train.get("route", motion.route))
                    following = route[route.index(current) + 1:route.index(current) + 2] if current in route else ()
                    if current == block or following == (block,):
                        identified.add(motion.train_id)
                # An unpositioned moving train also makes identity ambiguous.
                positioned_members = set(positions)
                for train_id in positions:
                    positioned_members.update(self.app._coupled_train_ids(train_id))
                identified.update(before[1] - positioned_members)
            # Paired locomotives describe one assembled train.
            by_id = {train["id"]: train for train in self.app.trains}
            identified = {by_id.get(tid, {}).get("coupled_to") or tid for tid in identified}
            if len(identified) == 1 and next(iter(identified)) in positions:
                train_id = next(iter(identified))
                self._positions[train_id] = block
                self.fire(train_id, block, stopped_trains=stopped_trains)
            else:
                self._pending.add(block)
                for definition in self.definitions:
                    if definition["enabled"] and definition["block_id"] == block:
                        self.result(definition, None, "skipped", "Occupancy detected; confirm the passing train's position because its identity is unclear")

    def position_confirmed(self, train_id, block):
        self._positions[train_id] = block
        self._reported[train_id] = block
        if self.app.track_power and block in self._pending:
            self._pending.remove(block)
            self.fire(train_id, block)

    def result(self, definition, train_id, status, detail=""):
        value = dict(trigger_id=definition["id"], train_id=train_id, status=status, detail=detail,
                     time=time.time())
        self.results[definition["id"]] = value
        self.app.events.append({"type": "track_trigger_" + status, **value})

    def fire(self, train_id, block, *, stopped_trains=()):
        train = next((t for t in self.app.trains if t["id"] == train_id), None)
        if train is None or train_id not in self.app.runtime.dispatcher.trains or self.app._closed:
            return
        for definition in self.definitions:
            if not definition["enabled"] or definition["block_id"] != block:
                continue
            if definition["train_scope"] == "selected" and train_id not in definition["train_ids"]:
                continue
            if definition["direction"] != "both" and definition["direction"] != train.get("direction", "forward"):
                continue
            try:
                for action in definition["actions"]:
                    if action["type"] == "routine":
                        if train_id in stopped_trains or self.app.runtime.dispatcher.trains[train_id].mode.value == "stopped":
                            raise ValueError("routine skipped because the train is stopped; track triggers cannot override a safety stop")
                        program = next(p for p in self.app._automation_programs if p["id"] == action["program_id"])
                        actions, duration = self.app._compile_automation_program(train_id, program["blocks"])
                        plan = PlaybackPlan(train_id, actions, 0., duration)
                        self.app._playback_plan(plan, {"confirm": True, "automatic": True, "program_id": program["id"]}, "track_trigger_routine")
                    else:
                        self.function(train_id, action)
                self.result(definition, train_id, "fired")
            except Exception as exc:
                self.result(definition, train_id, "failed", str(exc))

    def function(self, train_id, action):
        number = action["function_number"]
        if number >= self.app._active_hardware_profile().max_functions:
            raise ValueError("this command station does not support the configured function number")
        stock = action.get("target") == "rolling_stock"
        train = next(t for t in self.app.trains if t["id"] == train_id)
        if stock:
            item = self.app.runtime.train_database.get_inventory(action["item_id"])
            if item is None or item.decoder_address is None:
                raise ValueError("rolling-stock decoder is no longer available")
            address, protocol = item.decoder_address, "dcc"
        else:
            address, protocol = train.get("address") or train_id, str(train.get("decoder_protocol") or "dcc").lower()
        key = str(address), protocol, number
        self.cancel_pulse(key)
        payload = dict(type="set_rolling_stock_function" if stock else "set_train_function", train_id=train_id,
                       function_number=number, enabled=action["mode"] != "off")
        if stock:
            payload["item_id"] = action["item_id"]
        self.app.command(payload)
        if action["mode"] == "pulse":
            track = self.app.runtime.track
            def expire():
                with self.app._lock:
                    if self.pulses.get(key, {}).get("timer") is not timer:
                        return
                    self.pulses.pop(key, None)
                    if self.app.runtime.track is track:
                        self._release(payload)
            timer = threading.Timer(float(action.get("duration_s", 1)), expire)
            timer.daemon = True
            self.pulses[key] = {"timer": timer, "payload": payload}
            timer.start()

    def _release(self, payload):
        try:
            self.app.command({**payload, "enabled": False})
        except Exception as exc:
            self.app.events.append({"type": "track_trigger_pulse_failed", "detail": str(exc)})

    def cancel_pulse(self, key):
        key = str(key[0]), key[1], key[2]
        pending = self.pulses.pop(key, None)
        if pending:
            pending["timer"].cancel()

    def cancel_train_function(self, train_id, number):
        train = next((t for t in self.app.trains if t["id"] == train_id), {})
        self.cancel_pulse((train.get("address") or train_id, str(train.get("decoder_protocol") or "dcc").lower(), number))

    def rename_block(self, old, new):
        self._base_feedback = {key: new if str(value).upper() == old else value for key, value in self._base_feedback.items()}
        for definition in self.definitions:
            if definition["block_id"] == old:
                definition["block_id"] = new
        self.rebase()
        self.app._persist_operating_plan()

    def cancel_all(self):
        pending = list(self.pulses.values())
        self.pulses.clear()
        for pulse in pending:
            pulse["timer"].cancel()
            self._release(pulse["payload"])

    def payload(self):
        definitions = deepcopy(self.definitions)
        for definition in definitions:
            definition["train_ids"] = [self.app._ui_train_id(tid) for tid in definition["train_ids"]]
        results = deepcopy(list(self.results.values()))
        for result in results:
            if result["train_id"]:
                result["train_id"] = self.app._ui_train_id(result["train_id"])
        return {"definitions": definitions, "results": results,
                "feedback_map": [{"module": mod, "input": contact, "block_id": block} for (mod, contact), block in self.app.feedback_map.items()],
                "pending_blocks": sorted(self._pending), "active_pulses": len(self.pulses)}
