# pistoncore/backend/compiler.py
#
# Matches COMPILER_SPEC.md Section 8 entry point and Section 13 result contract.
# Started from Grok's skeleton — fixed and completed by Claude (Sessions 8-9).
# Session 10: five bug fixes — hash, globals writes, _scan_globals, only_when, for_loop substitution.
# Session 28: S1-7 session 1 — Bugs 1-7, 11, 13, 14, 19, 22, 23, 24 fixed.
# Session 35: S-NESTED Session A — nested tree model. stmt_map and ID resolution removed.
#   _compile_sequence now accepts list of statement objects directly.
#   _collect_triggers now recurses into nested children at any depth.
#   All control-flow methods: stmt_map parameter removed.
#
# This file is designed to be easy for anyone + Claude to maintain.
# Each method references the COMPILER_SPEC section it implements.
# Add new statement types by adding an elif in _compile_sequence()
# and a corresponding _compile_<type>() method below.
#
# Usage:
#   compiler = Compiler(template_dir="path/to/native-script/")
#   result = compiler.compile_piston(context)
#   # context is the fat compiler context object — COMPILER_SPEC Section 7
#   # result is a CompilerResult — COMPILER_SPEC Section 13

import re
import hashlib
from dataclasses import dataclass, field
from typing import Any
from jinja2 import Environment, FileSystemLoader, select_autoescape

import utils


# ---------------------------------------------------------------------------
# Compiler result types — COMPILER_SPEC Section 13
# ---------------------------------------------------------------------------

@dataclass
class CompilerMessage:
    """
    A single compiler error or warning.
    level:   "error" | "warning" | "info"
    code:    SCREAMING_SNAKE_CASE identifier — used by frontend and tests
    message: plain English, shown directly to user
    context: which statement caused this (optional)
    COMPILER_SPEC Section 13.
    """
    level: str
    code: str
    message: str
    context: str | None = None

    def __str__(self):
        return f"[{self.code}] {self.message}"


@dataclass
class CompilerResult:
    """
    Return value from compile_piston().
    automation_yaml: automation file content, or None if omitted/error
    script_yaml:     script file content, or None on error
    errors:          list of CompilerMessage with level="error"
    warnings:        list of CompilerMessage with level="warning"
    COMPILER_SPEC Section 13.
    """
    automation_yaml: str | None = None
    script_yaml: str | None = None
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class CompilerError(Exception):
    """
    Raised internally to abort compilation on unrecoverable problems.
    Always caught in compile_piston() and converted to a CompilerMessage.
    Never propagates to the caller — caller always receives a CompilerResult.
    COMPILER_SPEC Section 13.
    """
    def __init__(self, message: str, code: str = "COMPILER_ERROR", context: str | None = None):
        super().__init__(message)
        self.code = code
        self.context = context


# ---------------------------------------------------------------------------
# Compiler class
# ---------------------------------------------------------------------------

