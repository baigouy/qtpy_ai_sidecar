"""Strength-only chat templates (Muse-Glimmer) cannot switch reasoning off."""
from qtpy_ai_sidecar.backend import apply_reasoning_strength
from qtpy_ai_sidecar.config import Config
from qtpy_ai_sidecar.runtime import reasoning_control


def test_template_classification():
    assert reasoning_control('{% if enable_thinking %}<think>{% endif %}') == 'toggle'
    assert reasoning_control("{% set reasoning_strength = 'high' %}Reasoning strength: ") == 'strength'
    assert reasoning_control('{{ messages }}') is None


def config(**kw):
    return Config(thinking_backend='llama_cpp', **kw)


def test_off_becomes_low_with_a_notice():
    events = []
    transport = [{'role': 'system', 'content': 'Rules.'}, {'role': 'user', 'content': 'hi'}]
    apply_reasoning_strength(transport, config(thinking='disabled'), False, lambda *e: events.append(e))
    assert transport[0]['content'].endswith('Reasoning strength: low.')
    assert events and 'cannot switch reasoning off' in events[0][1]


def test_strength_goes_into_the_system_line_and_default_sends_nothing():
    transport = [{'role': 'user', 'content': 'hi'}]
    apply_reasoning_strength(transport, config(thinking_strength='medium'), False, lambda *e: None)
    assert transport[0] == {'role': 'system', 'content': 'Reasoning strength: medium.'}
    transport = [{'role': 'user', 'content': 'hi'}]
    apply_reasoning_strength(transport, config(), False, lambda *e: None)
    assert len(transport) == 1


def test_text_only_recovery_uses_low():
    transport = [{'role': 'system', 'content': 'Rules.'}]
    apply_reasoning_strength(transport, config(thinking_strength='high'), True, lambda *e: None)
    assert transport[0]['content'].endswith('Reasoning strength: low.')
