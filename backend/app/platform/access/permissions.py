"""The permission catalogue: code is the source of truth, the table mirrors it.

Migration 0002 seeds the codes that existed then; `ensure_catalogue_seeded` syncs any
added later, so a new permission needs no migration.
"""

PERMISSIONS: dict[str, str] = {
    "user:invite": "Invite people and manage their invitations",
    "user:read": "See the list of users",
    "user:manage": "Deactivate users and end their sessions",
    "role:grant": "Grant and revoke roles in a company",
    "role:manage": "Change what a role may do",
    "audit:read": "Read a company's audit log",
    "account:read": "See the chart of accounts",
    "account:manage": "Create, change and archive accounts and company defaults",
    "journal:read": "See the journals",
    "journal:manage": "Create, change and archive journals",
    "rate:read": "See exchange rates",
    "rate:manage": "Enter and import exchange rates",
    "chart:load": "Load a ready-made chart of accounts",
}

CODES = frozenset(PERMISSIONS)
