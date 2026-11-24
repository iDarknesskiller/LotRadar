"""Independent regression test supplied by Codex in its HOLD review of bc9f5b3 (2026-11-24), kept as written.

A completed Refresh review must stop being actionable once the vehicle is relinked to another post.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_delete_listing_refresh import FB, LID, TOY, VINS, RefreshBase


class FrozenReviewRelink(RefreshBase):
    def test_completed_review_is_invalidated_when_the_post_is_relinked(self):
        self.track(0)
        self.findings = {(VINS[0], TOY): ('UNREACHABLE', ['DEALER_LINK_UNAVAILABLE'])}
        _, status = self.run_batch({LID[0]: ('captured', 'unknown')})
        self.assertEqual(status['review'][0]['listing_id'], LID[0])

        self.store.db.execute(
            'UPDATE drafts SET published_url=? WHERE vin=?', (FB[4], VINS[0])
        )
        status = self.get('/api/listing-refresh-status')
        self.assertFalse(
            any(item['vin'] == VINS[0] for item in status['review']),
            'The completed review remained actionable after its Facebook link changed.',
        )


if __name__ == '__main__':
    import unittest
    unittest.main()
