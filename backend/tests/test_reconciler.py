from app.reconciler import TranscriptReconciler


def test_tentative_updates_replace_not_append():
    r = TranscriptReconciler()
    r.update_tentative(1, "hello")
    r.update_tentative(1, "hello world")
    assert r.tentative_text == "hello world"


def test_commit_makes_text_permanent():
    r = TranscriptReconciler()
    r.update_tentative(1, "hello wor")
    result = r.commit_segment(1, "hello world")
    assert result.emit == {
        "kind": "committed",
        "segment_id": 1,
        "text": "hello world",
        "start_ms": None,
        "end_ms": None,
    }
    assert r.committed_text() == "hello world"
    assert r.tentative_text == ""


def test_committed_text_is_immutable_after_commit():
    r = TranscriptReconciler()
    r.commit_segment(1, "first segment")
    # A late duplicate commit for the same id must be dropped, not applied.
    result = r.commit_segment(1, "corrupted text")
    assert result.emit is None
    assert r.committed_text() == "first segment"


def test_late_tentative_for_committed_segment_is_dropped():
    r = TranscriptReconciler()
    r.commit_segment(1, "done")
    result = r.update_tentative(1, "should not appear")
    assert result.emit is None
    assert r.tentative_text == ""


def test_append_only_across_multiple_segments():
    r = TranscriptReconciler()
    r.update_tentative(1, "hello")
    r.commit_segment(1, "hello")
    r.update_tentative(2, "world")
    r.commit_segment(2, "world")
    assert r.committed_text() == "hello world"
    assert [s.segment_id for s in r.committed_segments] == [1, 2]


def test_repeated_words_are_preserved_not_deduped():
    r = TranscriptReconciler()
    r.commit_segment(1, "very very important")
    r.commit_segment(2, "very very important")
    assert r.committed_text() == "very very important very very important"


def test_new_segment_without_explicit_commit_abandons_old_tentative():
    r = TranscriptReconciler()
    r.update_tentative(1, "false start")
    # Provider jumps straight to segment 2 without ever committing 1 (e.g. a
    # VAD false alarm that produced no real speech).
    result = r.update_tentative(2, "actual speech")
    assert result.emit == {"kind": "tentative", "segment_id": 2, "text": "actual speech"}
    assert r.tentative_text == "actual speech"


def test_discard_segment_clears_tentative_without_committing():
    r = TranscriptReconciler()
    r.update_tentative(1, "noise")
    r.discard_segment(1)
    assert r.tentative_text == ""
    assert r.committed_text() == ""
    # And a late tentative/commit for the discarded id is still dropped.
    assert r.commit_segment(1, "noise").emit is None


def test_empty_committed_text_segment_is_not_added_to_committed_list():
    r = TranscriptReconciler()
    r.commit_segment(1, "")
    assert r.committed_segments == []
    assert r.committed_text() == ""
