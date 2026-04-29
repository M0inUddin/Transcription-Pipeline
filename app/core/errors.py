class PipelineError(Exception):
    code = "pipeline_error"
    retryable = False

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ConfigurationError(PipelineError):
    code = "configuration_error"


class AudioValidationError(PipelineError):
    code = "audio_validation_error"


class JobNotFoundError(PipelineError):
    code = "job_not_found"


class StorageError(PipelineError):
    code = "storage_error"
    retryable = True


class PermanentProcessingError(PipelineError):
    code = "permanent_processing_error"


class TransientProcessingError(PipelineError):
    code = "transient_processing_error"
    retryable = True


class QueueingError(TransientProcessingError):
    code = "queueing_error"


class PermanentProviderError(PermanentProcessingError):
    code = "permanent_provider_error"


class TransientProviderError(TransientProcessingError):
    code = "transient_provider_error"
