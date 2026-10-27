# Tests

These guard bugs that each caused **silent data loss or silent wrong answers** on a
real bench. None of them raised an error when they happened — that is why they are
tested rather than trusted.

| file | guards |
|---|---|
| `test_mutation_queue.py` | Concurrent `create_device` / `remove_device` losing devices. Six concurrent creates once produced **one** device and reported success. Also checks a burst still collapses to a single config-entry reload. |
| `test_file_safety.py` | A failed save destroying the existing device file. The savers used to open the real file in `'w'` (truncating it) and only then serialize, swallowing failures at debug level — one unserialisable value emptied the file and the integration stopped loading. |
| `test_capability_capture.py` | A clone dropping abilities. The capture list is checked **against Home Assistant's own `capability_attributes`**, so a new HA capability shows up as a failure instead of being silently missed. Also checks every capturable key is declared by its platform's schema, and that nothing but primitives reaches the yaml. |
| `test_notifier_clone.py` | A cloned device getting nowhere for a push or a text to land: the push/text label, the UI-only `add_notifier`, the automatic push notifier for a companion-app phone, and the controls (an ordinary device gets nothing). |
| `test_explicit_ids.py` | Stand-ins losing the identity they were given: an entry naming its own `entity_id` keeps it, its unique id is derived (never random), devices carry their own details, and entries that name no id still behave exactly as before. |
| `test_orphans.py` | Removing one entity taking its whole device with it. Entities are removed one row at a time; a device goes only when the file no longer lists it, and nothing is removed at all on a file that could not be read. |
| `test_export.py` | The export: lock and alarm codes and text passwords never reach the file, every skip is accounted for, every entry is checked against its platform's own schema, and the written file loads back with the same entity ids. |
| `test_select_text.py` | The `select` and `text` platforms: a value off a menu, or one that breaks the limits Home Assistant itself enforces, must not leave an entity that errors when read. |
| `test_version.py` | The version drifting: there is one, and it is the manifest's. |

## Running them

They need a real Home Assistant, because the behaviour under test lives in the
seam between this integration and HA's own enums and yaml handling. The simplest
way to get one is the HA container:

```bash
docker run -d --name ha-test -p 8124:8123 \
  -v "$PWD/ha-config:/config" ghcr.io/home-assistant/home-assistant:stable

# put the integration and the tests where HA can import them
docker cp custom_components ha-test:/config/custom_components
docker cp tests             ha-test:/config/tests

docker exec ha-test python -m pytest /config/tests -q
```

Expect `186 passed`. There is no `pytest-asyncio` dependency — async cases call
`asyncio.run` directly, so HA and pytest are all you need.

## If you change the capture list

`CLONE_ATTRS` in `clone.py` and the platform schemas are **one contract**: the
platforms validate against closed schemas, so a key a platform does not declare
fails entity creation outright. Change both together, or
`test_every_capturable_key_is_declared_by_its_platform` will tell you.

## Keeping the suite honest

A test that cannot fail is worse than no test. After changing these, break the
thing on purpose and confirm the suite notices — that is how the first version of
this suite was found to be testing nothing at all (the tamper never applied, so
everything "passed"). Known-good result:

| break | failures |
|---|---|
| remove a key from `CLONE_ATTRS` | 4 |
| restore the truncate-before-serialize save | 2 |
| remove the lock in `_mutate_and_reload` | 4 |
