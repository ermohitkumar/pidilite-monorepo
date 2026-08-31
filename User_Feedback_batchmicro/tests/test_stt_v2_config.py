"""STT v2 telephony config used by the pipeline."""
from services.shared.stt_client import build_recognition_config
from services.shared.stt_config import STT_V2_MODEL


def test_build_config_uses_telephony_and_auto_decode():
    cfg = build_recognition_config("hi-IN", "latest_long")
    assert cfg.model == STT_V2_MODEL
    assert list(cfg.language_codes) == ["hi-IN"]
    assert cfg.auto_decoding_config is not None
    assert cfg.features.enable_automatic_punctuation is True
    assert not cfg.features.diarization_config.min_speaker_count


def test_build_config_keeps_explicit_v2_model():
    cfg = build_recognition_config("en-IN", "telephony")
    assert cfg.model == "telephony"
    assert list(cfg.language_codes) == ["en-IN"]


def test_output_uri_skipped_when_file_result_has_error():
    from google.cloud.speech_v2.types import cloud_speech
    from google.longrunning import operations_pb2
    from google.rpc import status_pb2

    from services.shared.stt_client import (
        file_error_from_operation,
        output_uri_from_operation,
    )

    parsed = cloud_speech.BatchRecognizeResponse(
        results={
            "gs://bucket/file.mp3": cloud_speech.BatchRecognizeFileResult(
                error=status_pb2.Status(code=7, message="Permission denied to access GCS object"),
                cloud_storage_result=cloud_speech.CloudStorageResult(
                    uri="gs://out/stt-output/job/file_transcript_x.json"
                ),
            )
        }
    )
    op = operations_pb2.Operation(done=True)
    op.response.type_url = "type.googleapis.com/google.cloud.speech.v2.BatchRecognizeResponse"
    op.response.value = parsed._pb.SerializeToString()

    assert "Permission denied" in (file_error_from_operation(op) or "")
    assert output_uri_from_operation(op) is None
