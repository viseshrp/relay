from relay.config import PHASE_TYPES, default_phase_model_mapping


def test_default_phase_model_mapping_covers_all_phases() -> None:
    mapping = default_phase_model_mapping()
    assert set(mapping) == set(PHASE_TYPES)
    assert all(value == "" for value in mapping.values())