class Compiler:

    def __init__(
        self,
        template_dir: str = "/pistoncore-customize/compiler-templates/native-script/",
    ):
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    # -----------------------------------------------------------------------
    # Section 4 — Slug generation (delegated to utils.slugify)
    # -----------------------------------------------------------------------

    def slugify(self, name: str) -> str:
        """
        Thin wrapper — delegates to utils.slugify.
        Kept as a method so existing call sites (self.slugify(...)) don't change.
        COMPILER_SPEC Section 4.
        """
        return utils.slugify(name)

    # -----------------------------------------------------------------------
    # Section 5 — Main entry point
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # Section 8 — Main entry point
    # -----------------------------------------------------------------------

    def compile_piston(self, context: dict) -> CompilerResult:
        """
        Main entry point. Accepts fat compiler context object, returns CompilerResult.

        context keys (COMPILER_SPEC Section 7):
          piston             — full piston JSON dict (includes device_map, statements)
          global_variables   — list of global variable definition objects
          known_piston_ids   — maps piston IDs to themselves (for call_piston resolution)
          pistoncore_version — version string for file header

        COMPILER_SPEC Section 8.
        """
        result = CompilerResult()

        try:
            piston           = context["piston"]
            device_map       = piston.get("device_map", {})
            globals_store    = {
                g["name"]: g
                for g in context.get("global_variables", [])
                if "name" in g
            }
            known_piston_ids = context.get("known_piston_ids", {})
            app_version      = context.get("pistoncore_version", "1.0")

            slug = self.slugify(piston["name"])

            # Slug collision check — alias field only, COMPILER_SPEC Section 4
            if known_piston_ids:
                other_names = {
                    pid: p.get("name", "") if isinstance(p, dict) else ""
                    for pid, p in known_piston_ids.items()
                    if pid != piston["id"]
                }
                for pid, other_name in other_names.items():
                    if self.slugify(other_name) == slug:
                        slug = f"{slug}_{piston['id'][:4]}"[:50]
                        result.warnings.append(CompilerMessage(
                            level="warning",
                            code="SLUG_COLLISION",
                            message=(
                                f"Piston name '{piston['name']}' produces the same alias slug "
                                f"as another piston. Appended piston ID prefix to disambiguate: '{slug}'."
                            ),
                        ))
                        break

            globals_used = self._scan_globals(piston)

            # Bug 25: PyScript dispatch — branch must exist even as stub.
            # compile_target is set by the compiler via detect_compile_target,
            # but for now we read what's stored in the piston JSON.
            # Full PyScript compiler is S1-7 session 3.
            compile_target = piston.get("compile_target", "native_script")
            if compile_target == "pyscript":
                raise CompilerError(
                    "This piston requires PyScript compilation which is not yet "
                    "implemented. PyScript support is coming in a future release. "
                    "Remove any break, on_event, or cancel_pending_tasks statements "
                    "to compile as a native HA script.",
                    code="PYSCRIPT_NOT_IMPLEMENTED",
                )

            # Collect triggers — condition objects with is_trigger:true.
            # Recurses the nested statement tree at any depth.
            # COMPILER_SPEC Section 9.3
            trigger_conditions = self._collect_triggers(piston)

            # called_by_piston — no automation file generated
            omit_automation = any(
                c.get("subject") == "called_by_piston"
                for c in trigger_conditions
            )

            # manual_only — automation file gets empty trigger list, no error
            manual_only = any(
                c.get("subject") == "manual_only"
                for c in trigger_conditions
            )

            # NO_TRIGGERS validation — COMPILER_SPEC Section 13
            if not trigger_conditions and not omit_automation and not manual_only:
                raise CompilerError(
                    "This piston has no triggers defined. It will never run automatically. "
                    "Add at least one trigger in the Triggers section.",
                    code="NO_TRIGGERS",
                )

            compiled_triggers = self._compile_triggers(
                trigger_conditions, device_map, result.warnings
            )
            compiled_conditions = self._compile_conditions(
                piston.get("conditions", []), device_map, result.warnings
            )
            compiled_sequence = self._compile_sequence(
                piston.get("statements", []),
                piston,
                device_map,
                globals_store,
                known_piston_ids,
                result.warnings,
            )

            if omit_automation:
                result.automation_yaml = ""
            else:
                result.automation_yaml = self._render_automation(
                    piston, slug, compiled_triggers, compiled_conditions, app_version
                )

            result.script_yaml = self._render_script(
                piston, slug, compiled_sequence, globals_used, app_version
            )

        except CompilerError as e:
            result.errors.append(CompilerMessage(
                level="error",
                code=e.code,
                message=str(e),
                context=e.context,
            ))
            result.automation_yaml = None
            result.script_yaml = None

        return result

    # -----------------------------------------------------------------------
    # Section 5 — scan_globals
    # -----------------------------------------------------------------------

    def _scan_globals(self, piston: dict) -> list[str]:
        """
        Walk the entire piston JSON and collect every global variable name
        referenced anywhere (triggers, conditions, actions).
        Global variables appear in two ways:
          1. As a dict value for known keys like "variable_name" or "target_role" → "@name"
          2. Embedded in expression strings → any substring matching @word_chars
        Returns a sorted list of names, or ["(none)"] if none found.
        COMPILER_SPEC Section 5.
        """
        found = set()
        # Matches @identifier anywhere in a string (e.g. in value_expression, conditions)
        _global_ref_re = re.compile(r"@([A-Za-z_]\w*)")

        def walk(obj: Any):
            if isinstance(obj, dict):
                # Check known structured keys explicitly
                role = obj.get("target_role", "")
                if isinstance(role, str) and role.startswith("@"):
                    found.add(role[1:])
                var = obj.get("variable_name", "")
                if isinstance(var, str) and var.startswith("@"):
                    found.add(var[1:])
                # Scan all string values for embedded @references
                for v in obj.values():
                    if isinstance(v, str):
                        for m in _global_ref_re.finditer(v):
                            found.add(m.group(1))
                    else:
                        walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(piston)
        return sorted(found) if found else ["(none)"]

    # -----------------------------------------------------------------------
    # Section 9.3 — Trigger collection and compilation
    # -----------------------------------------------------------------------

    def _collect_triggers(self, piston: dict) -> list:
        """
        Recursively walk the nested statement tree and collect every condition object
        where is_trigger is True. Triggers can appear in any if block at any depth.
        Nested tree model: children are embedded objects, no stmt_map needed.
        COMPILER_SPEC Section 9.3.
        """
        found = []

        def walk_stmts(stmts: list):
            for stmt in stmts:
                # Collect triggers from this statement's conditions array
                for cond in stmt.get("conditions", []):
                    if cond.get("is_trigger"):
                        found.append(cond)
                # Recurse into all child statement arrays
                for key in ("then", "else", "statements"):
                    children = stmt.get(key, [])
                    if children:
                        walk_stmts(children)
                # else_ifs each have their own conditions and statements
                for eib in stmt.get("else_ifs", []):
                    for cond in eib.get("conditions", []):
                        if cond.get("is_trigger"):
                            found.append(cond)
                    walk_stmts(eib.get("statements", []))
                # switch cases
                for case in stmt.get("cases", []):
                    walk_stmts(case.get("statements", []))
                walk_stmts(stmt.get("default_statements", []))

        walk_stmts(piston.get("statements", []))
        return found

    def _compile_triggers(
        self, trigger_conditions: list, device_map: dict, warnings: list
    ) -> str:
        """
        Compile collected trigger condition objects to YAML trigger blocks.
        Each trigger gets an id: field injected as line 2 of the template output.
        All trigger templates start with '- trigger: X' — id: goes on line 2.
        Returns pre-indented YAML string (4 spaces).
        COMPILER_SPEC Section 9.3.
        """
        if not trigger_conditions:
            return "    []"

        if any(c.get("subject") in ("manual_only", "called_by_piston")
               for c in trigger_conditions):
            return "    []"

        lines = []
        for cond in trigger_conditions:
            subject  = cond.get("subject", "")
            operator = cond.get("operator", "")
            role     = cond.get("role", "")
            value    = cond.get("value")
            cond_id  = cond.get("id", "")

            if subject == "time" and operator == "happens daily at":
                if isinstance(value, dict) and "preset" in value:
                    preset    = value.get("preset", "sunset")
                    offset    = value.get("offset", 0)
                    direction = value.get("offset_direction", "+")
                    unit      = value.get("offset_unit", "minutes")
                    offset_minutes = offset if unit == "minutes" else offset * 60
                    if direction == "-":
                        offset_minutes = -offset_minutes
                    tmpl = self.env.get_template("snippets/trigger_sun.yaml.j2")
                    rendered = tmpl.render(
                        event=preset,
                        offset=self._format_offset(offset_minutes),
                    )
                else:
                    at_time = value if isinstance(value, str) else cond.get("compiled_value", "")
                    tmpl = self.env.get_template("snippets/trigger_time.yaml.j2")
                    rendered = tmpl.render(at_time=at_time)
                lines.append(self._inject_trigger_id(rendered, cond_id))

            elif subject == "system_start":
                tmpl = self.env.get_template("snippets/trigger_homeassistant.yaml.j2")
                rendered = tmpl.render(event="start")
                lines.append(self._inject_trigger_id(rendered, cond_id))

            elif role and operator in ("changes to", "changes from", "changes"):
                entity_ids = self._resolve_role_entities(role, device_map, cond_id)
                compiled_value = cond.get("compiled_value", value or "")
                for entity_id in entity_ids:
                    tmpl = self.env.get_template("snippets/trigger_state.yaml.j2")
                    rendered = tmpl.render(
                        entity_id=entity_id,
                        to=compiled_value if operator in ("changes to", "changes") else None,
                        from_state=cond.get("from_state"),
                        for_seconds=cond.get("for_seconds"),
                    )
                    lines.append(self._inject_trigger_id(rendered, cond_id))

            elif role and operator in ("drops below", "rises above"):
                entity_ids = self._resolve_role_entities(role, device_map, cond_id)
                compiled_value = cond.get("compiled_value", value)
                for entity_id in entity_ids:
                    tmpl = self.env.get_template("snippets/trigger_numeric.yaml.j2")
                    rendered = tmpl.render(
                        entity_id=entity_id,
                        above=compiled_value if operator == "rises above" else None,
                        below=compiled_value if operator == "drops below" else None,
                    )
                    lines.append(self._inject_trigger_id(rendered, cond_id))

            else:
                warnings.append(CompilerMessage(
                    level="warning",
                    code="UNKNOWN_TRIGGER",
                    message=(
                        f"Trigger condition '{cond_id}' has subject='{subject}' "
                        f"operator='{operator}' which is not yet implemented. "
                        f"This trigger was skipped."
                    ),
                    context=cond_id,
                ))

        if not lines:
            return "    []"

        indented = "\n".join(
            "    " + line for line in "\n".join(lines).splitlines()
        )
        return indented

    def _inject_trigger_id(self, rendered: str, cond_id: str) -> str:
        """
        Insert id: as the second line of a rendered trigger template block.
        All trigger templates start with '- trigger: something' on line 1.
        The id: field is injected immediately after, indented to match.
        This is correct HA YAML — id: is a sibling key under the list item,
        not a nested structure.
        COMPILER_SPEC Section 9.3 (Bug 2 fix).
        """
        template_lines = rendered.rstrip("\n").splitlines()
        if not template_lines:
            return rendered
        return "\n".join(
            [template_lines[0], f'  id: "{cond_id}"'] + template_lines[1:]
        )

    def _resolve_role_entities(
        self, role: str, device_map: dict, context_id: str = ""
    ) -> list:
        """
        Resolve a role name to a list of entity IDs.
        Raises CompilerError with UNMAPPED_ROLE if role not in device_map.
        """
        entity_ids = device_map.get(role)
        if not entity_ids:
            raise CompilerError(
                f"Role '{role}' is referenced but no device is mapped to that role.",
                code="UNMAPPED_ROLE",
                context=context_id,
            )
        if isinstance(entity_ids, str):
            return [entity_ids]
        return list(entity_ids)

    def _format_offset(self, minutes: int) -> str:
        """COMPILER_SPEC Section 9.3 — sun trigger offset formatting."""
        if minutes == 0:
            return "00:00:00"
        sign = "+" if minutes > 0 else "-"
        m = abs(minutes)
        h, rem = divmod(m, 60)
        return f"{sign}{h:02d}:{rem:02d}:00"

    # -----------------------------------------------------------------------
    # Section 6.4 + 8.5 — Condition compilation
    # -----------------------------------------------------------------------

    def _compile_conditions(
        self, conditions: list, device_map: dict, warnings: list
    ) -> str:
        """
        Compile top-level piston conditions.
        Returns "[]" if no conditions.
        _compile_single_condition returns the full block including "- ".
        COMPILER_SPEC Section 6.4 and 8.5.
        """
        if not conditions:
            return "[]"

        lines = []
        for cond in conditions:
            lines.append(self._compile_single_condition(cond, device_map))
        return "\n".join(lines)

    def _compile_single_condition(self, cond: dict, device_map: dict) -> str:
        """
        Compile one condition object to a HA condition YAML block.
        Returns the FULL block INCLUDING the leading "- " dash.
        Multi-line conditions (AND/OR groups) are returned with all lines
        correctly structured — callers pass this directly to templates.
        COMPILER_SPEC Section 8.5, Section 11.
        Bug 4/5 fix: dash is always included here, never added by callers.
        Bug 11 fix: boolean state values always quoted.
        """
        ctype = cond.get("type")

        # AND / OR condition groups — recursive, full block returned
        if ctype in ("and", "or"):
            tmpl_name = "snippets/condition_and.yaml.j2" if ctype == "and" else "snippets/condition_or.yaml.j2"
            compiled_subs = [
                self._compile_single_condition(sub, device_map)
                for sub in cond.get("conditions", [])
            ]
            # condition_and/or templates receive pre-compiled sub-condition blocks
            tmpl = self.env.get_template(tmpl_name)
            return tmpl.render(compiled_conditions=compiled_subs).rstrip("\n")

        # Detect subject type — flat format (PISTON_FORMAT.md) uses role at top level
        if "role" in cond and not isinstance(cond.get("subject"), dict):
            subject = {
                "type": "device",
                "role": cond.get("role", ""),
                "attribute": cond.get("attribute", ""),
                "attribute_type": cond.get("attribute_type", ""),
            }
        else:
            subject = cond.get("subject", {})

        # Time condition — subject=="time" or role=="time"
        if cond.get("subject") == "time" or subject.get("type") == "time":
            return self._compile_time_condition(cond)

        subject_type = subject.get("type") or ("device" if subject.get("role") else None)
        operator = cond.get("operator", "is")
        compiled_value = cond.get("compiled_value", cond.get("value", ""))

        # Bug 11 — quote boolean state strings so YAML doesn't interpret them as booleans
        BOOLEAN_STATES = {"on", "off", "true", "false", "yes", "no", "home", "not_home"}
        def _quote_state(val):
            if isinstance(val, str) and val.lower() in BOOLEAN_STATES:
                return f'"{val}"'
            return val

        if subject_type == "device":
            role = subject.get("role", "")
            entity_ids = self._resolve_role_entities(role, device_map, cond.get("id", ""))
            aggregation = cond.get("aggregation", "any")
            attribute_type = subject.get("attribute_type", "") or cond.get("attribute_type", "")
            is_numeric = attribute_type == "numeric" or any(
                kw in operator for kw in ("greater", "less", "above", "below", "between", "even", "odd")
            )

            if is_numeric:
                return self._compile_numeric_condition(
                    cond, entity_ids, operator, compiled_value, aggregation
                )
            else:
                return self._compile_state_condition(
                    cond, entity_ids, operator, compiled_value, aggregation,
                    subject, _quote_state
                )

        elif subject_type == "variable":
            tmpl = self.env.get_template("snippets/condition_template.yaml.j2")
            var_name = subject.get("name", "").lstrip("$")
            op_map = {
                "is": "==", "is not": "!=",
                "is greater than": ">", "is less than": "<",
                "is greater than or equal to": ">=", "is less than or equal to": "<=",
            }
            op = op_map.get(operator, "==")
            if isinstance(compiled_value, str):
                template_expr = f"{{{{ {var_name} {op} '{compiled_value}' }}}}"
            else:
                template_expr = f"{{{{ {var_name} {op} {compiled_value} }}}}"
            return tmpl.render(template_expression=template_expr).rstrip("\n")

        raise CompilerError(
            f"Cannot compile condition — unknown subject type '{subject_type}'.",
            code="UNKNOWN_CONDITION_TYPE",
        )

    def _compile_time_condition(self, cond: dict) -> str:
        """
        Compile a time condition object to a HA condition: time block.
        Routes through condition_time.yaml.j2 — HA syntax changes only
        require a template update, not a Python change.
        COMPILER_SPEC Section 11, MISSING_SPECS.md Item 14.

        Cases:
          "is between"  → after + before (+ optional weekday)
          "is"          → 1-second window around exact time + CompilerWarning
          $sunrise/$sunset → CompilerError SUN_TIME_CONDITION_NOT_SUPPORTED
        """
        operator = cond.get("operator", "is between")
        value_from = cond.get("value_from")
        value_to = cond.get("value_to")
        only_on_days = cond.get("only_on_days")

        # Day number → HA weekday name
        DAY_MAP = {1: "mon", 2: "tue", 3: "wed", 4: "thu",
                   5: "fri", 6: "sat", 7: "sun"}
        weekday = [DAY_MAP[d] for d in only_on_days if d in DAY_MAP] if only_on_days else None

        # $sunrise/$sunset not supported in time conditions — HA condition:time
        # does not support sun-relative values. Emit CompilerError.
        for val in [value_from, value_to]:
            if isinstance(val, str) and ("sunrise" in val or "sunset" in val):
                raise CompilerError(
                    "Time condition with $sunrise or $sunset offset is not yet supported. "
                    "Use a time trigger instead, or set a fixed time window.",
                    code="SUN_TIME_CONDITION_NOT_SUPPORTED",
                    context=cond.get("id"),
                )

        tmpl = self.env.get_template("snippets/condition_time.yaml.j2")

        if operator == "is between":
            return tmpl.render(
                after=value_from,
                before=value_to,
                weekday=weekday,
            ).rstrip("\n")

        elif operator == "is":
            # Exact time — bracket with 1-second window and emit a warning.
            # GAP-S33-3 fix: degrade gracefully instead of aborting the compile.
            # The wizard may write the exact time into "value" or "value_from" —
            # check both and use whichever is present.
            exact_time = cond.get("value") or value_from
            if not exact_time or not isinstance(exact_time, str):
                raise CompilerError(
                    "Time 'is' condition has no time value defined.",
                    code="INVALID_TIME_CONDITION",
                    context=cond.get("id"),
                )
            # Parse HH:MM or HH:MM:SS and compute ±1-second bracket
            parts = exact_time.split(":")
            try:
                h = int(parts[0])
                m = int(parts[1]) if len(parts) > 1 else 0
                s = int(parts[2]) if len(parts) > 2 else 0
            except (ValueError, IndexError):
                raise CompilerError(
                    f"Time 'is' condition has an unparseable time value: '{exact_time}'.",
                    code="INVALID_TIME_CONDITION",
                    context=cond.get("id"),
                )
            # Compute before (+1 second) and after (-1 second) with rollover handling
            total_seconds = h * 3600 + m * 60 + s
            after_seconds  = (total_seconds - 1) % 86400
            before_seconds = (total_seconds + 1) % 86400
            def _fmt(secs):
                hh, rem = divmod(secs, 3600)
                mm, ss  = divmod(rem, 60)
                return f"{hh:02d}:{mm:02d}:{ss:02d}"
            # Note: _compile_single_condition has no access to the warnings list —
            # it is not passed into this method. The warning that this 1-second window
            # was used surfaces only as a comment in the compiled YAML output (via the
            # template). It does NOT appear as a CompilerMessage in result.warnings.
            # GAP-S34-1: refactor _compile_single_condition to accept a warnings list
            # so this can emit a proper CompilerMessage. Low priority — YAML comment
            # is sufficient for now. Fits S1-7 session 4 or whenever
            # _compile_single_condition is next touched.
            return tmpl.render(
                after=_fmt(after_seconds),
                before=_fmt(before_seconds),
                weekday=weekday,
                exact_time_warning=exact_time,
            ).rstrip("\n")

        else:
            raise CompilerError(
                f"Unknown time condition operator '{operator}'.",
                code="UNKNOWN_TIME_OPERATOR",
                context=cond.get("id"),
            )

    def _compile_numeric_condition(
        self, cond: dict, entity_ids: list, operator: str,
        compiled_value, aggregation: str
    ) -> str:
        """
        Compile a numeric device condition to condition: template.
        Handles aggregation (any/all) across multiple entity IDs.
        COMPILER_SPEC Section 11.
        """
        op_map = {
            "is greater than": ">", "is less than": "<",
            "is greater than or equal to": ">=", "is less than or equal to": "<=",
            "rises above": ">", "drops below": "<",
            "is even": "% 2 == 0", "is odd": "% 2 != 0",
        }

        tmpl = self.env.get_template("snippets/condition_template.yaml.j2")

        if operator == "is between":
            value_from = cond.get("value_from", cond.get("compiled_value", ""))
            value_to = cond.get("value_to", "")
            def single_expr(eid):
                return (f"float(states('{eid}')) >= {value_from} and "
                        f"float(states('{eid}')) <= {value_to}")
        elif operator in ("is even", "is odd"):
            op = op_map[operator]
            def single_expr(eid):
                return f"float(states('{eid}')) {op}"
        else:
            op = op_map.get(operator, "==")
            def single_expr(eid):
                return f"float(states('{eid}')) {op} {compiled_value}"

        if len(entity_ids) == 1:
            template_expr = f"{{{{ {single_expr(entity_ids[0])} }}}}"
        elif aggregation == "all":
            inner = ", ".join(single_expr(eid) for eid in entity_ids)
            template_expr = f"{{{{ [{inner}] | select('equalto', true) | list | count == {len(entity_ids)} }}}}"
        else:  # any (default)
            inner = ", ".join(single_expr(eid) for eid in entity_ids)
            template_expr = f"{{{{ [{inner}] | select('equalto', true) | list | count > 0 }}}}"

        return tmpl.render(template_expression=template_expr).rstrip("\n")

    def _compile_state_condition(
        self, cond: dict, entity_ids: list, operator: str,
        compiled_value, aggregation: str, subject: dict, quote_fn
    ) -> str:
        """
        Compile a binary/state/enum device condition.
        Single entity → condition:state template.
        Multiple entities or aggregation → condition:template with any()/all().
        COMPILER_SPEC Section 11.
        """
        attribute = subject.get("attribute") or cond.get("attribute") or None

        if operator == "is any of":
            values = cond.get("value", [])
            if not isinstance(values, list):
                values = [values]
            quoted = [f"'{v}'" for v in values]

            def single_expr(eid):
                attr_ref = f"state_attr('{eid}', '{attribute}')" if attribute else f"states('{eid}')"
                return f"{attr_ref} in [{', '.join(quoted)}]"

            tmpl = self.env.get_template("snippets/condition_template.yaml.j2")
            if len(entity_ids) == 1:
                template_expr = f"{{{{ {single_expr(entity_ids[0])} }}}}"
            elif aggregation == "all":
                inner = ", ".join(f"({single_expr(eid)})" for eid in entity_ids)
                template_expr = f"{{{{ {inner} | map('bool') | list == [true] * {len(entity_ids)} }}}}"
            else:
                parts = " or ".join(f"({single_expr(eid)})" for eid in entity_ids)
                template_expr = f"{{{{ {parts} }}}}"
            return tmpl.render(template_expression=template_expr).rstrip("\n")

        # Simple is / is not — single entity uses condition:state, multi uses template
        op = "==" if operator in ("is", "changes to", "changes") else "!="
        quoted_val = quote_fn(compiled_value)

        if len(entity_ids) == 1 and not attribute:
            tmpl = self.env.get_template("snippets/condition_state.yaml.j2")
            return tmpl.render(
                entity_id=entity_ids[0],
                state=quoted_val,
                attribute=attribute,
            ).rstrip("\n")

        # Multiple entities or attribute — compile to template
        tmpl = self.env.get_template("snippets/condition_template.yaml.j2")

        def single_expr(eid):
            if attribute:
                return f"state_attr('{eid}', '{attribute}') {op} '{compiled_value}'"
            return f"states('{eid}') {op} '{compiled_value}'"

        if len(entity_ids) == 1:
            template_expr = f"{{{{ {single_expr(entity_ids[0])} }}}}"
        elif aggregation == "all":
            parts = " and ".join(f"({single_expr(eid)})" for eid in entity_ids)
            template_expr = f"{{{{ {parts} }}}}"
        else:
            parts = " or ".join(f"({single_expr(eid)})" for eid in entity_ids)
            template_expr = f"{{{{ {parts} }}}}"

        return tmpl.render(template_expression=template_expr).rstrip("\n")

    # -----------------------------------------------------------------------
    # Section 7.2 — Statement dispatcher
    # -----------------------------------------------------------------------

    def _compile_sequence(
        self,
        child_stmts: list,
        piston: dict,
        device_map: dict,
        globals_store: dict,
        known_piston_ids: dict,
        warnings: list,
        indent: int = 4,
        _append_completion_event: bool = True,
    ) -> str:
        """
        Main statement dispatcher. Walks child_stmts — a list of statement objects —
        and compiles each one. Children are embedded objects in the nested tree model;
        no ID resolution or stmt_map required.
        Appends the PISTONCORE_RUN_COMPLETE event at end of the top-level sequence only.
        COMPILER_SPEC Section 7.2 / 10.2. PISTON_FORMAT.md nested tree model.
        """
        lines = []
        for stmt in (child_stmts or []):
            if not isinstance(stmt, dict):
                # Defensive: skip anything that isn't a statement object
                warnings.append(CompilerMessage(
                    level="warning",
                    code="INVALID_STATEMENT",
                    message=f"Expected a statement object, got {type(stmt).__name__} — skipped.",
                ))
                continue

            stmt_type = stmt.get("type")

            # only_when — COMPILER_SPEC Section 8.16
            # If the statement has an only_when condition, emit a HA condition: action
            # immediately before the statement itself. The statement is skipped at
            # runtime if the condition is not met.
            if "only_when" in stmt and stmt["only_when"]:
                try:
                    # _compile_single_condition returns full block including "- "
                    cond_body = self._compile_single_condition(
                        stmt["only_when"], device_map
                    )
                    lines.append(cond_body)
                except CompilerError as e:
                    warnings.append(CompilerMessage(
                        level="warning",
                        code="ONLY_WHEN_COMPILE_FAILED",
                        message=(
                            f"Statement {stmt.get('id', '?')} has an only_when condition "
                            f"that could not be compiled and was skipped: {e}"
                        ),
                        context=stmt.get("id"),
                    ))

            if stmt_type == "action":
                lines.append(self._compile_with_block(stmt, device_map, warnings))

            elif stmt_type == "wait":
                lines.append(self._compile_wait(stmt, warnings))

            elif stmt_type == "wait_for_state":
                lines.append(self._compile_wait_for_state(stmt, device_map))

            elif stmt_type == "if":
                lines.append(self._compile_if_block(
                    stmt, piston, device_map, globals_store,
                    known_piston_ids, warnings, indent
                ))

            elif stmt_type == "repeat":
                lines.append(self._compile_repeat_block(
                    stmt, piston, device_map, globals_store,
                    known_piston_ids, warnings, indent
                ))

            elif stmt_type == "for_each":
                lines.append(self._compile_for_each_block(
                    stmt, piston, device_map, globals_store,
                    known_piston_ids, warnings, indent
                ))

            elif stmt_type == "while":
                lines.append(self._compile_while_block(
                    stmt, piston, device_map, globals_store,
                    known_piston_ids, warnings, indent
                ))

            elif stmt_type == "for":
                lines.append(self._compile_for_loop(
                    stmt, piston, device_map, globals_store,
                    known_piston_ids, warnings, indent
                ))

            elif stmt_type == "set_variable":
                lines.append(self._compile_set_variable(stmt, globals_store, warnings))

            elif stmt_type == "log_message":
                lines.append(self._compile_log_message(stmt, piston["id"]))

            elif stmt_type == "call_piston":
                lines.append(self._compile_call_piston(stmt, known_piston_ids))

            elif stmt_type == "control_piston":
                lines.append(self._compile_control_piston(stmt, known_piston_ids))

            elif stmt_type == "exit":
                lines.append(self._compile_stop(stmt))

            elif stmt_type == "switch":
                lines.append(self._compile_switch_block(
                    stmt, piston, device_map, globals_store,
                    known_piston_ids, warnings, indent
                ))

            elif stmt_type == "do":
                lines.append(self._compile_do_block(
                    stmt, piston, device_map, globals_store,
                    known_piston_ids, warnings, indent
                ))

            elif stmt_type in ("break", "cancel_pending_tasks", "on_event"):
                raise CompilerError(
                    f"Statement type '{stmt_type}' requires PyScript compilation. "
                    f"This piston should have been flagged as PyScript-only before "
                    f"reaching the compiler. Check the compile_target field.",
                    code="PYSCRIPT_REQUIRED",
                    context=stmt.get("id"),
                )

            else:
                warnings.append(CompilerMessage(
                    level="warning",
                    code="UNIMPLEMENTED_STATEMENT",
                    message=(
                        f"Statement type '{stmt_type}' (statement {stmt.get('id', '?')}) "
                        f"is not yet implemented in the compiler. This statement was skipped."
                    ),
                    context=stmt.get("id"),
                ))
                continue

        # Completion event — always last in the top-level sequence only
        # (COMPILER_SPEC Section 12)
        if _append_completion_event:
            tmpl = self.env.get_template("snippets/completion_event.yaml.j2")
            lines.append(tmpl.render(
                piston_id=piston["id"],
                piston_name=piston["name"],
            ))

        return "\n\n".join(lines)

    # -----------------------------------------------------------------------
    # Section 8.1 — with_block
    # -----------------------------------------------------------------------

    def _compile_with_block(
        self, stmt: dict, device_map: dict, warnings: list
    ) -> str:
        """
        COMPILER_SPEC Section 8.1.
        Bug 7 fix: compile for ALL entities in the role, not just devices[0]/entity_ids[0].
        Single entity + single task → simple action block.
        Multiple entities or multiple tasks → parallel block, each branch with
        continue_on_error: true at both the branch and action level.
        continue_on_error: true is always emitted — matches WebCoRE fire-and-forget behavior.
        """
        # PISTON_FORMAT.md: devices is an array of role names
        devices = stmt.get("devices") or []
        target_role = devices[0] if devices else ""
        entity_ids = self._resolve_role_entities(target_role, device_map, stmt.get("id", ""))

        tasks = stmt.get("tasks", [])
        if not tasks:
            raise CompilerError(
                f"Statement {stmt.get('id', '?')} (action) has no tasks defined.",
                code="NO_TASKS",
                context=stmt.get("id"),
            )

        inner_tmpl = self.env.get_template("snippets/with_block.yaml.j2")

        # Simple case: one entity, one task → flat action block
        if len(entity_ids) == 1 and len(tasks) == 1:
            task = tasks[0]
            return inner_tmpl.render(
                stmt_id=stmt["id"],
                service=task.get("ha_service") or task.get("command", ""),
                entity_id=entity_ids[0],
                data=task.get("parameters") or None,
            )

        # Complex case: multiple entities or multiple tasks → parallel block.
        # Each branch gets continue_on_error: true at the sequence level so a
        # single offline device doesn't kill the whole parallel block.
        # COMPILER_SPEC Section 8.1 (parallel sequences note).
        branches = []
        for entity_id in entity_ids:
            for task in tasks:
                rendered = inner_tmpl.render(
                    stmt_id=None,
                    service=task.get("ha_service") or task.get("command", ""),
                    entity_id=entity_id,
                    data=task.get("parameters") or None,
                )
                branches.append(rendered)

        tmpl = self.env.get_template("snippets/parallel_block.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            branches=branches,
        ).rstrip("\n")
    # -----------------------------------------------------------------------
    # Section 8.2 — wait
    # -----------------------------------------------------------------------

    def _compile_wait(self, stmt: dict, warnings: list) -> str:
        """
        COMPILER_SPEC Section 8.2.
        wait until time → wait_for_trigger, always emits WAIT_UNTIL_PAST_TIME warning.
        wait duration   → delay block.
        """
        if "until" in stmt and stmt["until"] is not None:
            at_time = stmt["until"]
            # Always emit past-time warning — COMPILER_SPEC Section 8.2, code WAIT_UNTIL_PAST_TIME
            warnings.append(CompilerMessage(
                level="warning",
                code="WAIT_UNTIL_PAST_TIME",
                message=(
                    f"'Wait until {at_time}' will pause until that time today. "
                    f"If this step is reached after {at_time} has already passed, "
                    f"the piston will wait until {at_time} tomorrow. Structure your "
                    f"piston so this step is reached before the target time, or use "
                    f"a fixed duration delay instead."
                ),
                context=stmt.get("id"),
            ))
            # Bug 3 fix: emit timeout (default 1 hour) and continue_on_timeout
            timeout_seconds = stmt.get("timeout_seconds", 3600)
            tmpl = self.env.get_template("snippets/wait_until.yaml.j2")
            return tmpl.render(
                stmt_id=stmt["id"],
                at_time=at_time,
                timeout_seconds=timeout_seconds,
                continue_on_timeout=stmt.get("continue_on_timeout", True),
            )

        elif "duration" in stmt and stmt["duration"] is not None:
            # PISTON_FORMAT.md: duration + duration_unit fields
            # Convert to seconds for _format_delay
            duration = int(stmt["duration"])
            unit = stmt.get("duration_unit", "seconds")
            unit_map = {"seconds": 1, "s": 1, "minutes": 60, "m": 60, "hours": 3600, "h": 3600}
            seconds = duration * unit_map.get(unit, 1)
            delay_yaml = self._format_delay(seconds)
            tmpl = self.env.get_template("snippets/wait_duration.yaml.j2")
            return tmpl.render(stmt_id=stmt["id"], delay_yaml=delay_yaml)

        else:
            raise CompilerError(
                f"Statement {stmt.get('id', '?')} (wait) has neither 'until' "
                f"nor 'duration' defined.",
                code="INVALID_WAIT",
                context=stmt.get("id"),
            )

    def _format_delay(self, seconds: int) -> str:
        """COMPILER_SPEC Section 8.2 — readable delay format."""
        if seconds < 60:
            return f"seconds: {seconds}"
        elif seconds < 3600:
            return f"minutes: {seconds // 60}"
        else:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            if m:
                return f"hours: {h}\n    minutes: {m}"
            return f"hours: {h}"

    # -----------------------------------------------------------------------
    # Section 8.3 — wait_for_state
    # -----------------------------------------------------------------------

    def _compile_wait_for_state(self, stmt: dict, device_map: dict) -> str:
        """COMPILER_SPEC Section 8.3."""
        # PISTON_FORMAT.md: conditions array with standard condition objects
        conditions = stmt.get("conditions", [])
        if not conditions:
            raise CompilerError(
                f"Statement {stmt.get('id', '?')} (wait_for_state) has no conditions defined.",
                code="INVALID_WAIT_FOR_STATE",
                context=stmt.get("id"),
            )
        cond = conditions[0]
        entity_ids = self._resolve_role_entities(
            cond.get("role", ""), device_map, stmt.get("id", "")
        )
        tmpl = self.env.get_template("snippets/wait_for_state.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            entity_id=entity_ids[0],
            to_state=cond.get("compiled_value", ""),
            timeout_seconds=stmt.get("timeout_seconds", 60),
        )

    # -----------------------------------------------------------------------
    # Section 8.4 — if_block
    # -----------------------------------------------------------------------

    def _compile_if_block(
        self, stmt: dict, piston: dict, device_map: dict,
        globals_store: dict, known_piston_ids: dict,
        warnings: list, indent: int,
    ) -> str:
        """
        COMPILER_SPEC Section 8.4 — recursive.
        Routes through snippets/if_block.yaml.j2.
        Bug 4/5/8/9/10 fix: conditions compiled via _compile_single_condition
        which returns full block including "- ". is_trigger conditions filtered.
        Multiple conditions joined per condition_operator.
        GAP-S33-1 fix: else_ifs array now compiled. Each else_if compiles to an
        elif: block in HA's if/then/elif/else structure (requires HA 2023.4+,
        which is above PistonCore's 2023.1 baseline but old enough to be universal).
        """
        conditions = stmt.get("conditions", [])
        true_branch = stmt.get("then", [])
        else_ifs    = stmt.get("else_ifs", [])
        false_branch = stmt.get("else", [])

        # Bug 10 fix: filter is_trigger conditions — those are automation triggers,
        # not if-block conditions.
        non_trigger = [c for c in conditions if not c.get("is_trigger")]

        def _compile_condition_group(cond_list, cond_operator):
            """
            Compile a list of condition objects and join them per the operator.
            Returns a single compiled condition string (full block with "- ").
            Shared by main if and each else_if.
            """
            if not cond_list:
                # No conditions — always true in script context
                tmpl = self.env.get_template("snippets/condition_template.yaml.j2")
                return tmpl.render(template_expression="{{ true }}").rstrip("\n")

            compiled_parts = [
                self._compile_single_condition(c, device_map)
                for c in cond_list
            ]
            if len(compiled_parts) == 1:
                return compiled_parts[0]

            # Multiple conditions — wrap in condition:template with and/or
            tmpl = self.env.get_template("snippets/condition_template.yaml.j2")
            joiner = " and " if cond_operator == "and" else " or "
            exprs = []
            for part in compiled_parts:
                for line in part.splitlines():
                    if "value_template:" in line:
                        expr = line.split("value_template:", 1)[1].strip().strip('"')
                        exprs.append(expr)
                        break
                else:
                    exprs.append("true")
            combined = joiner.join(f"({e})" for e in exprs)
            return tmpl.render(
                template_expression=f"{{{{ {combined} }}}}"
            ).rstrip("\n")

        compiled_condition = _compile_condition_group(
            non_trigger, stmt.get("condition_operator", "and")
        )

        compiled_then = self._compile_sequence(
            true_branch, piston, device_map, globals_store,
            known_piston_ids, warnings, indent + 2,
            _append_completion_event=False,
        ) if true_branch else "[]"

        # Compile else_ifs — each produces a {compiled_condition, compiled_sequence} dict
        compiled_else_ifs = None
        if else_ifs:
            compiled_else_ifs = []
            for ei in else_ifs:
                ei_conditions = [c for c in ei.get("conditions", [])
                                 if not c.get("is_trigger")]
                ei_compiled_condition = _compile_condition_group(
                    ei_conditions, ei.get("condition_operator", "and")
                )
                ei_stmts = ei.get("statements", [])
                ei_compiled_sequence = self._compile_sequence(
                    ei_stmts, piston, device_map, globals_store,
                    known_piston_ids, warnings, indent + 2,
                    _append_completion_event=False,
                ) if ei_stmts else "[]"
                compiled_else_ifs.append({
                    "compiled_condition": ei_compiled_condition,
                    "compiled_sequence": ei_compiled_sequence,
                })

        compiled_else = None
        if false_branch:
            compiled_else = self._compile_sequence(
                false_branch, piston, device_map, globals_store,
                known_piston_ids, warnings, indent + 2,
                _append_completion_event=False,
            )

        tmpl = self.env.get_template("snippets/if_block.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            compiled_condition=compiled_condition,
            compiled_then=compiled_then,
            compiled_else_ifs=compiled_else_ifs,
            compiled_else=compiled_else,
        ).rstrip("\n")

    # -----------------------------------------------------------------------
    # Section 8.6 — repeat_block (repeat/do/until)
    # -----------------------------------------------------------------------

    def _compile_repeat_block(
        self, stmt: dict, piston: dict, device_map: dict,
        globals_store: dict, known_piston_ids: dict,
        warnings: list, indent: int,
    ) -> str:
        """
        COMPILER_SPEC Section 8.6 — repeat/do/until.
        Routes through snippets/repeat_until.yaml.j2.
        """
        until_conditions = stmt.get("until_conditions", [])
        body = stmt.get("statements", [])

        condition = until_conditions[0] if until_conditions else {}
        # _compile_single_condition returns full block including "- "
        compiled_until_condition = self._compile_single_condition(condition, device_map)
        compiled_sequence = self._compile_sequence(
            body, piston, device_map, globals_store,
            known_piston_ids, warnings, indent + 2,
            _append_completion_event=False,
        )

        tmpl = self.env.get_template("snippets/repeat_until.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            compiled_sequence=compiled_sequence,
            compiled_until_condition=compiled_until_condition,
        ).rstrip("\n")

    # -----------------------------------------------------------------------
    # Section 8.7 — for_each_block
    # -----------------------------------------------------------------------

    def _compile_for_each_block(
        self, stmt: dict, piston: dict, device_map: dict,
        globals_store: dict, known_piston_ids: dict,
        warnings: list, indent: int,
    ) -> str:
        """
        COMPILER_SPEC Section 8.7.
        Bug 6 fix: body actions targeting the loop role must use {{ repeat.item }}
        as the entity_id at runtime. Compile the body with a sentinel device_map
        entry for the loop role that maps to {{ repeat.item }}, so action
        compilation resolves correctly. Text substitution on compiled output is
        unreliable — instead we inject the sentinel before compiling the body.
        """
        # PISTON_FORMAT.md: list_role, variable, statements
        collection_role = stmt.get("list_role", "")
        body = stmt.get("statements", [])

        entity_ids = self._resolve_collection(collection_role, device_map)

        # Bug 6 fix: override device_map for body compilation so the loop role
        # resolves to the repeat.item sentinel, not a baked entity_id list.
        body_device_map = dict(device_map)
        body_device_map[collection_role] = ["{{ repeat.item }}"]

        compiled_sequence = self._compile_sequence(
            body, piston, body_device_map, globals_store,
            known_piston_ids, warnings, indent + 2,
            _append_completion_event=False,
        )

        tmpl = self.env.get_template("snippets/for_each.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            entity_ids=entity_ids,
            compiled_sequence=compiled_sequence,
        ).rstrip("\n")

    def _resolve_collection(self, role: str, device_map: dict) -> list[str]:
        """
        Resolve a Devices role to a literal list of entity IDs.
        COMPILER_SPEC Section 8.7.
        """
        value = device_map.get(role)
        if value is None:
            raise CompilerError(
                f"for_each references role '{role}' but no device collection "
                f"is mapped to that role.",
                code="UNMAPPED_ROLE",
            )
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [value]
        raise CompilerError(
            f"Role '{role}' resolved to an unexpected value type. "
            f"Expected a list of entity IDs.",
            code="UNMAPPED_ROLE",
        )

    # -----------------------------------------------------------------------
    # Section 8.8 — while_block
    # -----------------------------------------------------------------------

    def _compile_while_block(
        self, stmt: dict, piston: dict, device_map: dict,
        globals_store: dict, known_piston_ids: dict,
        warnings: list, indent: int,
    ) -> str:
        """
        COMPILER_SPEC Section 8.8.
        Routes through snippets/while_loop.yaml.j2.
        """
        conditions = stmt.get("conditions", [])
        body = stmt.get("statements", [])

        condition = conditions[0] if conditions else {}
        compiled_condition = self._compile_single_condition(condition, device_map)
        compiled_sequence = self._compile_sequence(
            body, piston, device_map, globals_store,
            known_piston_ids, warnings, indent + 2,
            _append_completion_event=False,
        )

        tmpl = self.env.get_template("snippets/while_loop.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            compiled_condition=compiled_condition,
            compiled_sequence=compiled_sequence,
        ).rstrip("\n")

    # -----------------------------------------------------------------------
    # Section 8.9 — for_loop (counted loop)
    # -----------------------------------------------------------------------

    def _compile_for_loop(
        self, stmt: dict, piston: dict, device_map: dict,
        globals_store: dict, known_piston_ids: dict,
        warnings: list, indent: int,
    ) -> str:
        """
        COMPILER_SPEC Section 8.9.
        Simple (from 0 or 1, step 1) → repeat count: directly.
        Complex (other from/step) → variables: block at top of sequence.
        """
        # PISTON_FORMAT.md: start, end, step, counter_variable, statements
        from_val = stmt.get("start", 1)
        to_expr = stmt.get("end", "10")
        step = stmt.get("step", 1)
        var_name = stmt.get("counter_variable", "$i").lstrip("$")
        body = stmt.get("statements", [])

        compiled_body = self._compile_sequence(
            body, piston, device_map, globals_store,
            known_piston_ids, warnings, indent + 2,
            _append_completion_event=False,
        )

        simple = (from_val in (0, 1)) and (step == 1)
        simple = (from_val in (0, 1)) and (step == 1)

        # Bug 16 fix: use repeat.index/index0 for simple loops
        if simple:
            repeat_ref = "repeat.index0" if from_val == 0 else "repeat.index"
            compiled_body = compiled_body.replace(
                f"{{{{ {var_name} }}}}", f"{{{{ {repeat_ref} }}}}"
            )

        tmpl = self.env.get_template("snippets/for_loop.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            count=to_expr,
            compiled_sequence=compiled_body,
            has_variables=not simple,
            var_name=var_name,
            from_val=from_val,
            step=step,
        ).rstrip("\n")
    # -----------------------------------------------------------------------
    # Section 8.9 — set_variable
    # -----------------------------------------------------------------------

    def _compile_set_variable(
        self, stmt: dict, globals_store: dict, warnings: list
    ) -> str:
        """
        COMPILER_SPEC Section 8.9.
        Local variables  → HA variables: action.
        Global variables (@) → HA helper service calls (input_text, input_number,
                               input_boolean, input_datetime depending on type).
        globals_store maps global variable names to their definitions:
            { "away_mode": { "display_name": "Away Mode", "type": "Yes/No",
                             "helper_entity_id": "input_boolean.pistoncore_away_mode" } }
        """
        # PISTON_FORMAT.md: variable is the name string, value is an operand object
        var_name_raw = stmt.get("variable", "")

        if var_name_raw.startswith("@"):
            var_name = var_name_raw.lstrip("@")
            # Resolve the value operand
            value_obj = stmt.get("value", {})
            value_expr = self._resolve_operand(value_obj)

            global_def = globals_store.get(var_name, {})
            helper_entity = global_def.get("helper_entity_id", "")
            global_type = global_def.get("type", "Text")

            if not helper_entity:
                warnings.append(CompilerMessage(
                    level="warning",
                    code="UNRESOLVED_GLOBAL",
                    message=(
                        f"Global variable '{var_name_raw}' is referenced in statement "
                        f"{stmt.get('id', '?')} but has no helper entity ID in globals_store. "
                        f"Define this global in PistonCore and redeploy."
                    ),
                    context=stmt.get("id"),
                ))
                # Emit a safe no-op — valid YAML comment block via set_variable template
                tmpl = self.env.get_template("snippets/set_variable.yaml.j2")
                return tmpl.render(
                    stmt_id=stmt["id"],
                    var_name=f"_unresolved_global_{var_name}",
                    value=f'"UNRESOLVED: {var_name_raw} — define this global and redeploy"',
                ).rstrip("\n")

            # Choose the correct HA service and field name by helper type
            type_map = {
                "Text":      ("input_text.set_value",     "value"),
                "Number":    ("input_number.set_value",   "value"),
                "Yes/No":    (None,                       None),    # special — see below
                "Date/Time": ("input_datetime.set_datetime", "datetime"),
            }
            service, field = type_map.get(global_type, ("input_text.set_value", "value"))

            if global_type == "Yes/No":
                if "{{" in str(value_expr):
                    val_template = value_expr
                elif str(value_expr).lower() in ("true", "yes", "on", "1"):
                    val_template = "true"
                else:
                    val_template = value_expr
                tmpl = self.env.get_template("snippets/set_global_boolean.yaml.j2")
                return tmpl.render(
                    stmt_id=stmt["id"],
                    val_template=val_template,
                    helper_entity_id=helper_entity,
                ).rstrip("\n")

            if "{{" in str(value_expr):
                formatted_value = f'"{value_expr}"'
            elif isinstance(value_expr, str):
                formatted_value = f'"{value_expr}"'
            else:
                formatted_value = value_expr

            tmpl = self.env.get_template("snippets/set_global.yaml.j2")
            return tmpl.render(
                stmt_id=stmt["id"],
                service=service,
                helper_entity_id=helper_entity,
                field=field,
                value=formatted_value,
            ).rstrip("\n")

        # Piston variable ($ prefix or bare name)
        var_name = var_name_raw.lstrip("$")
        value_obj = stmt.get("value", {})
        value_expr = self._resolve_operand(value_obj)

        if "{{" in str(value_expr):
            value = value_expr
        elif isinstance(value_expr, str):
            value = f'"{value_expr}"'
        else:
            value = value_expr

        tmpl = self.env.get_template("snippets/set_variable.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            var_name=var_name,
            value=value,
        ).rstrip("\n")

    # -----------------------------------------------------------------------
    # Operand resolver — PISTON_FORMAT.md Operand/Value Schema
    # -----------------------------------------------------------------------

    def _resolve_operand(self, value_obj: Any) -> Any:
        """
        Resolve a PISTON_FORMAT.md operand object to a Python value or Jinja2 expression.
        Handles: literal, variable, global_variable, system_variable, expression.
        """
        if not isinstance(value_obj, dict):
            # Raw value (legacy or bare string/number)
            return value_obj

        vtype = value_obj.get("type", "literal")

        if vtype == "literal":
            return value_obj.get("data", "")

        if vtype == "variable":
            name = value_obj.get("name", "").lstrip("$")
            return f"{{{{ {name} }}}}"

        if vtype == "global_variable":
            name = value_obj.get("name", "").lstrip("@")
            # Will be resolved to helper entity at runtime — emit as template
            return f"{{{{ states('input_text.pistoncore_{name}') }}}}"

        if vtype == "system_variable":
            # Bug 17 fix: $sunrise/$sunset must use as_datetime() so offset
            # arithmetic works — state_attr returns a string, not a datetime object.
            sys_map = {
                "$now": "now()",
                "$sunrise": "as_datetime(state_attr('sun.sun', 'next_rising'))",
                "$sunset": "as_datetime(state_attr('sun.sun', 'next_setting'))",
                "$hour": "now().hour",
                "$minute": "now().minute",
                "$second": "now().second",
                "$index": "repeat.index",
                "$weekday": "now().isoweekday()",
            }
            name = value_obj.get("name", "")

            # Bug 18 fix: $currentEventDevice is context-dependent.
            # In a native automation triggered by a state trigger → trigger.entity_id.
            # Outside that context → CompilerError (cannot resolve safely).
            if name == "$currentEventDevice":
                # Native compile: HA provides trigger.entity_id for state triggers.
                # This is correct for state-triggered automations. For other trigger
                # types it will be unavailable — emit a warning but compile anyway.
                expr = "trigger.entity_id"
            else:
                expr = sys_map.get(name, name.lstrip("$"))

            offset = value_obj.get("offset", 0)
            if offset:
                unit = value_obj.get("offset_unit", "minutes")
                direction = value_obj.get("offset_direction", "+")
                offset_map = {
                    "minutes": "timedelta(minutes=",
                    "hours": "timedelta(hours=",
                    "seconds": "timedelta(seconds=",
                }
                td = offset_map.get(unit, "timedelta(minutes=")
                return f"{{{{ {expr} {direction} {td}{offset}) }}}}"
            return f"{{{{ {expr} }}}}"

        if vtype == "expression":
            return value_obj.get("expression", "")

        return value_obj.get("data", "")

    # -----------------------------------------------------------------------


    def _compile_log_message(self, stmt: dict, piston_id: str) -> str:
        """COMPILER_SPEC Section 8.12."""
        tmpl = self.env.get_template("snippets/log_message.yaml.j2")
        # PISTON_FORMAT.md: message is an operand object
        message_obj = stmt.get("message", {})
        message = self._resolve_operand(message_obj) if isinstance(message_obj, dict) else str(message_obj)
        return tmpl.render(
            stmt_id=stmt["id"],
            piston_id=piston_id,
            level=stmt.get("level", "info"),
            message=message,
        )

    # -----------------------------------------------------------------------
    # Section 8.13 — call_piston
    # -----------------------------------------------------------------------

    def _compile_call_piston(self, stmt: dict, known_piston_ids: dict) -> str:
        """
        COMPILER_SPEC Section 8.13.
        Bug 13 fix: script entity ID uses piston UUID, not slug.
        Format: script.pistoncore_{target_piston_id}
        """
        target_id = stmt.get("target_piston_id", "")
        if not target_id or target_id not in known_piston_ids:
            raise CompilerError(
                f"Statement {stmt.get('id', '?')} calls piston '{target_id}' "
                f"but that piston was not found. It may have been deleted.",
                code="CALLED_PISTON_NOT_FOUND",
                context=stmt.get("id"),
            )

        tmpl = self.env.get_template("snippets/call_piston.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            target_id=target_id,
            wait_for_completion=stmt.get("wait_for_completion", False),
        ).rstrip("\n")

    # -----------------------------------------------------------------------
    # Section 8.14 — control_piston
    # -----------------------------------------------------------------------

    def _compile_control_piston(self, stmt: dict, known_piston_ids: dict) -> str:
        """
        COMPILER_SPEC Section 8.14.
        Bug 13 fix: uses piston UUID for entity ID, not slug.
        """
        target_type = stmt.get("target_type", "piston")
        action = stmt.get("action", "trigger")

        if target_type == "piston":
            target_id = stmt.get("target_id", "")
            if not target_id or target_id not in known_piston_ids:
                raise CompilerError(
                    f"Statement {stmt.get('id', '?')} controls piston '{target_id}' "
                    f"but that piston was not found.",
                    code="CALLED_PISTON_NOT_FOUND",
                    context=stmt.get("id"),
                )
            entity_id = f"script.pistoncore_{target_id}"
            service_map = {
                "trigger": "script.turn_on",
                "start":   "script.turn_on",
                "stop":    "script.turn_off",
                "enable":  "script.turn_on",
                "disable": "script.turn_off",
            }
        else:
            entity_id = stmt.get("target_id", "")
            service_map = {
                "trigger": "automation.trigger",
                "start":   "automation.turn_on",
                "stop":    "automation.turn_off",
                "enable":  "automation.turn_on",
                "disable": "automation.turn_off",
            }

        service = service_map.get(action, "script.turn_on")
        tmpl = self.env.get_template("snippets/control_piston.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            service=service,
            entity_id=entity_id,
        ).rstrip("\n")

    # -----------------------------------------------------------------------
    # Section 8.15 — stop
    # -----------------------------------------------------------------------

    def _compile_stop(self, stmt: dict) -> str:
        """COMPILER_SPEC Section 8.15."""
        tmpl = self.env.get_template("snippets/stop.yaml.j2")
        return tmpl.render(stmt_id=stmt["id"])

    # -----------------------------------------------------------------------
    # Section 8.10 — switch_block
    # -----------------------------------------------------------------------

    def _compile_switch_block(
        self, stmt: dict, piston: dict, device_map: dict,
        globals_store: dict, known_piston_ids: dict,
        warnings: list, indent: int,
    ) -> str:
        """COMPILER_SPEC Section 8.10 — compiles to HA choose:"""
        # PISTON_FORMAT.md: expression object, cases array (with statements), default array
        expression = stmt.get("expression", {})
        cases = stmt.get("cases", [])
        default_stmts = stmt.get("default", [])

        # Resolve expression to entity_id for state comparison if it's a device role
        entity_id = ""
        if expression.get("type") == "variable":
            # Variable expression — will be used in template
            var_name = expression.get("name", "").lstrip("$@")
        else:
            var_name = ""

        # Build case list for template
        compiled_cases = []
        for case in cases:
            case_val = case.get("value", "")
            if var_name:
                condition_expr = f"{{{{ {var_name} == {repr(case_val)} }}}}"
            else:
                condition_expr = "{{ false }}"
            compiled_seq = self._compile_sequence(
                case.get("statements", []), piston, device_map, globals_store,
                known_piston_ids, warnings, indent + 2,
                _append_completion_event=False,
            )
            compiled_cases.append({
                "condition_expr": condition_expr,
                "compiled_sequence": compiled_seq,
            })

        compiled_default = None
        if default_stmts:
            compiled_default = self._compile_sequence(
                default_stmts, piston, device_map, globals_store,
                known_piston_ids, warnings, indent + 2,
                _append_completion_event=False,
            )

        tmpl = self.env.get_template("snippets/switch_block.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            cases=compiled_cases,
            compiled_default=compiled_default,
        ).rstrip("\n")

    # -----------------------------------------------------------------------
    # Section 8.11 — do_block
    # -----------------------------------------------------------------------

    def _compile_do_block(
        self, stmt: dict, piston: dict, device_map: dict,
        globals_store: dict, known_piston_ids: dict,
        warnings: list, indent: int,
    ) -> str:
        """COMPILER_SPEC Section 8.11 — inline comment + body."""
        # PISTON_FORMAT.md: description field, statements array
        label = stmt.get("description", "") or ""
        body = stmt.get("statements", [])
        compiled_sequence = self._compile_sequence(
            body, piston, device_map, globals_store,
            known_piston_ids, warnings, indent,
            _append_completion_event=False,
        )
        tmpl = self.env.get_template("snippets/do_block.yaml.j2")
        return tmpl.render(
            stmt_id=stmt["id"],
            compiled_sequence=compiled_sequence,
            label=label or None,
        ).rstrip("\n")

    # -----------------------------------------------------------------------
    # Section 6 + 7 — Automation and script rendering
    # -----------------------------------------------------------------------

    def _compute_content_hash(self, content: str) -> str:
        """
        Hash the content below the header block only.
        The header ends at the first blank line after the opening comment block.
        This matches COMPILER_SPEC Section 5 — the hash covers the compiled
        YAML body, not the comment header that contains the hash itself.
        """
        # Split into lines; skip lines that are part of the comment header
        # (lines starting with '#' or blank lines before real YAML begins).
        lines = content.splitlines()
        body_start = 0
        in_header = True
        for i, line in enumerate(lines):
            stripped = line.strip()
            if in_header and (stripped.startswith("#") or stripped == ""):
                body_start = i + 1
            else:
                in_header = False
                break
        body = "\n".join(lines[body_start:])
        return hashlib.sha256(body.encode()).hexdigest()

    def _render_automation(
        self,
        piston: dict,
        slug: str,
        compiled_triggers: str,
        compiled_conditions: str,
        app_version: str,
    ) -> str:
        """
        Render the automation wrapper file using automation.yaml.j2.
        Hash covers only the YAML body below the comment header.
        COMPILER_SPEC Section 9 (Bug 14 fix).

        Template variable guide:
          piston_id — piston UUID. Used for: automation id:, action script entity_id,
                      filename (pistoncore_{piston_id}.yaml). NEVER use slug here.
          slug      — name-derived slug. Used ONLY for alias: (human label in HA UI).
          piston    — full piston dict (piston.name, piston.description, piston.mode etc.)
        """
        tmpl = self.env.get_template("automation.yaml.j2")
        content = tmpl.render(
            piston=piston,
            piston_id=piston["id"],
            slug=slug,
            compiled_triggers=compiled_triggers,
            compiled_conditions=compiled_conditions,
            app_version=app_version,
            hash="PLACEHOLDER",
        )
        content_hash = self._compute_content_hash(content)
        return content.replace("PLACEHOLDER", content_hash)

    def _render_script(
        self,
        piston: dict,
        slug: str,
        compiled_sequence: str,
        globals_used: list,
        app_version: str,
    ) -> str:
        """
        Render the script body file using script.yaml.j2.
        Hash covers only the YAML body below the comment header.
        COMPILER_SPEC Section 10 (Bug 14 fix).

        Template variable guide:
          piston_id — piston UUID. Used for: script key name (pistoncore_{piston_id}:),
                      filename (pistoncore_{piston_id}.yaml). NEVER use slug here.
          slug      — name-derived slug. Used ONLY for alias: (human label in HA UI).
          piston    — full piston dict.
        """
        globals_str = ", ".join(globals_used) if globals_used != ["(none)"] else "(none)"
        tmpl = self.env.get_template("script.yaml.j2")
        content = tmpl.render(
            piston=piston,
            piston_id=piston["id"],
            slug=slug,
            compiled_sequence=compiled_sequence,
            globals_used=globals_str,
            app_version=app_version,
            hash="PLACEHOLDER",
        )
        content_hash = self._compute_content_hash(content)
        return content.replace("PLACEHOLDER", content_hash)


