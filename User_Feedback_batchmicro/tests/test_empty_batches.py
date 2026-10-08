
from core.enums import BatchStatus, JobStatus
from repositories import batch_repository


def test_delete_empty_batches(db_session, create_test_batch, create_test_job):
    empty = create_test_batch(status=BatchStatus.COMPLETED)
    kept = create_test_batch(status=BatchStatus.PROCESSING)
    create_test_job(status=JobStatus.COMPLETED, batch_id=kept.id)

    deleted = batch_repository.delete_empty_batches(db_session)
    assert deleted >= 1
    assert batch_repository.get_batch(db_session, empty.id) is None
    assert batch_repository.get_batch(db_session, kept.id) is not None


def test_evaluate_deletes_empty_batch(db_session, create_test_batch):
    empty = create_test_batch(status=BatchStatus.PROCESSING)
    assert batch_repository.evaluate_batch_status(db_session, empty.id) is True
    assert batch_repository.get_batch(db_session, empty.id) is None
