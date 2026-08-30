## ADDED Requirements

### Requirement: Graphs can reference a durable plugin-managed audio source
The system SHALL model a plugin-managed source instance as an audio-producing endpoint role with a
stable provider and instance reference, declared signal contract, and typed activity facts. Saved
graphs SHALL NOT contain the source's transient process or PipeWire object identifiers.

#### Scenario: User adds a librespot source
- **WHEN** an installed enabled librespot plugin exposes one or more instances
- **THEN** the graph editor offers a typed Spotify source whose instance field uses a labelled instance selector rather than JSON

#### Scenario: Referenced plugin is disabled
- **WHEN** a saved graph references a librespot instance whose plugin is disabled or removed
- **THEN** the graph remains loadable and editable, preserves the stable reference, and marks the source unavailable

#### Scenario: Instance stream restarts
- **WHEN** the referenced instance recreates its PipeWire stream with new runtime IDs
- **THEN** the desired graph remains unchanged and subsequent resolution uses the newly correlated candidate

