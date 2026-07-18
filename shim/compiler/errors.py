"""Compiler errors — one canonical record shape (COMPILER_DECISIONS_HOLDING §A3).

Every error names the piston and statement it came from; announced on the two
UI surfaces only (front-door indicator + piston status banner). The
machine-readable fields exist for the drill-in help screen and future
AI-assisted template fixing (the "check HA updates" pointer)."""


class CompilerError(Exception):
    code = "COMPILE_ERROR"

    def __init__(self, message: str, piston_id: str = "", piston_name: str = "",
                 stmt_id: int | None = None, ha_domain: str = ""):
        super().__init__(message)
        self.message = message
        self.piston_id = piston_id
        self.piston_name = piston_name
        self.stmt_id = stmt_id
        self.ha_domain = ha_domain

    def record(self) -> dict:
        return {"code": self.code, "message": self.message,
                "piston_id": self.piston_id, "piston_name": self.piston_name,
                "stmt_id": self.stmt_id, "ha_domain": self.ha_domain}


class NotYetImplemented(CompilerError):
    """Construct is implementable (make-it-work rule) but not built yet —
    scheduled work, not a cut. Names the construct so the piston status banner
    is specific."""
    code = "NOT_YET_IMPLEMENTED"


class UnresolvableDevice(CompilerError):
    """Hash/name with no resolution-map entry (A2/A7): a trigger on a
    nonexistent entity silently never fires, so this is a hard error."""
    code = "UNRESOLVABLE_DEVICE"
