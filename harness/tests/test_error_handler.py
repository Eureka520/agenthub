"""Tests for error handler."""

import pytest
from harness.error_handler import ErrorHandler


@pytest.fixture
def handler():
    return ErrorHandler()


def test_l1_pip_timeout(handler):
    match = handler.classify("pip install timed out after 30s")
    assert match.level == "L1"
    assert match.solution == "switch_proxy"


def test_l1_missing_module(handler):
    match = handler.classify("ModuleNotFoundError: No module named 'torch'")
    assert match.level == "L1"


def test_l2_oom(handler):
    match = handler.classify("RuntimeError: CUDA out of memory")
    assert match.level == "L2"
    assert match.solution == "reduce_gpu_memory_utilization"


def test_l3_segfault(handler):
    match = handler.classify("Segmentation fault (core dumped)")
    assert match.level == "L3"
    assert match.solution is None


def test_l3_unknown(handler):
    match = handler.classify("some completely unknown error xyz")
    assert match.level == "L3"
    assert match.solution is None


def test_acceptance_failed(handler):
    match = handler.classify("ACCEPTANCE_FAILED: metric images_processed=1200 < 1355")
    assert match.level == "L2"
    assert match.solution == "rerun_stage"
