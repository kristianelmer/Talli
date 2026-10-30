"""Explicit historical workflow fixture for unchanged V1 HTTP contract regressions.

These tests own V1 storage/admission doubles. They do not prove the default
composition; test_rf1086_default_source_http exercises the actual V2/V3 factory.
Keep the historical workflow assertions without making production downgrade to
those ports or teaching V1 doubles to manufacture V2 proof.
"""
from types import SimpleNamespace
from unittest.mock import patch

from talli_backend import main
from talli_backend.application.shareholder_register_source_workflow import ShareholderRegisterSourceWorkflow
from talli_backend.application.shareholder_register_source_approval import ShareholderRegisterSourceApprovalWorkflow


def create_legacy_source_app(**dependencies):
    workflows = []

    def source_workflow(*args):
        workflow = ShareholderRegisterSourceWorkflow(*args)
        workflows.append(workflow)
        return workflow

    class Preview:
        def __init__(self, *args):
            self._workflow = workflows[-1]

        async def generate(self, *args, **kwargs):
            return SimpleNamespace(preview=await self._workflow.generate_source_preview(*args, **kwargs))

        async def read(self, *args, **kwargs):
            return await self._workflow.read_source_preview(*args, **kwargs)

    class Approval:
        def __init__(self, *args):
            self._workflow = ShareholderRegisterSourceApprovalWorkflow(*args)

        async def read_review(self, *args, **kwargs):
            return SimpleNamespace(review=await self._workflow.read_review(*args, **kwargs))

        async def approve(self, *args, **kwargs):
            return await self._workflow.approve(*args, **kwargs)

    with patch.multiple(main,
            ShareholderRegisterSourceWorkflow=source_workflow,
            ShareholderRegisterSourceCaptureV2=lambda *args: workflows[-1],
            ShareholderRegisterSourcePreviewV2=Preview,
            ShareholderRegisterSourceApprovalV3=Approval):
        return main.create_app(**dependencies)
