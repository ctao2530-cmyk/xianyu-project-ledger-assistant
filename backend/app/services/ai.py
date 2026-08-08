"""Compatibility exports for integrations importing the original module."""

from ..ai import GeneratedDraft, OpenAICompatibleProvider

AIService = OpenAICompatibleProvider

__all__ = ["AIService", "GeneratedDraft"]
