import unittest

from CloudHandoffCompressor import (
    already_compressed,
    append_prior_provider_block,
    build_cloud_handoff_prompt,
    prepare_cloud_coding_prompt,
)


class CloudHandoffCompressorTests(unittest.TestCase):
    def test_already_compressed_detects_marker(self):
        text = "[BLOSSOM SESSION SUMMARY — compressed for handoff]\nGoal: fix bug"
        self.assertTrue(already_compressed(text))

    def test_prepare_compresses_large_enriched_prompt(self):
        huge = "[USER REQUEST]\nFix login\n\n" + ("x" * 15000)
        cloud_prompt, stats = prepare_cloud_coding_prompt(
            "[USER REQUEST]\nFix login",
            enriched=huge,
            local_attempt="ESCALATE_CLOUD: need help with auth flow",
            web_block="",
            summarize_fn=lambda _raw: None,
        )
        self.assertTrue(stats.get("compressed"))
        self.assertLess(stats["compressed_chars"], stats["raw_chars"])
        self.assertIn("BLOSSOM SESSION SUMMARY", cloud_prompt)
        self.assertIn("Fix login", cloud_prompt)
        self.assertIn("auth flow", cloud_prompt)

    def test_prepare_skips_when_summary_present(self):
        enriched = (
            "[BLOSSOM SESSION SUMMARY — compressed for handoff]\n"
            "Goal: already done\n\n"
            "<<<FILE path='big.py'>>>\n" + ("z" * 5000)
        )
        cloud_prompt, stats = prepare_cloud_coding_prompt(
            enriched,
            enriched=enriched,
            summarize_fn=lambda _raw: None,
        )
        self.assertTrue(stats.get("skipped"))
        self.assertNotIn("zzzz", cloud_prompt)

    def test_append_prior_provider_block(self):
        base = build_cloud_handoff_prompt(
            summary_markdown="[BLOSSOM SESSION SUMMARY — compressed for handoff]\nGoal",
            user_text="Do thing",
        )
        extended = append_prior_provider_block(base, "gemini", "Failed: rate limit")
        self.assertIn("[PRIOR ESCALATION ATTEMPT — gemini]", extended)
        self.assertIn("rate limit", extended)
        self.assertIn("Do thing", extended)


if __name__ == "__main__":
    unittest.main()
