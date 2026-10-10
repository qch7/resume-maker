CREATE TABLE IF NOT EXISTS record_references (
 namespace TEXT NOT NULL, identifier TEXT NOT NULL, owner TEXT NOT NULL,
 value_json TEXT NOT NULL, PRIMARY KEY(namespace, identifier)
);
CREATE TABLE IF NOT EXISTS record_operations (
 id TEXT PRIMARY KEY, namespace TEXT NOT NULL, identifiers_json TEXT NOT NULL,
 phase TEXT NOT NULL, blockers_json TEXT NOT NULL DEFAULT '[]'
);