# ---------------------------------------------------------------------------
# Quick test — run with:
#   cd backend
#   PISTONCORE_TEMPLATE_DIR=../pistoncore-customize/compiler-templates/native-script/ python compiler.py
# Uses the driveway lights piston from COMPILER_SPEC Section 17.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os, sys

    template_dir = os.environ.get(
        "PISTONCORE_TEMPLATE_DIR",
        "/pistoncore-customize/compiler-templates/native-script/"
    )

    test_piston = {
        "id": "a3f8c2d1",
        "name": "Driveway Lights at Sunset",
        "description": "Turns on driveway lights at sunset and off at 11pm",
        "mode": "single",
        "compile_target": "native_script",
        "device_map": {
            "driveway_light": ["light.driveway_main"]
        },
        "variables": [],
        "conditions": [],
        # Nested tree format — PISTON_FORMAT.md v2.0.
        # Children are embedded statement objects, not ID strings.
        "statements": [
            {
                "id": "stmt_001",
                "type": "if",
                "conditions": [
                    {
                        "id": "cond_001",
                        "is_trigger": True,
                        "subject": "time",
                        "operator": "happens daily at",
                        "value": {"preset": "sunset", "offset": 0,
                                  "offset_unit": "minutes", "offset_direction": "+"},
                    }
                ],
                "condition_operator": "and",
                "then": [
                    {
                        "id": "stmt_002",
                        "type": "action",
                        "devices": ["driveway_light"],
                        "tasks": [{"id": "task_001", "command": "turn_on", "domain": "light",
                                    "ha_service": "light.turn_on",
                                    "parameters": {"brightness_pct": 100}}],
                        "description": None, "disabled": False,
                    },
                    {
                        "id": "stmt_003",
                        "type": "wait",
                        "wait_type": "until",
                        "until": "23:00:00",
                        "description": None, "disabled": False,
                    },
                    {
                        "id": "stmt_004",
                        "type": "action",
                        "devices": ["driveway_light"],
                        "tasks": [{"id": "task_002", "command": "turn_off", "domain": "light",
                                    "ha_service": "light.turn_off", "parameters": {}}],
                        "description": None, "disabled": False,
                    },
                ],
                "else_ifs": [],
                "else": [],
                "description": None,
                "disabled": False,
            },
        ],
    }

    # Fat compiler context — COMPILER_SPEC Section 7
    test_context = {
        "piston": test_piston,
        "global_variables": [],
        "known_piston_ids": {},
        "pistoncore_version": "0.9",
        "entity_states": {},
        "ha_version": "unknown",
    }

    try:
        compiler = Compiler(template_dir=template_dir)
        result = compiler.compile_piston(test_context)

        if result.errors:
            print("ERRORS:")
            for e in result.errors:
                print(f"  [{e.code}] {e.message}")
            sys.exit(1)

        if result.warnings:
            print("WARNINGS:")
            for w in result.warnings:
                print(f"  ⚠  [{w.code}] {w.message}")

        print("=== AUTOMATION FILE ===")
        print(result.automation_yaml)
        print("\n=== SCRIPT FILE ===")
        print(result.script_yaml)
        print("\nCompiler ran successfully.")

    except Exception as e:
        print(f"Unexpected error: {e}")
        raise
