from __future__ import annotations

__all__ = [
    "AudioService",
    "GlossaryService",
    "JobService",
    "JobTracker",
    "PipelineService",
    "ProviderService",
    "QAService",
]


def __getattr__(name: str):
    if name == "AudioService":
        from app.mobile_api.services.audio_service import AudioService

        return AudioService
    if name == "GlossaryService":
        from app.mobile_api.services.glossary_service import GlossaryService

        return GlossaryService
    if name in {"JobService", "JobTracker"}:
        from app.mobile_api.services.job_service import JobService, JobTracker

        return {"JobService": JobService, "JobTracker": JobTracker}[name]
    if name == "PipelineService":
        from app.mobile_api.services.pipeline_service import PipelineService

        return PipelineService
    if name == "ProviderService":
        from app.mobile_api.services.provider_service import ProviderService

        return ProviderService
    if name == "QAService":
        from app.mobile_api.services.qa_service import QAService

        return QAService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
